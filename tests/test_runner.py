"""End-to-end: contract in, report out.

These are the tests that would catch the tool lying. Each asserts a claim from
`SPEC-report.md` that the rest of the design depends on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partspec import Part, Status, Verdict, openscad, run
from partspec.engines import openscad as openscad_engine

pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"

needs_openscad = pytest.mark.skipif(
    openscad_engine.find_executable() is None, reason="openscad binary not installed"
)

# 30x20x10 block with a 6x6 square through-hole.
BLOCK = FIXTURES / "block_with_hole.scad"
PLATE = FIXTURES / "parametric_plate.scad"
TWO = FIXTURES / "two_bodies.scad"


def _status(report, check_id: str) -> Status:
    return next(c.status for c in report.checks if c.id == check_id)


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


@needs_openscad
def test_a_satisfied_contract_passes(tmp_path: Path):
    p = Part("block", openscad(BLOCK))
    p.envelope(max=(30, 20, 10))
    p.watertight()
    p.solid_count(1)
    p.genus(1)

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.PASS
    assert report.exit_code == 0
    assert _status(report, "builds") is Status.PASS


@needs_openscad
def test_a_violated_geometry_check_fails(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).envelope(max=(5, 5, 5))
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert report.exit_code == 1


@needs_openscad
def test_measurements_are_recorded_on_pass(tmp_path: Path):
    """What lets a future diff report drift on a check that still passes."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    envelope = next(c for c in report.checks if c.id == "envelope")
    assert envelope.status is Status.PASS
    assert envelope.measurement is not None
    assert envelope.measurement.value == pytest.approx((30.0, 20.0, 10.0))


@needs_openscad
def test_provenance_is_recorded(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.geometry["triangles"] > 0
    assert report.geometry["distinct_normals"] > 0
    assert report.engine["kind"] == "openscad"
    assert report.engine["backend"] == "mesh"


# --------------------------------------------------------------------------
# the guards
# --------------------------------------------------------------------------


@needs_openscad
def test_a_contract_that_asserts_nothing_is_empty_not_pass(tmp_path: Path):
    """Vacuous green. The implicit `builds` check must not satisfy the emptiness
    test — otherwise the tool defeats its own most important guard."""
    report = run(Part("vacuous", openscad(BLOCK)), out_dir=tmp_path)
    assert report.verdict is Verdict.EMPTY
    assert report.exit_code == 3
    assert _status(report, "builds") is Status.PASS, "builds itself still ran and passed"


@needs_openscad
def test_unsupported_does_not_read_as_green(tmp_path: Path):
    """genus is refused for multi-body parts; the part must not pass anyway."""
    p = Part("two", openscad(TWO))
    p.solid_count(2)
    p.genus(0)

    report = run(p, out_dir=tmp_path)
    assert _status(report, "solid_count") is Status.PASS
    assert _status(report, "genus") is Status.UNSUPPORTED
    assert report.verdict is Verdict.INCOMPLETE
    assert report.exit_code == 2, "not proven is not the same as fine"


# --------------------------------------------------------------------------
# provenance — the closure, not just the entry file
# --------------------------------------------------------------------------


def _closure_of(source) -> dict:
    from partspec.runner import _closure

    result = _closure(source)
    assert result is not None
    return result


def test_a_transitive_edit_is_visible_where_source_digest_is_blind(tmp_path: Path):
    """The reason the closure exists.

    An OpenSCAD entry file is routinely a small fraction of its own build — the
    gridfinity bin in the dogfood corpus is one file of sixteen. Editing a helper
    three levels down changes the part and leaves `source_digest` identical, so
    two genuinely different builds compare as the same inputs.
    """
    (tmp_path / "helper.scad").write_text("W = 10;\n")
    (tmp_path / "mid.scad").write_text("include <helper.scad>\n")
    entry = tmp_path / "a.scad"
    entry.write_text("include <mid.scad>\ncube([W, W, W]);\n")

    source = openscad(entry)
    before = _closure_of(source)
    entry_digest_before = entry.read_bytes()

    (tmp_path / "helper.scad").write_text("W = 20;\n")  # a different part
    after = _closure_of(source)

    assert entry.read_bytes() == entry_digest_before, "premise: the entry file is untouched"
    assert before["files"] == after["files"] == 3
    assert before["digest"] != after["digest"], "the closure must see it"


def test_the_closure_digest_does_not_depend_on_where_the_tree_lives(tmp_path: Path):
    """Digested over sorted content hashes rather than paths, because the whole
    point of a comparator is comparing a CI run against a laptop run, and a
    path-sensitive digest would differ on every one of them."""
    import shutil

    a = tmp_path / "one"
    a.mkdir()
    (a / "lib.scad").write_text("X = 1;\n")
    (a / "top.scad").write_text("include <lib.scad>\n")
    b = tmp_path / "two"
    shutil.copytree(a, b)

    assert (
        _closure_of(openscad(a / "top.scad"))["digest"]
        == (_closure_of(openscad(b / "top.scad"))["digest"])
    )


def test_a_partial_closure_says_so_in_the_report(tmp_path: Path):
    entry = tmp_path / "a.scad"
    entry.write_text("include <gone.scad>\n")
    closure = _closure_of(openscad(entry))
    assert closure["partial"] is True
    assert closure["unresolved"] == ["gone.scad"]


def test_a_complete_closure_carries_no_partial_flag(tmp_path: Path):
    entry = tmp_path / "a.scad"
    entry.write_text("cube([1,2,3]);\n")
    assert "partial" not in _closure_of(openscad(entry))


def test_python_engines_get_no_closure(tmp_path: Path):
    """Claiming nothing beats claiming wrongly. Python resolves imports through
    the interpreter; installed packages are already covered by
    `environment.packages`, and local helper modules are a recorded gap."""
    from partspec import build123d
    from partspec.runner import _closure

    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")
    assert _closure(build123d(model)) is None


@needs_openscad
def test_a_tier_that_cannot_answer_says_which_one_can(tmp_path: Path):
    """The capability-refusal path, which no contract could reach until
    `topology` existed: every other v0 check maps to a primitive both backends
    declare, so `requires` was never populated in a real report.

    A triangle mesh has no modelled faces, so this is refused *before* dispatch
    — the mesh backend does not declare the capability — rather than answered
    with a triangle count, which is the PartCAD failure (D12).
    """
    p = Part("block", openscad(BLOCK))
    p.topology(faces=6)

    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert check.measurement is None, "a refusal must not carry a number"
    assert report.verdict is Verdict.INCOMPLETE
    assert report.exit_code == 2


@needs_openscad
def test_a_failing_parameter_check_short_circuits_the_engine(tmp_path: Path):
    """Building geometry from inputs already rejected wastes time and produces a
    shape describing something the contract has ruled out."""
    p = Part("plate", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.requires("plate_x < plate_y")  # false
    p.envelope(max=(40, 30, 4))
    p.watertight()

    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert _status(report, "plate_x_plate_y") is Status.FAIL
    assert _status(report, "builds") is Status.SKIPPED
    assert _status(report, "envelope") is Status.SKIPPED
    assert not (tmp_path / "parametric_plate.stl").exists(), "the engine must not have run"


@needs_openscad
def test_short_circuited_checks_are_present_not_omitted(tmp_path: Path):
    """An absent check is indistinguishable from one never declared."""
    p = Part("plate", openscad(PLATE, plate_x=1.0))
    p.requires("plate_x > 100")
    p.watertight()
    p.solid_count(1)

    report = run(p, out_dir=tmp_path)
    assert {c.id for c in report.checks} == {"plate_x_100", "builds", "watertight", "solid_count"}
    assert report.counts()["total"] == 4


@needs_openscad
def test_a_failing_parameter_check_names_the_blocker(tmp_path: Path):
    p = Part("plate", openscad(PLATE, plate_x=1.0)).requires("plate_x > 100").watertight()
    report = run(p, out_dir=tmp_path)
    detail = next(c.detail for c in report.checks if c.id == "watertight")
    assert "plate_x_100" in (detail or "")


@needs_openscad
def test_operands_are_recorded_on_a_failed_predicate(tmp_path: Path):
    p = Part("plate", openscad(PLATE, plate_x=40.0, plate_y=30.0)).requires("plate_x < plate_y")
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "requires")
    assert check.operands == {"plate_x": 40.0, "plate_y": 30.0}
    assert check.measurement is None and check.limit is None, "predicates are not measurements"


# --------------------------------------------------------------------------
# build failure
# --------------------------------------------------------------------------


@needs_openscad
def test_a_build_failure_fails_builds_and_skips_the_rest(tmp_path: Path):
    p = Part("missing", openscad(tmp_path / "nope.scad")).watertight()
    report = run(p, out_dir=tmp_path)
    assert _status(report, "builds") is Status.FAIL
    assert _status(report, "watertight") is Status.SKIPPED
    assert report.verdict is Verdict.FAIL


def test_an_unknown_engine_errors_rather_than_pretending(tmp_path: Path):
    """A backend that pretended to measure would defeat the point of the tool."""
    from partspec.contract import Source

    p = Part("later", Source(engine="freecad", path=Path("model.py"))).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert report.exit_code == 4
    assert "unknown engine" in (report.error or "")
    assert all(c.status is Status.SKIPPED for c in report.checks)


def test_a_contract_error_skips_every_check(tmp_path: Path):
    """A malformed question has no answer, so nothing is reported as failed."""
    p = Part("bad", openscad(BLOCK)).requires("undeclared_name > 0")
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert all(c.status is Status.SKIPPED for c in report.checks)
    assert "undeclared" in (report.error or "")


# --------------------------------------------------------------------------
# the artifact
# --------------------------------------------------------------------------


@needs_openscad
def test_the_report_written_to_disk_is_schema_shaped(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).watertight()
    report = run(p, out_dir=tmp_path, argv=["check", "x"])
    path = report.write(tmp_path)

    doc = json.loads(path.read_text())
    assert doc["schema_version"] == 1
    assert doc["counts"]["total"] == len(doc["checks"])
    assert sum(v for k, v in doc["counts"].items() if k != "total") == doc["counts"]["total"]
    assert doc["part"]["source_digest"].startswith("sha256:")
    assert doc["engine"]["backend"] == "mesh"


@needs_openscad
def test_digests_change_with_content(tmp_path: Path):
    scad = tmp_path / "m.scad"
    scad.write_text("cube(10);\n")
    first = run(Part("m", openscad(scad)).watertight(), out_dir=tmp_path).source_digest

    scad.write_text("cube(11);\n")
    second = run(Part("m", openscad(scad)).watertight(), out_dir=tmp_path).source_digest

    assert first != second
