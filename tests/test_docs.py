"""The README makes checkable claims, so they are checked.

A verification tool whose own front page overstates what it does is not a small
irony — it is the same failure it exists to prevent, and it happened: the status
line asserted the backends were unimplemented for three phases after they
shipped. A written rule did not catch that. These do.

Nothing here needs a CAD engine; it is all parsing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from partspec.status import EXIT_USAGE, Verdict, exit_code

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
EXAMPLE = ROOT / "examples" / "spacer" / "spec.py"


def _check_calls(source: str) -> list[str]:
    """The sequence of `p.<check>(...)` calls inside `spacer()`, normalised.

    Compares the call *shape* rather than the source text, so reformatting or
    inlining a constant does not fail the test but adding, dropping or
    reordering a check does.
    """
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "spacer")
    calls = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            args = [ast.unparse(a) for a in node.args]
            kwargs = [f"{k.arg}=" for k in node.keywords]
            calls.append(f"{node.func.attr}({', '.join(args + kwargs)})")
    return calls


def _first_python_block(markdown: str) -> str:
    match = re.search(r"```python\n(.*?)```", markdown, re.S)
    assert match is not None, "the README no longer contains a python example"
    return match.group(1)


def test_the_readme_example_is_the_real_contract():
    """The front-page example must be the contract that actually runs.

    It previously showed a `bayonet_lock.scad` call that would not have worked —
    the library needs `method=`, which the example omitted. An example nobody can
    run is a claim nobody can check.
    """
    assert _check_calls(_first_python_block(README.read_text())) == _check_calls(
        EXAMPLE.read_text()
    )


def test_the_readme_console_output_matches_the_contract():
    """Every check the example declares appears in the transcript, and the tally
    agrees. `builds` is added by the tool, hence the +1."""
    readme = README.read_text()
    transcript = re.search(r"```console\n\$ partspec check.*?```", readme, re.S)
    assert transcript is not None, "the README no longer shows a check transcript"
    body = transcript.group(0)

    declared = len(_check_calls(EXAMPLE.read_text()))
    shown = len(re.findall(r"^\s+ok\s+\S+", body, re.M))
    assert shown == declared + 1, "transcript check count disagrees with the contract"
    assert f"PASS: {shown} pass" in body, "the transcript's tally disagrees with its own lines"


@pytest.mark.parametrize(
    ("verdict", "described"),
    [
        (Verdict.PASS, "pass"),
        (Verdict.FAIL, "fail"),
        (Verdict.INCOMPLETE, "incomplete"),
        (Verdict.EMPTY, "empty"),
        (Verdict.ERROR, "error"),
    ],
)
def test_the_readme_exit_codes_match_the_implementation(verdict: Verdict, described: str):
    """The exit codes are the machine-readable half of the product contract
    (`SPEC-report.md` §6.2), so the README's table of them must not drift."""
    line = next(ln for ln in README.read_text().splitlines() if ln.startswith("codes: `0` pass"))
    assert f"`{exit_code(verdict)}` {described}" in line


def test_the_readme_documents_the_usage_exit_code():
    assert f"`{EXIT_USAGE}` bad usage" in README.read_text()


def test_the_readme_does_not_claim_the_backends_are_unimplemented():
    """Pins the specific regression. Both README.md and AGENTS.md asserted the
    contract API and geometry backends did not exist, through P1-P5 shipping
    them."""
    for doc in (README, ROOT / "AGENTS.md"):
        text = doc.read_text().lower()
        assert "backends are\nnot" not in text, doc.name
        assert "nothing useful to run yet" not in text, doc.name


def test_readme_links_survive_pypi():
    """pyproject embeds README.md verbatim as the wheel's long description, so
    a repo-relative link 404s on pypi.org. Absolute blob URLs or nothing (#61).
    """
    text = README.read_text()
    # Positive invariant, not banned prefixes: `](./docs/`, a root-file link
    # (`](LICENSE)`) or a reference-style definition would evade a denylist
    # while 404ing identically. Every markdown link target must be absolute
    # or an in-page anchor.
    for target in re.findall(r"\]\(([^)]+)\)", text):
        assert re.match(r"^(https?://|#)", target), f"README link would 404 on PyPI: {target}"
    assert "<a href=" not in text
    assert not re.search(r"^\[[^\]]+\]:", text, re.MULTILINE), "reference-style link definition"


def test_readme_agent_claim_matches_the_convergence_record():
    """The README's agent paragraph quotes the eval result; pinned to the
    evidence so the claim cannot outlive the record (#62)."""
    import json

    data = json.loads((ROOT / "evals" / "convergence-20260807" / "results.json").read_text())
    records = data["trials"]
    assert len({t["case"] for t in records}) == 5
    assert all(t["outcome"] == "converged" and t["turns_to_converge"] == 1 for t in records)
    # "without once weakening its contract" is a claim about `gamed`, so it is
    # pinned to the counter, not inferred from convergence.
    assert data["summary"]["gamed"] == 0
    assert "five defect classes in" in README.read_text()
