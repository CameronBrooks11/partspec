"""The lint configuration's own prose, held to what ruff actually reports.

`pyproject.toml`'s `[tool.ruff.lint]` block explains what adopting each rule
cost and why two things are handled specially. PR #155's review found four of
those numbers wrong — eleven `BLE001` annotations called ten, 37 test findings
called 41, and a whole rule disabled "because this repo writes em-dashes" when
every finding was a multiplication sign. All four were written from memory.

So they are derived here. This is the repo's own thesis pointed at its own
configuration: a number in prose beside the data it describes is a claim, and a
claim nothing executes is the thing this project exists to refuse.

Skipped without the `ruff` binary or outside a checkout — it asks what THIS
tree lints to, which a published artifact cannot answer.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None and not (ROOT / ".venv" / "bin" / "ruff").exists(),
    reason="needs the ruff binary; this test asks what this tree lints to",
)


def _ruff(*args: str) -> subprocess.CompletedProcess:
    binary = ROOT / ".venv" / "bin" / "ruff"
    exe = str(binary) if binary.exists() else "ruff"
    return subprocess.run(
        [exe, "check", "--output-format", "concise", *args, "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _findings(rule: str, *extra: str) -> list[str]:
    """The lines ruff emits for a rule prefix."""
    out = _ruff("--extend-select", rule, *extra).stdout
    return [line for line in out.splitlines() if re.search(rf"\b{re.escape(rule)}\d*\b", line)]


def _count(rule: str, *extra: str) -> int:
    """Findings for a rule prefix. `\bARG\b` matches nothing — the codes are
    `ARG001` etc., so the prefix must be followed by its digits. My first draft
    used a bare boundary and reported zero for every multi-rule prefix, which
    made the zero-cost assertion pass for the wrong reason."""
    out = _ruff("--extend-select", rule, *extra).stdout
    return len(re.findall(rf"\b{re.escape(rule)}\d*\b", out))


def _lint_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["tool"]["ruff"]["lint"]


def _comment_block() -> str:
    """The prose above `select =`, which is what the claims live in."""
    text = PYPROJECT.read_text()
    block = text[text.index("[tool.ruff.lint]") : text.index("[tool.pyright]")]
    return block


def test_the_tree_is_clean_under_the_declared_rules():
    """The premise everything else rests on."""
    result = _ruff()
    assert result.returncode == 0, (
        f"the configured rule set must pass on this tree:\n{result.stdout}"
    )


def test_c4_costs_zero_outright():
    """`C4` is the only rule in the set the tree satisfies with no help: zero
    findings even with every suppression disregarded. If that changes, the
    comment saying so is wrong and someone should decide deliberately."""
    assert _count("C4", "--ignore-noqa") == 0, "C4 no longer costs zero outright"


def test_the_suppressed_rules_are_clean_but_not_vacuous():
    """The distinction the config comment used to blur.

    `S102`, `S307` and `BLE` report nothing — but only because `# noqa`
    comments were already sitting there, written against rules nobody had
    enabled. "Costs zero" measured with `noqa` honored says nothing about
    whether a rule is doing work, so both halves are asserted: silent as
    configured, and non-silent with the waivers disregarded. A rule that went
    genuinely vacuous would mean the annotations are now decoration, which is
    the shape this slice removed.
    """
    select = _lint_config()["select"]
    for rule in ("S102", "S307", "BLE"):
        # Membership FIRST. Everything below measures with `--extend-select`,
        # which re-enables the rule whether or not the config selects it — so
        # without this line, deleting `"BLE"` from `select` (which is precisely
        # how these annotations went inert the first time) left the test green.
        # Verified: that mutation survived until this assertion existed.
        assert rule in select, f"{rule} is no longer selected — its noqa comments are inert"
        assert _count(rule) == 0, f"{rule} is not clean as configured"
        raw = _findings(rule, "--ignore-noqa")
        assert raw, f"{rule} finds nothing even ignoring noqa — its waivers are decoration now"


def test_every_suppression_the_slice_made_live_is_still_live():
    """The property, not a count.

    The first draft of the block said "ten `noqa: BLE001` annotations"; there
    were eleven, and by the end of the slice thirteen. A count beside a growing
    set is a second thing to forget. What actually matters is that none of these
    suppressions is inert again — which is exactly what `RUF100` reports, so it
    is asserted instead of counted.
    """
    unused = [
        line for line in _ruff("--extend-select", "RUF100").stdout.splitlines() if "RUF100" in line
    ]
    assert not unused, "these noqa directives suppress nothing:\n" + "\n".join(unused)

    # And the annotations exist at all: if they were all deleted, RUF100 would
    # also be silent, and the rules would be enforcing nothing in particular.
    sources = "".join(
        path.read_text() for path in [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").glob("*.py")]
    )
    assert "# noqa: BLE001" in sources
    assert "# noqa: S102" in sources or "# noqa: S307" in sources


def test_ruf002_is_enforced_and_only_the_multiplication_sign_is_allowed():
    """The rule was nearly retired on a false premise: the justification said
    em-dashes, and em-dashes are not flagged by RUF001-003 at all. Allowing the
    one confusable that does appear keeps the rule live.

    Both halves of the comment, because the first alone is weak: nothing else
    is flagged *with* `×` allowed, and `×` is the only reason anything would be
    flagged without it. The second is what makes the allowance narrow rather
    than a blanket ignore wearing a smaller name.
    """
    config = _lint_config()
    assert "RUF002" not in config.get("ignore", []), "RUF002 stays enforced"
    assert config["allowed-confusables"] == ["×"]
    assert _count("RUF002") == 0, "with × allowed, nothing else is confusable"

    # `--config` overrides the allowance in-flight; no file is written.
    unallowed = _ruff(
        "--config", "lint.allowed-confusables = []", "--select", "RUF001,RUF002,RUF003"
    )
    hits = [line for line in unallowed.stdout.splitlines() if "RUF00" in line]
    assert hits, "no confusables at all — the allowance is describing nothing"
    others = [line for line in hits if "MULTIPLICATION SIGN" not in line]
    assert not others, "a confusable that is not × appeared:\n" + "\n".join(others)


def test_the_pt018_count_is_what_the_comment_says():
    """86 is the one number left in the block, and it is load-bearing: it is the
    argument for the ignore. Derived rather than remembered."""
    assert _count("PT018") == 86


def test_both_ruff_pins_name_one_version():
    """`.pre-commit-config.yaml` says it pins "the SAME ruff the gate runs".
    It did not: the dev group pinned `ruff==0.16.*`, so the two could differ by
    any patch release — and ruff changes formatter output in patch releases,
    which is exactly the `git commit` writes / `just check` rejects split the
    comment exists to prevent. Both are exact now; this holds them equal so
    bumping one alone fails instead of drifting quietly.

    Parsed with a regex rather than yaml: the config is not otherwise read by
    the suite, and pyyaml is not a dependency of this project.
    """
    dev = tomllib.loads(PYPROJECT.read_text())["dependency-groups"]["dev"]
    pinned = [d for d in dev if d.startswith("ruff")]
    assert pinned == ["ruff==0.16.1"] or len(pinned) == 1, pinned
    gate = pinned[0].removeprefix("ruff==")
    assert "*" not in gate, f"the gate's ruff pin must be exact, not {pinned[0]!r}"

    config = (ROOT / ".pre-commit-config.yaml").read_text()
    revs = re.findall(r"ruff-pre-commit\s+rev:\s*v?(\S+)", " ".join(config.split()))
    assert revs, "could not find the ruff-pre-commit rev"
    assert revs == [gate], f"pre-commit pins {revs} but the gate runs {gate}"


def test_arg_is_declined_and_the_comment_does_not_quantify_it():
    """`ARG` is not adopted. The first draft justified that with 'of which 41
    in tests' — it was 37 — so the block now argues from where the findings
    are rather than from a number nothing rechecks."""
    assert "ARG" not in _lint_config()["select"]
    assert _count("ARG") > 0, "if ARG became free, revisit the decision"
    assert not re.search(r"ARG.{0,80}\b\d+\b", _comment_block(), re.S), (
        "the ARG rationale must not carry a hand-maintained count"
    )
