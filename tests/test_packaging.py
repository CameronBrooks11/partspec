"""What the published artifact promises, held against what it contains.

The publish surface is the one place this project's thesis could fail without
any test noticing, because nothing else in the suite installs the wheel or
reads the release path. Two properties here were actually wrong: a typed
package that shipped no type marker, and a release workflow whose entire
safety argument rested on a convention it did not enforce.
"""

from __future__ import annotations

import re
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())
GATE = REPO / "scripts" / "assert_tag_on_main.sh"


def _live_lines(path: Path) -> str:
    """A workflow with comment lines removed.

    A grep over YAML cannot tell a live step from prose about one: deleting
    the gate step while leaving its words in a comment passed the first
    version of these tests.
    """
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def test_the_package_ships_its_type_marker():
    """PEP 561: without `py.typed`, a downstream type checker does not check
    partspec *less* — it skips the package entirely and reports nothing.

    Measured before the marker existed, with a deliberate type error in a
    one-line consumer against the installed wheel:

        without:  Skipping analyzing "partspec": module is installed, but
                  missing library stubs or py.typed marker
        with:     error: Incompatible types in assignment

    The consumer's real error was not reported at all. That is this project's
    own thesis — silence reading as success — on its PyPI surface.
    """
    assert (REPO / "src" / "partspec" / "py.typed").is_file()


# ---------------------------------------------------------------------------
# the release gate, exercised rather than grepped
# ---------------------------------------------------------------------------


def _repo_with_history(root: Path) -> tuple[str, str]:
    """A throwaway git repo: returns (commit on main, commit off main)."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "--quiet", "--initial-branch=main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (root / "f").write_text("1\n")
    git("add", "f")
    git("commit", "--quiet", "-m", "one")
    on_main = git("rev-parse", "HEAD")

    git("checkout", "--quiet", "-b", "sidebranch")
    (root / "f").write_text("2\n")
    git("commit", "--quiet", "-am", "two")
    off_main = git("rev-parse", "HEAD")
    git("checkout", "--quiet", "main")
    return on_main, off_main


def _run_gate(root: Path, commit: str, main_ref: str = "main") -> subprocess.CompletedProcess:
    return subprocess.run([str(GATE), commit, main_ref], cwd=root, capture_output=True, text=True)


def test_the_release_gate_publishes_a_commit_on_main(tmp_path: Path):
    on_main, _ = _repo_with_history(tmp_path)
    assert _run_gate(tmp_path, on_main).returncode == 0


def test_the_release_gate_blocks_a_commit_that_is_not_on_main(tmp_path: Path):
    """The hole this closes: `release.yml` runs no tests, so main's `ok` gate
    is the only thing between a commit and PyPI. A tag pointing anywhere else
    published code no gate ever saw.

    Exercised against a real repository rather than grepped out of the YAML,
    because a grep proves a string is present, not that anything blocks —
    dropping one `!` from the old inline version left it green and inert.
    """
    _, off_main = _repo_with_history(tmp_path)
    result = _run_gate(tmp_path, off_main)
    assert result.returncode == 1
    assert f"{off_main} is not on main" in result.stdout


def test_the_release_gate_on_the_shape_production_actually_uses(tmp_path: Path):
    """Every other fixture here names the ref `main`; production passes
    `origin/main`, a remote-tracking ref. The combination that matters most —
    resolvable origin/main AND true ancestry — was the one no test covered,
    which would have made release day its first execution.
    """
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    on_main, off_main = _repo_with_history(upstream)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", str(upstream), str(clone)], check=True)
    assert _run_gate(clone, on_main, "origin/main").returncode == 0
    assert _run_gate(clone, off_main, "origin/main").returncode == 1


def test_the_release_gate_refuses_rather_than_assumes_when_it_cannot_tell(tmp_path: Path):
    """A shallow checkout has no `origin/main` to compare against. Answering
    "fine" there would defeat the gate exactly when it is least able to
    judge, so it fails closed and names the cause."""
    on_main, _ = _repo_with_history(tmp_path)
    result = _run_gate(tmp_path, on_main, main_ref="origin/main")
    assert result.returncode == 1
    assert "cannot resolve" in result.stdout
    assert "fetch-depth: 0" in result.stdout


def test_the_release_workflow_calls_the_gate_and_gives_it_the_history_it_needs():
    """The gate itself is exercised above; this holds the wiring.

    Comment lines are stripped first, because a grep over YAML cannot tell a
    live step from prose about one — deleting the step while leaving the
    words in a comment passed the first version of this test.
    """
    live = _live_lines(REPO / ".github" / "workflows" / "release.yml")

    # Anchored to the whole line. An unanchored match is satisfied by a call
    # ending `|| true`, which is one token from inert — the same one-character
    # neutering the gate was moved into a script to prevent, relocated to the
    # call site.
    assert re.search(
        r'^\s*(?:run: )?scripts/assert_tag_on_main\.sh "\$GITHUB_SHA" origin/main\s*$',
        live,
        re.M,
    ), "the gate must be called, unqualified, with the tagged commit and main"
    assert "continue-on-error" not in live, "a gate that cannot fail the job is not a gate"
    assert "fetch-depth: 0" in live, "ancestry cannot be checked against a shallow clone"
    assert "does not match version" in live, "the tag must match the declared version"
    assert re.search(r"^\s*needs: \[build\]", live, re.M), (
        "publish must depend on the job that runs the gate"
    )


def test_the_workflows_declare_their_permissions_and_serialise_releases():
    release = _live_lines(REPO / ".github" / "workflows" / "release.yml")
    ci = _live_lines(REPO / ".github" / "workflows" / "ci.yml")
    for name, text in (("release.yml", release), ("ci.yml", ci)):
        assert re.search(r"^permissions:\n  contents: read$", text, re.M), (
            f"{name} must declare read-only permissions rather than inherit a repo setting"
        )
    assert re.search(r"^  group: release$", release, re.M), (
        "one release at a time across ALL tags; `release-${{ github.ref }}` is per-tag "
        "and serialises nothing between two different versions"
    )


def test_every_pypi_publish_action_is_pinned_to_a_digest():
    """The one action holding the OIDC identity for PyPI. `@release/v1` is a
    mutable branch: whatever it points at on the day of a release is what runs
    with permission to publish.

    Every occurrence, not the first — checking only `re.search` let a second,
    unpinned publish step be appended below the pinned one.
    """
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text()
    uses = re.findall(r"uses:\s*pypa/gh-action-pypi-publish@(\S+)", workflow)
    assert uses, "the publish step must still exist"
    unpinned = [ref for ref in uses if not re.fullmatch(r"[0-9a-f]{40}", ref)]
    assert not unpinned, f"publish actions must be SHA-pinned, not {unpinned}"


# ---------------------------------------------------------------------------
# the sdist
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sdist_names(tmp_path_factory) -> set[str]:
    """Every path inside the built sdist, package-prefix stripped.

    Skipped outside a checkout, or without the build frontend. These two
    tests ask what THIS repository publishes; inside the published artifact
    the question is already answered, and a distro packager building offline
    without `uv` would otherwise see the only two tests about their own use
    case error out.
    """
    import shutil

    if shutil.which("uv") is None or not (REPO / ".git").exists():
        pytest.skip("inspects what this checkout publishes; needs a checkout and the uv frontend")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    tarball = next(out.glob("*.tar.gz"))
    with tarfile.open(tarball) as archive:
        return {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}


def test_the_sdist_carries_everything_the_suite_reads(sdist_names: set[str]):
    """`tests/` ships so a downstream packager can run the suite, and that
    claim is only worth making if it holds. The first draft of the exclude
    list cut `.github/`, `evals/` and `notes/` and broke five tests inside
    the sdist — two of them tests added by the same commit — which is the
    same failure this slice exists to fix, committed while fixing it.

    These are the repo paths the suite actually reads, found by grepping the
    tests for their own fixtures.
    """
    required = [
        "tests/conftest.py",
        "docs/SPEC-contract.md",
        "docs/FAILURE-MODES.md",
        "examples/bearing-block/claims.py",
        "skills/contract-authoring/SKILL.md",
        "evals/CONVERGENCE.md",
        "notes/dogfood-results.md",
        ".github/workflows/release.yml",
        "scripts/assert_tag_on_main.sh",
        "src/partspec/py.typed",
    ]
    missing = [path for path in required if path not in sdist_names]
    assert not missing, f"the suite reads these and the sdist does not carry them: {missing}"


def test_no_test_shells_out_to_git_without_a_checkout_guard():
    """The invariant behind the claim above, since nothing enforces the claim.

    `tests/` ships so a downstream packager can run the suite, and
    `pyproject.toml` argues that only holds if the suite passes from an sdist —
    which has no `.git`. It did not hold from #151 until PR #155:
    `test_docs.py` called `git ls-files` with `check=True` and errored out with
    exit 128 there. Rebuilding an sdist to catch the next one would double CI, so
    this asserts the property that actually breaks instead: a test that runs git
    must also know it might not be in a checkout.

    Textual on purpose — it is a lint over test sources, not a behaviour — and
    scoped to `["git"` because that is how every current caller spells it. A
    caller that builds its argv some other way slips past; the point is to catch
    the copy-paste shape that has now caused this once, not to be a type system.
    """
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        text = path.read_text()
        if '["git"' in text and '".git"' not in text:
            offenders.append(path.name)
    assert not offenders, (
        "these shell out to git with no `(ROOT / '.git').exists()` guard, so they "
        f"error rather than skip in an unpacked sdist: {offenders}"
    )


def test_the_sdist_leaves_out_what_a_consumer_cannot_use(sdist_names: set[str]):
    """`uv.lock` pins this repo's dev environment, which says nothing about the
    package's own requirements, so a consumer cannot use it.

    Excluding it saves ~160 KiB, ~23% of the tarball — measured by building both
    ways. This docstring said "27% ... half a megabyte" until PR #155's review
    found the same two figures already corrected in `pyproject.toml` and not
    here, in the test that actually enforces the exclusion. The absolute sizes
    are deliberately absent: four measurements taken while editing this PR's own
    prose gave four different answers, because every line added to the repo lands
    in the tarball. Only the delta and the share hold still."""
    assert "uv.lock" not in sdist_names
    assert "CLAUDE.md" not in sdist_names
    assert "pyproject.toml" in sdist_names, "and the things a build needs are still there"
    assert "README.md" in sdist_names


def test_the_project_urls_point_at_things_that_exist():
    """Presence of the keys is not the claim; the claim is that a reader
    following them arrives somewhere. The two that name in-repo files are
    checked against the repo."""
    urls = PYPROJECT["project"]["urls"]
    assert {"Repository", "Issues", "Changelog", "Documentation"} <= set(urls)
    assert urls["Changelog"].endswith("/CHANGELOG.md")
    assert (REPO / "CHANGELOG.md").is_file()
    assert urls["Documentation"].rstrip("/").endswith("/docs")
    assert (REPO / "docs").is_dir()
