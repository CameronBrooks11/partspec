"""End-to-end: contract in, report out.

These are the tests that would catch the tool lying. Each asserts a claim from
`SPEC-report.md` that the rest of the design depends on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_openscad

from partspec import Measurement, Part, Status, Unsupported, Verdict, openscad, run
from partspec.runner import _run_parameter_check

pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"

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


def test_the_python_closure_is_not_computed_before_the_build(tmp_path: Path):
    """A Python model's imports are not knowable until it has run.

    So `_closure` — which runs while the report is being constructed — declines,
    and the runner fills the field in after a successful build instead.
    """
    from partspec import build123d
    from partspec.runner import _closure

    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")
    assert _closure(build123d(model)) is None


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)
def test_a_helper_beside_a_python_model_is_part_of_the_build(tmp_path: Path):
    """The same gap the OpenSCAD closure closed, on the other tier.

    `engines/pycad.py` puts the model's directory on `sys.path` specifically so
    a model can import helpers beside it, which makes those helpers build
    inputs by design. Editing one changed the part and left `source_digest`
    byte-identical, so two different builds compared as the same input.
    """
    (tmp_path / "dims.py").write_text("SIZE = 10.0\n")
    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box\nfrom dims import SIZE\n\n\n"
        "def make_part():\n    return Box(SIZE, SIZE, SIZE)\n"
    )

    from partspec import build123d

    def closure_of() -> dict:
        report = run(Part("m", build123d(model)).watertight(), out_dir=tmp_path)
        assert report.verdict is Verdict.PASS, report.error
        assert report.source_closure is not None
        return report.source_closure

    model_before = model.read_bytes()
    before = closure_of()

    (tmp_path / "dims.py").write_text("SIZE = 20.0\n")  # a different part
    after = closure_of()

    assert model.read_bytes() == model_before, "premise: the model file is untouched"
    assert before["files"] == after["files"] == 2
    assert before["digest"] != after["digest"], "the closure must see the helper"
    assert after["partial"] is True, "Python can import from anywhere; never claim completeness"
    assert after["scope"] == "model_directory"


def test_the_contract_is_not_folded_into_the_source_closure(tmp_path: Path):
    """`contract_digest` already covers it, and a source closure that moved
    whenever a *claim* changed would answer a different question than the one
    it is named for."""
    from partspec.runner import _python_closure

    contract = tmp_path / "spec.py"
    contract.write_text("# a claim\n")
    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")

    from partspec import build123d

    closure = _python_closure(build123d(model), contract)
    assert closure["files"] == 0, "nothing imported yet, and the contract does not count"


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
    assert _status(report, "plate_x_lt_plate_y") is Status.FAIL
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
    assert {c.id for c in report.checks} == {
        "plate_x_gt_100",
        "builds",
        "watertight",
        "solid_count",
    }
    assert report.counts()["total"] == 4


@needs_openscad
def test_a_failing_parameter_check_names_the_blocker(tmp_path: Path):
    p = Part("plate", openscad(PLATE, plate_x=1.0)).requires("plate_x > 100").watertight()
    report = run(p, out_dir=tmp_path)
    detail = next(c.detail for c in report.checks if c.id == "watertight")
    assert "plate_x_gt_100" in (detail or "")


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
def test_a_build_the_environment_prevented_is_not_a_failing_part(tmp_path: Path):
    """A missing source file is a fact about the machine, not about the design.

    This used to be `builds: fail` / `verdict: fail` / exit 1 -- the code that
    means "the part failed its contract". So a CI run on a box with no OpenSCAD
    installed reported every design as disproven, and exit 1 is the one an agent
    is most likely to answer by editing the model.
    """
    p = Part("missing", openscad(tmp_path / "nope.scad")).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.ERROR
    assert report.build_origin == "environment"
    assert _status(report, "builds") is Status.SKIPPED, "never reported as a failing check"
    assert _status(report, "watertight") is Status.SKIPPED


@needs_openscad
def test_a_design_that_does_not_compile_does_fail_builds(tmp_path: Path):
    """The other half of the split: this one *is* a statement about the part."""
    source = tmp_path / "bad.scad"
    source.write_text("this is not openscad;\n")
    p = Part("broken", openscad(source)).watertight()
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert report.build_origin == "model"
    assert _status(report, "builds") is Status.FAIL
    assert _status(report, "watertight") is Status.SKIPPED
    # `build_stderr` exists so the #37 hint filter can never lose the
    # diagnosis, and nothing asserted the value survived the hop into the
    # report — `report.build_stderr = None` passed the whole suite.
    assert report.build_stderr, "the unabridged diagnosis must reach the report"
    assert "bad.scad" in report.build_stderr


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


def test_the_part_block_carries_no_absolute_path(tmp_path: Path):
    """Two checkouts of the same tree at different locations must produce
    byte-identical `part` blocks.

    `part.source` was absolute after `_anchor` resolved it, so the committed
    example report leaked a developer home directory — undoing at the path layer
    exactly the machine-independence `source_closure` was built to have.
    """
    for location in ("checkout-a", "checkout-b"):
        root = tmp_path / location
        root.mkdir()
        (root / "box.scad").write_text("x = 10;\ncube([x, x, x]);\n")
        p = Part("paths", openscad(root / "box.scad", x=10.0)).watertight()
        report = run(p, out_dir=root / "out", contract_path=root / "spec.py")
        doc = report.to_json()["part"]
        assert doc["source"] == "box.scad"
        assert doc["contract"] == "spec.py"
        assert not any(str(v).startswith("/") or "\\" in str(v) for v in doc.values())


def test_a_parameter_unit_does_not_depend_on_the_python_literal(tmp_path: Path):
    """`40` and `40.0` are the same dimension. `_unit_for` used to give the first
    "count" and the second "mm", so editing a declared parameter between the two
    changed the recorded unit without changing the design — spurious drift in the
    field SPEC-report.md 7.2 exists to keep stable."""
    p = Part("units", openscad(tmp_path / "x.scad", a=40, b=40.0))
    p.param("a", min=1.0)
    p.param("b", min=1.0)
    results = [_run_parameter_check(s, p.source.params) for s in p.checks]
    assert {r.measurement.unit for r in results if r.measurement} == {"mm"}


def test_a_genuine_count_says_so(tmp_path: Path):
    p = Part("units", openscad(tmp_path / "x.scad", teeth=24))
    p.param("teeth", min=1, unit="count")
    result = _run_parameter_check(p.checks[0], p.source.params)
    assert result.measurement is not None
    assert result.measurement.unit == "count"


def test_the_report_records_the_invoked_method_and_param_mode(tmp_path: Path):
    # A method= build and a plain build were indistinguishable in the
    # artifact (#40); a reader of a SINGLE report must see which happened.
    (tmp_path / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    p = Part("m", openscad(tmp_path / "lib.scad", method="block", s=8.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] == "block"
    assert report.engine["param_mode"] == "call"
    assert report.engine["source_rendered"] == "derived"


def test_a_define_build_states_the_default_entry(tmp_path: Path):
    p = Part("d", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] is None
    assert report.engine["param_mode"] == "define"
    assert "source_rendered" not in report.engine


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)
def test_a_python_build_records_its_named_factory(tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n\n\n"
        "def wide():\n    return Box(20, 5, 2)\n"
    )
    from partspec import build123d

    p = Part("w", build123d(model, method="wide"))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["method"] == "wide"
    # param_mode is the OpenSCAD -D/call distinction; a Python factory call
    # has no such split and must not pretend to.
    assert "param_mode" not in report.engine

    q = Part("d", build123d(model))
    q.watertight()
    default = run(q, out_dir=tmp_path / "out2")
    assert default.engine["method"] is None


def test_an_unpinned_run_still_carries_the_render_backend_key(tmp_path: Path):
    # Null = "the engine's default, whichever this version chose" — the run a
    # reader cannot infer, which is why omission was backwards (#41).
    p = Part("u", openscad(PLATE, plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert "render_backend" in report.engine
    assert report.engine["render_backend"] is None


def test_a_pinned_render_backend_reaches_the_report(tmp_path: Path):
    # The engine block is written before the build, so the pinned string is
    # assertable even where --backend would fail the render itself.
    p = Part("pin", openscad(PLATE, backend="CGAL", plate_x=40.0, plate_y=30.0, plate_z=4.0))
    p.watertight()
    report = run(p, out_dir=tmp_path / "out")
    assert report.engine["render_backend"] == "CGAL"


# --------------------------------------------------------------------------
# keep_out / keep_in — the paired region-and-shell adjudication (#49)
# --------------------------------------------------------------------------

# The stub is an honest one-box world, not a canned answer sequence: parts and
# materialized regions are all axis-aligned boxes, and intersect_volume is real
# AABB overlap arithmetic. The adjudication logic is then tested against true
# geometry without an engine in sight.


class _BoxWorld:
    kind = "stub"

    def capabilities(self):
        return frozenset({"region_solid", "intersect_volume"})

    def region_solid(self, region):
        return (region.min, region.max)

    def intersect_volume(self, a, b) -> Measurement | Unsupported:
        from partspec.status import Measurement

        (alo, ahi), (blo, bhi) = a, b
        v = 1.0
        for lo1, hi1, lo2, hi2 in zip(alo, ahi, blo, bhi, strict=True):
            v *= max(0.0, min(hi1, hi2) - max(lo1, lo2))
        return Measurement(v, "mm3", exact=True)


def _region_result(part_box, kind, region, shell):
    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check

    spec = CheckSpec(id="r", kind=kind, phase="geometry", region=region, shell=shell)
    return _run_geometry_check(spec, _BoxWorld(), part_box)


def _box_part(lo, hi):
    return (lo, hi)


def test_keep_out_passes_when_the_region_is_empty_and_something_surrounds_it():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(12, 0, 0), max=(14, 10, 10)), shell=3.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    in_region, in_shell = result.measurement.value
    assert in_region == 0.0
    assert in_shell > 0.0  # the 9..10 slab of the part lies inside the shell
    assert result.limit is None
    assert result.region == {
        "shape": "box",
        "min": [12.0, 0.0, 0.0],
        "max": [14.0, 10.0, 10.0],
        "shell": 3.0,
    }


def test_keep_out_fails_on_intruding_material_and_names_the_volume():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(9, 0, 0), max=(11, 10, 10)), shell=2.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "100 mm3" in result.detail


def test_keep_out_fails_when_nothing_surrounds_the_region():
    """The mandatory-shell acceptance in #49: a part with the material deleted
    satisfies the naive claim perfectly, and must not pass."""
    from partspec.region import box

    part = _box_part((100, 100, 100), (110, 110, 110))
    result = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=2.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "absent part satisfies the bare emptiness" in result.detail


def test_keep_in_passes_when_solid_and_bounded():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_in", box(min=(7, 1, 1), max=(9, 9, 9)), shell=2.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    in_region, in_shell = result.measurement.value
    assert in_region == pytest.approx(2 * 8 * 8)
    # 500 mm3 of the part lies inside the outer box; the shell figure must be
    # the difference, not the raw outer intersection (a mutation that reported
    # in_outer here survived every other engine-free test).
    assert in_shell == pytest.approx(500.0 - 128.0)


def test_keep_in_fails_on_missing_material_and_names_the_deficit():
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_in", box(min=(8, 0, 0), max=(12, 10, 10)), shell=1.0)
    assert result.status is Status.FAIL
    assert result.detail is not None and "missing 200 mm3" in result.detail


def test_keep_in_fails_inside_an_unbounded_block():
    """The mirror vacuity: every keep-in is satisfied by a brick, so a shell
    that is entirely solid must fail the check."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (20, 20, 20))
    result = _region_result(part, "keep_in", box(min=(8, 8, 8), max=(12, 12, 12)), shell=2.0)
    assert result.status is Status.FAIL
    assert (
        result.detail is not None and "unbounded block satisfies the bare solidity" in result.detail
    )


def test_a_backend_refusal_propagates_to_the_region_check():
    from partspec.backend import Unsupported
    from partspec.region import box

    class _Refusing(_BoxWorld):
        def intersect_volume(self, a, b):
            return Unsupported("manifold3d rejected this mesh: NotManifold")

    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check

    spec = CheckSpec(
        id="r",
        kind="keep_out",
        phase="geometry",
        region=box(min=(0, 0, 0), max=(1, 1, 1)),
        shell=1.0,
    )
    result = _run_geometry_check(spec, _Refusing(), _box_part((0, 0, 0), (1, 1, 1)))
    assert result.status is Status.UNSUPPORTED
    assert result.detail is not None and "rejected" in result.detail


def test_a_skipped_region_check_still_records_its_claim(tmp_path: Path):
    """Short-circuited by a failing parameter check, the report must still say
    what the region check would have claimed — an absent claim is the
    vacuous-green failure wearing a different hat."""
    from partspec.region import box

    p = Part("s", openscad(PLATE, plate_x=-1.0, plate_y=30.0, plate_z=4.0))
    p.requires("plate_x > 0")
    p.keep_out(box(min=(0, 0, 0), max=(1, 1, 1)), shell=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "keep_out")
    assert check.status is Status.SKIPPED
    assert check.region == {
        "shape": "box",
        "min": [0.0, 0.0, 0.0],
        "max": [1.0, 1.0, 1.0],
        "shell": 1.0,
    }


@needs_openscad
def test_region_checks_run_end_to_end_on_the_mesh_tier(tmp_path: Path):
    """A clearance hole passes its keep_out and a boss its keep_in, and the
    written report carries the declared regions (#49 acceptance, mesh side)."""
    from partspec.region import box, cylinder

    scad = tmp_path / "bracket.scad"
    scad.write_text(
        "difference() {\n"
        "  union() {\n"
        "    cube([40, 30, 6]);\n"
        "    translate([27.5, 17.5, 6]) cube([5, 5, 4]);\n"
        "  }\n"
        "  translate([10, 10, -1]) cylinder(d=5.4, h=8, $fn=64);\n"
        "}\n"
    )
    p = Part("bracket", openscad(scad))
    p.keep_out(cylinder(d=5.0, h=8.0, at=(10, 10, -1)), shell=2.0, id="bolt_clearance")
    p.keep_in(box(min=(28.5, 18.5, 6.5), max=(31.5, 21.5, 9.5)), shell=1.0, id="boss_core")
    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS, [c.to_json() for c in report.checks]

    written = json.loads((report.write(tmp_path / "out")).read_text())
    bolt = next(c for c in written["checks"] if c["id"] == "bolt_clearance")
    assert bolt["region"]["shape"] == "cylinder"
    assert bolt["region"]["shell"] == 2.0
    assert bolt["limit"] is None
    assert bolt["measurement"]["axes"] == ["region", "shell"]
    assert bolt["measurement"]["value"][0] == 0.0


@needs_openscad
def test_an_oversize_hole_fails_its_keep_out_on_the_mesh_tier(tmp_path: Path):
    """The region is empty — the naive check would pass — but the clearance
    exceeds the shell everywhere, so nothing surrounds the declared hole."""
    from partspec.region import cylinder

    scad = tmp_path / "oversize.scad"
    scad.write_text(
        "difference() {\n"
        "  cube([40, 30, 6]);\n"
        "  translate([10, 10, -1]) cylinder(d=10, h=8, $fn=64);\n"
        "}\n"
    )
    p = Part("oversize", openscad(scad))
    p.keep_out(cylinder(d=5.0, h=8.0, at=(10, 10, -1)), shell=2.0, id="bolt_clearance")
    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL
    check = next(c for c in report.checks if c.id == "bolt_clearance")
    assert check.detail is not None and "shell" in check.detail


def test_both_region_clauses_can_fail_and_neither_message_contradicts_the_other():
    """A lone crumb inside the region of an otherwise-deleted part fails the
    core claim AND the shell claim. Each message must describe only what its
    own clause measured — the first cut of this code said 'the region is
    empty' in a detail string that also reported the intrusion volume."""
    from partspec.region import box

    part = _box_part((1, 1, 1), (2, 2, 2))
    result = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=1.0)
    assert result.status is Status.FAIL
    assert result.detail is not None
    assert "1 mm3 of material intrudes" in result.detail
    assert "no material lies within the 1 mm shell" in result.detail
    assert "region is empty" not in result.detail


def test_a_sub_epsilon_intrusion_is_tolerated_but_still_recorded():
    """epsilon(0.0) = 1e-6 mm3 — a ~10 um cube. Below it the verdict tolerates
    boolean dust; the measurement still shows the true figure, so the report
    never hides what the verdict forgave."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (10, 10, 10))
    result = _region_result(part, "keep_out", box(min=(10 - 1e-8, 0, 0), max=(12, 1, 1)), shell=2.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    assert result.measurement.value[0] == pytest.approx(1e-8, rel=0.01)


def test_keep_in_tolerance_scales_with_region_volume():
    """The relative epsilon term is load-bearing on large regions: a 10 L
    region missing 0.5 mm3 to float accumulation must pass, and would fail
    under a flat epsilon(0.0)."""
    from partspec.region import box

    part = _box_part((0, 0, 0), (200, 200, 250))
    result = _region_result(
        part, "keep_in", box(min=(0, 0, 0), max=(200, 200, 250 + 1.25e-5)), shell=2.0
    )
    assert result.status is Status.PASS
    assert result.measurement is not None
    assert result.measurement.value[0] == pytest.approx(200 * 200 * 250)


# --------------------------------------------------------------------------
# per-component attribution (#84)
# --------------------------------------------------------------------------


@needs_openscad
def test_a_failing_envelope_names_the_failing_axis(tmp_path: Path):
    """The block is 30x20x10. Only z breaks its bound, and the report must say
    so as data — an agent acting on 'envelope failed' has to bisect; one acting
    on 'z=10 outside max=5' edits once."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 5))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.FAIL
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.FAIL}
    assert check.detail == "z=10 outside max=5"


@needs_openscad
def test_components_are_recorded_on_pass_too(tmp_path: Path):
    """The 7.2 principle applied to attribution: drift analysis needs the
    passing shape as much as the failing one."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.PASS
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}
    assert check.detail is None


@needs_openscad
def test_a_scalar_check_carries_no_components(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).volume(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "volume")
    assert check.components is None
    assert "components" not in check.to_json()


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)
def test_an_unconstrained_topology_axis_is_absent_from_components(tmp_path: Path):
    """faces= alone claims nothing about edges or vertices, so those axes must
    not appear — a status on an unmade claim would be an answer to a question
    nobody asked."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text("from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n")
    p = Part("cube", build123d(model)).topology(faces=6)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.PASS
    assert check.components == {"faces": Status.PASS}


def test_region_clauses_appear_as_components():
    from partspec.region import box

    part = _box_part((1, 1, 1), (2, 2, 2))
    both = _region_result(part, "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=1.0)
    assert both.components == {"region": Status.FAIL, "shell": Status.FAIL}

    ok = _region_result(
        _box_part((0, 0, 0), (10, 10, 10)),
        "keep_out",
        box(min=(12, 0, 0), max=(14, 10, 10)),
        shell=3.0,
    )
    assert ok.components == {"region": Status.PASS, "shell": Status.PASS}

    # The asymmetric cases are what pin WHICH clause each entry reports: with
    # the two swapped, a report would blame the shell for the region's
    # intrusion — and the symmetric cases above cannot see it.
    intruded = _region_result(
        _box_part((4, 4, 4), (6, 6, 6)), "keep_out", box(min=(0, 0, 0), max=(5, 5, 5)), shell=2.0
    )
    assert intruded.components == {"region": Status.FAIL, "shell": Status.PASS}

    nothing_around = _region_result(
        _box_part((100, 100, 100), (110, 110, 110)),
        "keep_out",
        box(min=(0, 0, 0), max=(5, 5, 5)),
        shell=2.0,
    )
    assert nothing_around.components == {"region": Status.PASS, "shell": Status.FAIL}


def test_components_respect_the_same_epsilon_the_status_does():
    """The headline invariant, tested at the boundary where it can break: the
    binary-STL float32 round-trip that `epsilon()` exists for. A recompute of
    components with a naive comparison would fail x here while the folded
    status passes — a report contradicting its own attribution."""
    from partspec import Limit, adjudicate
    from partspec.runner import _components_of

    m = Measurement((120.30000305, 80.69999695, 40.09999847), "mm", axes=("x", "y", "z"))
    limit = Limit(max=(120.3, 80.7, 40.1))
    assert adjudicate(m, limit) is Status.PASS
    assert _components_of(m, limit) == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}


def test_an_approximate_axis_is_never_claimed_outside_its_bound():
    """'outside' is a conclusive claim. An axis whose error band straddles the
    limit is APPROXIMATE — the tool does not know — and the detail must stay
    silent about it rather than rounding indeterminate into violated. No
    backend emits vector bounds today; this pins the path before one does."""
    from partspec import Limit
    from partspec.runner import _components_of, _failing_axes

    m = Measurement(
        (5.0, 2.01),
        "mm",
        exact=False,
        bounds=((4.9, 5.1), (1.96, 2.06)),
        axes=("a", "b"),
    )
    limit = Limit(min=(6.0, 2.0))
    components = _components_of(m, limit)
    assert components == {"a": Status.FAIL, "b": Status.APPROXIMATE}
    assert components is not None
    assert _failing_axes(m, limit, components) == "a=5 outside min=6.0"


# --------------------------------------------------------------------------
# hole_diameter (#80)
# --------------------------------------------------------------------------

_HOLE_MODEL = (
    "from build123d import Align, Box, Cylinder, Location\n\n"
    "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
    "def make_part():\n"
    "    plate = Box(60, 40, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    return (\n"
    "        plate\n"
    "        - (Location((15, 20, -1)) * Cylinder(4, 12, align=A))\n"
    "        - (Location((30, 20, -1)) * Cylinder(4, 12, align=A))\n"
    "        + (Location((50, 20, 10)) * Cylinder(3, 5, align=A))\n"
    "    )\n"
)

needs_build123d = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)


@needs_build123d
def test_hole_diameter_passes_and_records_the_matched_diameters(tmp_path: Path):
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(_HOLE_MODEL)
    p = Part("plate", build123d(model)).hole_diameter(8.0, count=2)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.PASS
    assert check.measurement is not None
    assert check.measurement.value == (8.0, 8.0)
    assert check.hole == {"d": 8.0, "count": 2}
    assert report.verdict is Verdict.PASS


@needs_build123d
def test_a_boss_does_not_satisfy_a_hole_claim(tmp_path: Path):
    """The Ø6 boss is a full-wrap cylindrical surface of exactly the claimed
    diameter — facing out. Counting it would report a hole where there is a
    pin, which is the confident wrong answer in its purest form."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(_HOLE_MODEL)
    p = Part("plate", build123d(model)).hole_diameter(6.0, count=1)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.FAIL
    assert check.measurement is None, "nothing matched; nothing was measured for this claim"
    assert check.detail is not None
    assert "found 0 bore(s)" in check.detail
    assert "Ø8, Ø8" in check.detail, "the inventory shows what exists"


@needs_build123d
def test_a_count_mismatch_fails_with_the_inventory(tmp_path: Path):
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(_HOLE_MODEL)
    p = Part("plate", build123d(model)).hole_diameter(8.0, count=3)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.FAIL
    assert check.measurement is not None and check.measurement.value == (8.0, 8.0)
    assert check.detail is not None and "expected 3" in check.detail


@needs_build123d
def test_the_same_hole_contract_holds_on_cadquery(tmp_path: Path):
    """#80 acceptance names both Python engines: one OCCT implementation
    serves them (D3), and this is the check that proves it for bores."""
    pytest.importorskip("cadquery", reason="cadquery extra not installed")
    from partspec import cadquery as cq_source

    model = tmp_path / "m.py"
    model.write_text(
        "import cadquery as cq\n\n\n"
        "def make_part():\n"
        "    return (\n"
        "        cq.Workplane('XY').box(60, 40, 10, centered=False)\n"
        "        .faces('>Z').workplane()\n"
        "        .pushPoints([(15, 20), (30, 20)]).hole(8.0)\n"
        "    )\n"
    )
    p = Part("plate", cq_source(model)).hole_diameter(8.0, count=2)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.PASS, check.detail
    assert report.engine["adopted_via"] == "wrapped"


@needs_openscad
def test_hole_diameter_is_refused_on_the_mesh_tier_with_the_pointer(tmp_path: Path):
    """A 64-gon bore is a real 64-sided prism; answering Ø8 for it is the
    PartCAD failure. The refusal is structural — the capability is absent —
    and names the tier that would answer for an equivalent part."""
    p = Part("block", openscad(BLOCK)).hole_diameter(8.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert check.hole == {"d": 8.0, "count": 1}, "the refusal still states the claim"
    assert report.verdict is Verdict.INCOMPLETE
    assert report.exit_code == 2


@needs_build123d
def test_a_diameter_on_the_band_edge_is_inside_the_band(tmp_path: Path):
    """The band is closed: a drawing's Ø8 +0/-0.1 puts a shaft-fit bore at
    exactly 7.9, and 'within tolerance' includes its own limits. Also pins
    containment against a strict-inequality mutant nothing else catches."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Align, Box, Cylinder, Location\n\n\n"
        "def make_part():\n"
        "    plate = Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
        "    hole = Location((15, 15, -1)) * Cylinder(\n"
        "        3.95, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "    return plate - hole\n"
    )
    p = Part("plate", build123d(model)).hole_diameter(8.0, tol=0.1)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "hole_diameter")
    assert check.status is Status.PASS, check.detail
    assert check.measurement is not None and check.measurement.value == (7.9,)


# --------------------------------------------------------------------------
# bolt_circle (#81)
# --------------------------------------------------------------------------

_FLANGE_MODEL = (
    "import math\n"
    "from build123d import Box, Cylinder, Location, Align\n\n"
    "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
    "def make_part():\n"
    "    plate = Box(80, 80, 8, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    part = plate - (Location((40, 40, -1)) * Cylinder(10, 10, align=A))\n"
    "    for k in range(4):\n"
    "        x = 40 + 20 * math.cos(math.tau * k / 4 + 0.3)\n"
    "        y = 40 + 20 * math.sin(math.tau * k / 4 + 0.3)\n"
    "        part = part - (Location((x, y, -1)) * Cylinder(2.5, 10, align=A))\n"
    "    part = part - (Location((70, 8, -1)) * Cylinder(2.5, 10, align=A))\n"
    "    return part\n"
)


@needs_build123d
def test_the_drawing_callout_passes_as_one_check(tmp_path: Path):
    """4x Ø5 on Ø40 BCD, with a centre bore and an unrelated off-circle Ø5
    bore that subset semantics must ignore (#81 acceptance)."""
    from partspec import build123d

    model = tmp_path / "flange.py"
    model.write_text(_FLANGE_MODEL)
    p = Part("flange", build123d(model)).bolt_circle(5.0, count=4, bcd=40.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "bolt_circle")
    assert check.status is Status.PASS, check.detail
    assert check.measurement is not None
    assert check.measurement.value == pytest.approx(40.0, abs=1e-9)
    assert check.hole == {"d": 5.0, "count": 4, "bcd": 40.0}


@needs_build123d
def test_wrong_bcd_missing_hole_and_extra_on_circle_all_fail(tmp_path: Path):
    from partspec import build123d

    model = tmp_path / "flange.py"
    model.write_text(_FLANGE_MODEL)

    def result(**kw):
        p = Part("flange", build123d(model)).bolt_circle(5.0, **kw)
        return next(c for c in run(p, out_dir=tmp_path).checks if c.kind == "bolt_circle")

    wrong_bcd = result(count=4, bcd=38.0)
    assert wrong_bcd.status is Status.FAIL
    assert wrong_bcd.detail is not None and "5 candidate bore(s)" in wrong_bcd.detail

    # "5x on Ø40" when only 4 lie on it: a count, not a minimum.
    overcount = result(count=5, bcd=40.0)
    assert overcount.status is Status.FAIL
    assert overcount.detail is not None and "holds 4 of them" in overcount.detail

    # Wrong hole size on the right circle: position claims never blur into
    # diameter tolerance.
    wrong_d = Part("flange", build123d(model)).bolt_circle(6.0, count=4, bcd=40.0)
    check = next(c for c in run(wrong_d, out_dir=tmp_path).checks if c.kind == "bolt_circle")
    assert check.status is Status.FAIL
    assert check.detail is not None and "0 candidate bore(s)" in check.detail


@needs_build123d
def test_two_bolt_flanges_claim_centre_distance(tmp_path: Path):
    """count=2 collapses to centre separation == bcd — two of the four holes
    sit diametrically opposite, and a circle through two points is
    under-determined, so this is deliberately satisfiable here."""
    from partspec import build123d

    model = tmp_path / "flange.py"
    model.write_text(_FLANGE_MODEL)
    p = Part("flange", build123d(model)).bolt_circle(5.0, count=2, bcd=40.0)
    check = next(c for c in run(p, out_dir=tmp_path).checks if c.kind == "bolt_circle")
    assert check.status is Status.PASS
    assert check.measurement is not None
    assert check.measurement.value == pytest.approx(40.0)


@needs_openscad
def test_bolt_circle_is_refused_on_the_mesh_tier(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).bolt_circle(5.0, count=4, bcd=40.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "bolt_circle")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert report.verdict is Verdict.INCOMPLETE


# The stub lets the circle search be attacked at speed: canned bore tables,
# no kernel. The e2e tests above keep the real-geometry path honest.
class _BoreWorld:
    kind = "stub"

    def __init__(self, table):
        self.table = table

    def capabilities(self):
        return frozenset({"bore_table"})

    def bore_table(self, a):
        return self.table


def _bolt_result(table, *, d=5.0, count=4, bcd=40.0, tol=0.2):
    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check
    from partspec.status import Limit

    spec = CheckSpec(
        id="bc",
        kind="bolt_circle",
        phase="geometry",
        limit=Limit(min=bcd - tol, max=bcd + tol),
        hole={"d": d, "count": count, "bcd": bcd},
    )
    return _run_geometry_check(spec, _BoreWorld(table), None)


def _bore(x, y, d=5.0, direction=(0.0, 0.0, 1.0)):
    return {"d": d, "direction": direction, "center": (x, y, 0.0)}


def _ring(r, n=4, cx=40.0, cy=40.0, phase=0.0):
    import math

    return [
        _bore(
            cx + r * math.cos(math.tau * k / n + phase), cy + r * math.sin(math.tau * k / n + phase)
        )
        for k in range(n)
    ]


def test_holes_perturbed_within_tol_still_pass():
    """PR #89 review, blocker 1: a raw triple circumcentre shifts ~2x the
    perturbation and ejected a conforming fourth hole mid-band — the check
    failed a part every hole of which sat within tol of the true circle, and
    the detail asserted a circle that exists does not. The refit must find it."""
    import math

    table = [
        _bore(40 + r * math.cos(t), 40 + r * math.sin(t))
        for r, t in [(20.05, 0.3), (19.95, 1.87), (20.04, 3.44), (19.97, 5.01)]
    ]
    result = _bolt_result(table, tol=0.2)
    assert result.status is Status.PASS, result.detail
    assert result.measurement is not None
    assert result.measurement.value == pytest.approx(40.0, abs=0.1)


def test_count_is_exact_against_the_fitted_circle():
    """Three-of-four on the circle must fail: a count, not a minimum. Kills
    the >= mutant nothing else caught."""
    result = _bolt_result(_ring(20.0), count=3)
    assert result.status is Status.FAIL
    assert result.detail is not None and "holds 4 of them" in result.detail


def test_a_tilted_hole_does_not_complete_a_circle():
    """Axes must be parallel: three straight holes plus one tilted 15 degrees
    at the fourth position is not a bolt circle. Kills the direction-grouping
    mutant."""
    table = _ring(20.0)[:3] + [
        {"d": 5.0, "direction": (0.0, 0.2588, 0.9659), "center": _ring(20.0)[3]["center"]}
    ]
    assert _bolt_result(table).status is Status.FAIL


def test_the_search_cap_refuses_only_when_something_went_unexamined():
    """61 coaxial candidates alone: honest refusal, never a slow claimed-
    exhaustive answer. The same 61 plus a clean circle about another axis:
    the pass is found — a cap in one group must not preempt the others."""
    noise = [_bore(float(i), float((i * i) % 97)) for i in range(61)]
    refused = _bolt_result(noise)
    assert refused.status is Status.UNSUPPORTED
    assert refused.detail is not None and "refusing to search" in refused.detail

    other_axis = [
        {"d": 5.0, "direction": (1.0, 0.0, 0.0), "center": (0.0, b["center"][0], b["center"][1])}
        for b in _ring(20.0)
    ]
    assert _bolt_result(noise + other_axis).status is Status.PASS


def test_concentric_circles_answer_their_own_claims():
    table = _ring(20.0) + _ring(30.0, phase=0.4)
    assert _bolt_result(table, bcd=40.0, tol=0.2).status is Status.PASS
    assert _bolt_result(table, bcd=60.0, tol=0.2).status is Status.PASS
    assert _bolt_result(table, bcd=50.0, tol=0.2).status is Status.FAIL


def test_count_two_records_the_pair_closest_to_the_claim():
    """Four holes on Ø40: adjacent pairs sit at ~28.3, diagonal at 40. A wide
    tol admits both; the measurement must be the diagonal the drafter meant,
    not whichever pair iteration met first."""
    result = _bolt_result(_ring(20.0), count=2, bcd=40.0, tol=5.0)
    assert result.status is Status.PASS
    assert result.measurement is not None
    assert result.measurement.value == pytest.approx(40.0)


# --------------------------------------------------------------------------
# fillet_radius (#82)
# --------------------------------------------------------------------------

_FILLETED_MODEL = (
    "from build123d import Box, Align\n\n\n"
    "def make_part():\n"
    "    part = Box(30, 30, 20, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    top_edges = part.edges().group_by(lambda e: e.center().Z)[-1]\n"
    "    part = part.fillet(radius=3, edge_list=[top_edges[0]])\n"
    "    part = part.fillet(radius=1.5, edge_list=[e for e in part.edges().group_by(\n"
    "        lambda e: e.center().Z)[-1] if abs(e.center().Y) < 1e-6])\n"
    "    return part\n"
)


@needs_build123d
def test_fillet_radius_bounds_every_blend_and_names_the_breaker(tmp_path: Path):
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(_FILLETED_MODEL)

    ok = Part("f", build123d(model)).fillet_radius(min=1.0)
    report = run(ok, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "fillet_radius")
    assert check.status is Status.PASS, check.detail
    assert check.measurement is not None
    assert min(check.measurement.value) == pytest.approx(1.5)
    assert max(check.measurement.value) == pytest.approx(3.0)

    tight = Part("f", build123d(model)).fillet_radius(min=2.0)
    check = next(c for c in run(tight, out_dir=tmp_path).checks if c.kind == "fillet_radius")
    assert check.status is Status.FAIL
    assert check.components is not None
    assert check.components["blend_1"] is Status.FAIL, "ascending: the tightest blend is first"
    statuses = list(check.components.values())
    assert statuses[-1] is Status.PASS, "the r3 blend satisfies the bound"
    assert check.detail is not None and "=1.5 outside min=2.0" in check.detail


@needs_build123d
def test_a_bore_is_not_a_blend_and_zero_blends_never_pass_vacuously(tmp_path: Path):
    """A part whose only cylindrical surface is a full-wrap bore has no
    blends, and 'every blend >= r' over an empty set is the vacuous green
    this tool refuses (SPEC-contract.md 4.7)."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box, Cylinder, Location, Align\n\n\n"
        "def make_part():\n"
        "    plate = Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
        "    return plate - (Location((15, 15, -1)) * Cylinder(\n"
        "        4, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)))\n"
    )
    p = Part("plate", build123d(model)).fillet_radius(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "fillet_radius")
    assert check.status is Status.FAIL
    assert check.detail is not None and "vacuous green" in check.detail
    assert "not yet detected" in check.detail, "the message must not deny torus blends exist"
    assert report.verdict is Verdict.FAIL


@needs_build123d
def test_a_slot_end_counts_as_a_blend(tmp_path: Path):
    """Deliberate and documented: nothing at the surface level distinguishes a
    slot end from a fillet, and for the machinability claim they constrain
    the tool identically."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text(
        "from build123d import Box, Cylinder, Location, Align\n\n"
        "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
        "def make_part():\n"
        "    plate = Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
        "    slot = (Location((10, 15, -1)) * Cylinder(4, 12, align=A)\n"
        "            + Location((25, 15, -1)) * Cylinder(4, 12, align=A)\n"
        "            + Location((17.5, 15, -1)) * Box(15, 8, 12, align=A))\n"
        "    return plate - slot\n"
    )
    p = Part("slotted", build123d(model)).fillet_radius(min=5.0)
    check = next(c for c in run(p, out_dir=tmp_path).checks if c.kind == "fillet_radius")
    assert check.status is Status.FAIL
    assert check.measurement is not None
    assert 4.0 in check.measurement.value, "the slot-end radius is a blend candidate"


@needs_openscad
def test_fillet_radius_is_refused_on_the_mesh_tier(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).fillet_radius(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "fillet_radius")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert report.verdict is Verdict.INCOMPLETE


def test_a_declared_primitive_that_refuses_still_names_the_tier():
    """`_refused` exists to guarantee `requires=` reaches the report, and PR
    #152's review proved that guarantee was untested: deleting the field from
    the helper passed all 770 tests.

    The reason is structural. Every `requires`-bearing refusal in the shipped
    backends belongs to a primitive that tier does not declare, so the
    capability gate intercepts first and sets `requires` itself — the helper's
    path is only reached when a backend DECLARES a primitive and then refuses
    per-call, which no shipped backend does today. A stub does, so the field
    the helper exists for is finally exercised.
    """
    from partspec.backend import Unsupported
    from partspec.contract import Part, build123d
    from partspec.runner import _run_geometry_check

    class _RefusesWhatItDeclares:
        kind = "stub"

        def capabilities(self):
            return frozenset({"volume"})

        def volume(self, a):
            return Unsupported("this stub cannot integrate", requires="occt")

    part = Part("subject", build123d("m.py"))
    part.volume(min=1.0)
    result = _run_geometry_check(part.checks[0], _RefusesWhatItDeclares(), None)

    assert result.status is Status.UNSUPPORTED
    assert result.detail == "this stub cannot integrate"
    assert result.requires == "occt", "the tier that would answer must survive into the report"
