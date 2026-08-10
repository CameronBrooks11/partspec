"""The lint configuration's own prose, held to what ruff actually reports.

`pyproject.toml`'s `[tool.ruff.lint]` block explains what adopting each rule
cost and why two things are handled specially. PR #155's review found two of
those counts wrong — `BLE001` annotations called ten, really eleven then and
thirteen now; unused-argument findings called "41 in tests", really 37 — plus a
rule disabled "because this repo writes em-dashes" when every finding was a
multiplication sign. Two other numbers it checked were right (`RUF002`'s six, and
55 unused arguments in total), which is the actual defect: nothing distinguished
the wrong ones from the right ones without re-running ruff.

This said "four of those numbers ... all four" while `pyproject.toml` already
said two — one file corrected, its neighbour not, which is the same miss the
review caught in `test_packaging.py`'s docstring one round earlier.

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

# The docstring above promised a skip "outside a checkout" that this guard did
# not implement, and `test_both_ruff_pins_name_one_version` reads
# `.pre-commit-config.yaml` — which the sdist `exclude` list drops on purpose.
# `tests/` ships so a downstream packager can run the suite, so a packager with
# ruff on PATH got a hard FileNotFoundError. The two requirements genuinely
# conflict (either this skips outside a checkout, or the sdist ships a file it
# deliberately excludes), and skipping is the right side: these tests ask what
# THIS tree lints to, which an unpacked sdist cannot answer. Same idiom as
# `test_packaging.py`'s `(REPO / ".git").exists()`. Related: #150.
pytestmark = pytest.mark.skipif(
    (shutil.which("ruff") is None and not (ROOT / ".venv" / "bin" / "ruff").exists())
    or not (ROOT / ".git").exists(),
    reason="asks what this checkout lints to; needs a checkout and the ruff binary",
)


def _ruff(*args: str) -> subprocess.CompletedProcess:
    binary = ROOT / ".venv" / "bin" / "ruff"
    exe = str(binary) if binary.exists() else "ruff"
    result = subprocess.run(
        [exe, "check", "--output-format", "concise", *args, "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 0 = clean, 1 = findings, anything else = ruff could not run (a bad
    # selector, an unparseable config). Without this, every "assert the count is
    # zero" test below passes on an empty stdout from a crashed ruff — silence
    # reading as success, in the file written to refuse exactly that. Found by
    # PR #155's review, which broke the config deliberately: five failed and
    # THREE passed — two of the three of the form "the tool found nothing", the
    # third (`test_both_ruff_pins_name_one_version`) reading only files and so
    # rightly indifferent to whether ruff runs. This said "two passed", which
    # does not sum to eight.
    assert result.returncode in (0, 1), (
        f"ruff could not run (exit {result.returncode}); "
        f"a zero count below would be meaningless:\n{result.stderr.strip()}"
    )
    return result


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
    """The premise everything else rests on.

    Truncated on failure. When CI extracted an OpenSCAD AppImage into the
    checkout, this assertion was correct — the tree really was not clean — but it
    printed every finding in a bundled Python 3.10 stdlib: tens of thousands of
    lines, of which the FIRST named the cause. So nothing was buried under the
    noise; the noise was the problem. Ten lines is enough to see whether the
    paths are yours, and ruff's own trailing count is kept because it says how
    bad it is.
    """
    result = _ruff()
    lines = result.stdout.splitlines()
    shown = "\n".join(lines[:10])
    if len(lines) > 10:
        shown += f"\n... and {len(lines) - 10} more lines\n{lines[-1]}"
    assert result.returncode == 0, f"the configured rule set must pass on this tree:\n{shown}"


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
        # without this line, deleting `"BLE"` from `select` left the test green.
        # Verified: that mutation survived until this assertion existed. It is
        # not the only guard — `ruff check .` then reports thirteen unused-noqa
        # findings, "non-enabled: BLE001", and `just lint` fails, so an inert
        # annotation cannot pass unnoticed. This test names the cause instead of
        # leaving thirteen symptoms. (Wrapped to keep the RUF100 spelling off the
        # start of a line: written the obvious way, this comment WAS a blanket
        # directive, and RUF100 flagged its own explanation.)
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
    # rglob over all three roots: `tests` was globbed non-recursively and
    # `evals` was omitted entirely, though one `noqa: BLE001` lives in
    # `evals/run.py`. The assertion read stronger than it was.
    sources = "".join(
        path.read_text()
        for root in ("src", "tests", "evals")
        for path in (ROOT / root).rglob("*.py")
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
    # Excluding this file: five of the findings are this test's own prose ABOUT
    # `×`, so `assert hits` was partly self-satisfying — it would hold even if
    # every × elsewhere were gone, which is when the allowance stops describing
    # anything.
    elsewhere = [line for line in hits if not line.startswith("tests/test_lint_config.py")]
    assert elsewhere, "the only confusables left are this test's own prose about them"
    others = [line for line in hits if "MULTIPLICATION SIGN" not in line]
    assert not others, "a confusable that is not × appeared:\n" + "\n".join(others)


def test_the_pt018_count_is_what_the_comment_says():
    """86 is the one number left in the block, and it is load-bearing: it is the
    argument for the ignore. Derived rather than remembered."""
    assert _count("PT018") == 86


def test_both_ruff_pins_name_one_version():
    """`.pre-commit-config.yaml` says it pins "the SAME ruff the gate runs".
    It did not: the dev group pinned `ruff==0.16.*`, so the two could differ by
    any patch release. Nothing guarantees two builds format identically, and the
    cost of being wrong is the `git commit` writes / `just check` rejects split
    the comment exists to prevent. Both are exact now; this holds them equal so
    bumping one alone fails instead of drifting quietly.

    Parsed with a regex rather than yaml: the config is not otherwise read by
    the suite, and pyyaml is not a dependency of this project.
    """
    dev = tomllib.loads(PYPROJECT.read_text())["dependency-groups"]["dev"]
    pinned = [d for d in dev if d.startswith("ruff")]
    # One entry, exactly. This read `== ["ruff==0.16.1"] or len(pinned) == 1`,
    # which no realistic tree can fail — and did not fail when the pin was
    # loosened to `0.16.*`; line 2 below caught that. A disjunction whose second
    # arm is always true is not an assertion.
    assert len(pinned) == 1, f"expected one ruff pin in the dev group, got {pinned}"
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
    # Presence first. The regex below forbids a digit near "ARG", which deleting
    # the whole paragraph also satisfies — verified: removing all three lines
    # left this test green until this assertion existed.
    paragraphs = [
        para for para in _comment_block().split("#\n") if "is deliberately NOT adopted" in para
    ]
    assert len(paragraphs) == 1, "the ARG decision must still be explained, not merely dropped"
    # Scoped to that paragraph, not the whole block, which also records the
    # counts the review found WRONG ("41 in tests, really 37"). Citing a
    # retracted number is the opposite of maintaining one by hand; what must
    # stay unquantified is the live rationale.
    assert not re.search(r"ARG.{0,80}\b\d+\b", paragraphs[0], re.S), (
        "the ARG rationale must not carry a hand-maintained count"
    )
