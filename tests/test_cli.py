"""The CLI surface: `measure`'s output shape and `check`'s exit code.

D5 makes the report schema plus the exit code the product contract, not the
verbs — which is precisely why the verbs need tests. Everything below asserts
something a consumer would break on.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from support import needs_openscad

from partspec.cli import main
from partspec.status import Verdict, exit_code

pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"


def _contract(tmp_path: Path, scad: str, body: str) -> str:
    """Write a contract module next to a copy of its source, return its target."""
    shutil.copy(FIXTURES / scad, tmp_path / scad)
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part('subject', openscad({scad!r}))\n"
        f"{body}"
        "    return p\n"
    )
    return f"{module}:make"


def _measure(target: str, capsys) -> dict:
    assert main(["measure", target]) == 0, "measure never produces a verdict"
    return json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# measure — the adoption path
# --------------------------------------------------------------------------


@needs_openscad
def test_measure_reports_the_quantities_it_can_answer(tmp_path: Path, capsys):
    doc = _measure(_contract(tmp_path, "block_with_hole.scad", ""), capsys)
    assert doc["engine"]["backend"] == "mesh"
    assert doc["measurements"]["volume"]["value"] == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)
    assert "refused" not in doc, "a sound part refuses nothing"


@needs_openscad
def test_measure_says_why_it_refused_rather_than_omitting_the_quantity(tmp_path: Path, capsys):
    """The bug this replaced, and the reason it mattered.

    `measure` dropped every `Unsupported` silently. That was honest while a
    refusal only ever meant "this tier cannot answer this quantity" — a static
    fact, the same for every part. Since D17 it also means "this part is
    broken, and here is the defect", and the two arrived identically: absent.

    On an open box that leaves a reader looking at area, bbox and solid_count
    with no volume line, in the verb whose whole job is showing you the numbers
    before you decide which are intent. They would write a contract that
    declines to claim a volume, and the omission would have taught them that.
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)

    assert set(doc["refused"]) == {"volume", "center_of_mass", "genus"}
    for name, reason in doc["refused"].items():
        assert "boundary edge" in reason, f"{name} must name the defect, not just decline"
        assert name not in doc["measurements"], "a refusal must not also carry a number"

    assert doc["measurements"]["watertight"]["value"] is False
    assert doc["measurements"]["area"]["value"] == pytest.approx(500.0)


@needs_openscad
def test_measure_separates_a_tier_gap_from_a_broken_part(tmp_path: Path, capsys):
    """Two different silences, and conflating them is what went wrong before.

    `unavailable` is a property of the backend and identical for every part it
    will ever see. `refused` is a property of *this* part. A reader deciding
    what to assert needs to tell "you need the OCCT tier for that" apart from
    "fix your model".
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)
    assert doc["unavailable"] == ["topology_counts"]
    assert "topology_counts" not in doc["refused"]


@needs_openscad
def test_measure_produces_no_verdict_on_a_broken_part(tmp_path: Path, capsys):
    """Exit 0 on an open box is correct here and would be a bug in `check`.

    `measure` asks no question, so it cannot answer one wrongly. The verdict
    machinery deliberately does not run.
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)
    assert "verdict" not in doc and "checks" not in doc


# --------------------------------------------------------------------------
# check — the exit code is half the contract
# --------------------------------------------------------------------------


@needs_openscad
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("    p.watertight()\n", Verdict.PASS),
        ("    p.envelope(max=(1, 1, 1))\n", Verdict.FAIL),
        ("    p.topology(faces=6)\n", Verdict.INCOMPLETE),
        ("", Verdict.EMPTY),
    ],
)
def test_check_exits_with_the_verdicts_code(tmp_path: Path, body: str, expected: Verdict):
    """Every verdict, through `main`, on a real render.

    The exit code is the only thing a CI job reads, so a report that is right
    while the process exits 0 anyway would defeat all of it.
    """
    target = _contract(tmp_path, "block_with_hole.scad", body)
    assert main(["check", target, "--quiet"]) == exit_code(expected)


@needs_openscad
def test_check_writes_the_report_where_it_says_it_did(tmp_path: Path, capsys):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    assert main(["check", target]) == 0
    printed = capsys.readouterr().err.strip().splitlines()[-1].strip()
    doc = json.loads(Path(printed).read_text())
    assert doc["verdict"] == "pass"


def test_an_unresolvable_target_is_a_usage_error_not_a_crash(tmp_path: Path):
    assert main(["check", str(tmp_path / "nope.py")]) == 64
    assert main(["measure", str(tmp_path / "nope.py")]) == 64


@pytest.mark.parametrize("verb", ["check", "measure"])
def test_a_contract_that_raises_does_not_exit_as_a_failing_part(tmp_path: Path, verb: str):
    """Found by mistyping a keyword argument while writing a real contract.

    The traceback escaped `main` and the interpreter exited 1, which is this
    tool's code for *the part failed its contract*. A malformed question would
    have been recorded in CI as a wrong answer about the design, and the two
    are indistinguishable from the outside. Exit 4: nothing was evaluated, so
    nothing may be said about the part.
    """
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def make() -> Part:\n"
        "    return Part('x', openscad('x.scad')).envelope(max=(1, 1, 1), tol=0.05)\n"
    )
    assert main([verb, f"{module}:make"]) == exit_code(Verdict.ERROR)


def test_no_arguments_prints_help(capsys):
    assert main([]) == 64
    assert "usage:" in capsys.readouterr().out


@needs_openscad
def test_a_contract_that_raises_does_not_leave_the_previous_verdict(tmp_path: Path):
    """The regression this ordering exists to prevent.

    `write_placeholder` used to run *after* the contract resolved, so a contract
    that raised returned exit 4 without touching the output directory — leaving
    the previous run's `verdict: "pass"` at the deterministic path. The exit code
    said error and the artifact said the part was fine, and the artifact is what
    a later reader trusts.
    """
    scad = tmp_path / "box.scad"
    scad.write_text("x = 10;\ncube([x, x, x]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n"
        "def part() -> Part:\n"
        "    p = Part('stale', openscad('box.scad', x=10.0))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 0
    report = out / "report.json"
    assert json.loads(report.read_text())["verdict"] == "pass", "premise: a green run on disk"

    spec.write_text(
        "from partspec import Part\ndef part() -> Part:\n    raise RuntimeError('boom')\n"
    )
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert json.loads(report.read_text())["verdict"] == "error", (
        "the previous run's pass survived a contract that raised"
    )


def test_a_contract_calling_sys_exit_is_not_a_green_run(tmp_path: Path):
    """`sys.exit(0)` raises SystemExit, which sailed past `except Exception` and
    exited the process 0 — green, silent, zero checks evaluated. The exit code
    was the contract's to choose: `sys.exit(2)` read as incomplete."""
    spec = tmp_path / "spec.py"
    spec.write_text("import sys\nfrom partspec import Part\ndef part() -> Part:\n    sys.exit(0)\n")
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert json.loads((out / "report.json").read_text())["verdict"] == "error"


def test_argparse_still_owns_its_own_exits():
    """The BaseException guard is scoped to contract resolution, so argparse's
    SystemExit for `--version` and usage errors is untouched."""
    with pytest.raises(SystemExit):
        main(["--version"])
