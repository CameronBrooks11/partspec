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
    assert doc["unavailable"] == ["topology_counts", "bores", "blend_radii"]
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
# measure — identity (#47): as identifiable as a report
# --------------------------------------------------------------------------


@needs_openscad
def test_measure_carries_the_same_identity_as_the_report(tmp_path: Path, capsys):
    """One builder serves both verbs, and this pin is what keeps them from
    drifting apart again (#73 was exactly that drift, in the engine block).
    A consumer turning measure output into checks must be able to say which
    file, which revision, and which parameters produced the numbers."""
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())

    doc = _measure(target, capsys)
    assert doc["schema_version"] == report["schema_version"]
    assert doc["part"] == report["part"]
    assert doc["params"] == report["params"]
    assert list(doc)[:7] == [
        "schema_version",
        "tool",
        "part",
        "engine",
        "params",
        "geometry",
        "measurements",
    ]


@needs_openscad
def test_measure_records_the_parameters_that_produced_the_numbers(tmp_path: Path, capsys):
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('block_with_hole.scad', hole=4))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    assert doc["params"] == {"hole": 4}


@needs_openscad
def test_measure_failure_is_an_artifact_not_a_shrug(tmp_path: Path, capsys):
    """A caller parsing stdout used to get an empty string and a bare exit
    code, with the reason on stderr only — machine-invisible exactly where a
    machine is the audience (#47)."""
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad'))\n"
    )
    assert main(["measure", f"{module}:make"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["schema_version"] == 1
    assert doc["part"]["id"] == "subject"
    assert doc["part"]["contract"].endswith("spec.py")
    assert "not found" in doc["error"]
    assert "hint" in doc
    assert "not found" in captured.err, "the console courtesy line survives"


def test_measure_python_closure_appears_after_the_build(tmp_path: Path, capsys):
    """A Python model's inputs are only knowable once it has run; measure's
    identity must carry the same imports-derived closure the report does."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helper47.py").write_text("SIZE = 2\n")
    (tmp_path / "model.py").write_text(
        "import helper47\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper47.SIZE, 1, 1)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('model.py'))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    closure = doc["part"]["source_closure"]
    assert closure["scope"] == "model_directory"
    assert closure["partial"] is True
    assert closure["files"] >= 2, "the helper the model imported is a build input"


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


def test_render_on_a_python_engine_target_is_usage_not_a_crash(tmp_path: Path):
    (tmp_path / "m.py").write_text("")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    assert main(["render", f"{module}:make"]) == 64


@needs_openscad
def test_render_writes_the_views_or_reports_the_display(tmp_path: Path, capsys):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    code = main(["render", target])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert set(payload["renders"]) == {"iso", "front", "top", "right"}
        for path in payload["renders"].values():
            assert Path(path).stat().st_size > 0
    else:
        assert code == 4
        assert "display" in captured.err


@needs_openscad
def test_check_render_records_the_views_in_the_report_or_fails_the_run(tmp_path: Path):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--quiet", "--render", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    if code == 0:
        # Relative POSIX paths keyed by view, resolving against the report's
        # own directory (SPEC-report.md section 8.4).
        assert set(report["renders"]) == {"iso", "front", "top", "right"}
        for rel in report["renders"].values():
            assert not Path(rel).is_absolute()
            assert (out / rel).stat().st_size > 0
    else:
        # No display: the run fails loudly and the key is absent — the report
        # speaks for the part, the exit code for the run.
        assert code == 4
        assert "renders" not in report
        assert report["verdict"] == "pass"


@needs_openscad
def test_a_report_without_render_carries_no_renders_key(tmp_path: Path):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    assert "renders" not in json.loads((out / "report.json").read_text())


def test_check_render_on_a_python_engine_target_is_usage(tmp_path: Path):
    (tmp_path / "m.py").write_text("")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    assert main(["check", f"{module}:make", "--render", "--quiet"]) == 64


@needs_openscad
def test_measure_engine_block_matches_the_report_shape(tmp_path: Path, capsys):
    # measure and check had drifted (#73): wrong key order, no method. One
    # constructor now serves both, so a measure artifact answers the same
    # provenance questions a report does.
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    payload = _measure(target, capsys)
    assert list(payload["engine"]) == [
        "kind",
        "version",
        "backend",
        "render_backend",
        "adopted_via",
        "method",
        "param_mode",
    ]
    assert payload["engine"]["method"] is None
    assert payload["engine"]["param_mode"] == "define"


@needs_openscad
def test_render_engine_block_states_the_method(tmp_path: Path, capsys):
    (tmp_path / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('lib.scad', method='block', s=8.0))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert payload["engine"]["method"] == "block"
        assert payload["engine"]["param_mode"] == "call"
    else:
        assert code == 4  # no display; the refusal path is asserted elsewhere
