"""The runner: contract in, report out — and the internals that path relies on.

Most of this file is end-to-end. Those are the tests that would catch the tool
lying, and each asserts a claim from `SPEC-report.md` that the rest of the
design depends on.

The last section is not. `# runner internals, exercised directly` drives
`_run_geometry_check` with a stub, no engine and no report. It is here because
`runner.py` owns that helper.

This docstring says so because the #153 split added that section while the
first line still read "End-to-end" — the same false module docstring #158
retracted one file over, committed in the commit that retracted it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_build123d, needs_openscad, needs_scad_tier

from partspec import Part, Status, Verdict, openscad, run
from partspec.runner import _run_parameter_check

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


@needs_scad_tier
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


@needs_scad_tier
def test_a_violated_geometry_check_fails(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).envelope(max=(5, 5, 5))
    report = run(p, out_dir=tmp_path)
    assert report.verdict is Verdict.FAIL
    assert report.exit_code == 1


@needs_scad_tier
def test_measurements_are_recorded_on_pass(tmp_path: Path):
    """What lets a future diff report drift on a check that still passes."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    envelope = next(c for c in report.checks if c.id == "envelope")
    assert envelope.status is Status.PASS
    assert envelope.measurement is not None
    assert envelope.measurement.value == pytest.approx((30.0, 20.0, 10.0))


@needs_scad_tier
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


@needs_scad_tier
def test_a_contract_that_asserts_nothing_is_empty_not_pass(tmp_path: Path):
    """Vacuous green. The implicit `builds` check must not satisfy the emptiness
    test — otherwise the tool defeats its own most important guard."""
    report = run(Part("vacuous", openscad(BLOCK)), out_dir=tmp_path)
    assert report.verdict is Verdict.EMPTY
    assert report.exit_code == 3
    assert _status(report, "builds") is Status.PASS, "builds itself still ran and passed"


@needs_scad_tier
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


@pytest.mark.parametrize(
    ("body", "unseen"),
    [
        ("cube([1,2,3]);\n", []),
        ("include <gone.scad>\n", ["unresolved_includes"]),
        ('import("part.stl");\n', ["external_data_reads"]),
        ('import_stl("part.stl");\n', ["external_data_reads"]),
        ('surface("h.dat");\n', ["external_data_reads"]),
        (
            'include <gone.scad>\nsurface("h.dat");\n',
            ["external_data_reads", "unresolved_includes"],
        ),
    ],
)
def test_partial_is_exactly_whether_anything_was_left_unseen(
    tmp_path: Path, body: str, unseen: list[str]
):
    """`partial == bool(unseen)`, in every case the OpenSCAD tier can reach.

    `partial` used to be `bool(unresolved) or reads_external_data` and is now
    derived from the named gaps. The two must agree exactly, or #190's stage 3
    inherits a `diff` whose verdicts moved under it: `_closure_state` keys on
    this boolean and on nothing else in the closure.
    """
    entry = tmp_path / "a.scad"
    entry.write_text(body)
    closure = _closure_of(openscad(entry))
    assert closure["unseen"] == unseen
    assert closure.get("partial", False) is bool(unseen)


def test_the_openscad_tier_records_an_empty_imports_map_not_a_missing_one(tmp_path: Path):
    """This tier renders in a subprocess and imports nothing, which is a
    different statement from "not recorded" — the reading an absent `imports`
    carries in a report written before 0.7.5."""
    entry = tmp_path / "a.scad"
    entry.write_text("cube([1,2,3]);\n")
    assert _closure_of(openscad(entry))["imports"] == {}


def test_the_python_tier_is_partial_because_of_reads_no_python_can_see(tmp_path: Path):
    """The irreducible gap, and the reason `partial` cannot become false here:
    `OCP.StlAPI_Reader().Read()` read an STL off disk and produced zero `open`
    audit events. A closure on this tier is never complete, whatever it
    covers."""
    from partspec import build123d
    from partspec.runner import _python_closure

    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    pass\n")
    closure = _python_closure(build123d(model), None)
    assert "native_reads" in closure["unseen"]
    assert closure["partial"] is True
    assert closure["partial"] is bool(closure["unseen"])


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


@needs_build123d
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


@needs_scad_tier
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


@needs_scad_tier
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
    # `argv` is passed in and was never read back, so emitting `[]` instead
    # passed the suite — and the invocation block exists so a reader can tell
    # what produced the artifact.
    assert doc["invocation"]["argv"] == ["check", "x"]
    assert doc["counts"] == {
        "total": 2,
        "pass": 2,
        "fail": 0,
        "approximate": 0,
        "unsupported": 0,
        "skipped": 0,
    }, "the per-status tally, not just its sum"


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


@needs_build123d
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
# runner internals, exercised directly
#
# One test, filed here because `runner.py` owns the helper it drives. It runs
# no engine and touches no check: it hands `_run_geometry_check` a stub backend
# that DECLARES a primitive and then refuses it per-call, which no shipped
# backend does, so it is the only way `_refused`'s `requires=` field is
# exercised at all.
#
# It arrived here in #158 from `test_fillet_radius.py`, where the #153 split had
# filed it by the banner it sat under rather than by its subject. Two others
# arrived with it and have since gone on to `test_attribution.py` (#159), which
# is where the reader asking "which component failed?" now finds all six.
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# `p.empty()` — declaring that nothing is the intended result (#237, §4.12)
# --------------------------------------------------------------------------

_CLEARANCE_PROBE = (
    "intersection() {{ cube([10, 10, 10]); translate([0, 0, {z}]) cube([10, 10, 10]); }}\n"
)


@needs_openscad
def test_a_declared_empty_part_passes_and_never_reaches_a_measurement(tmp_path: Path):
    """The clearance probe's good answer, which had no way to be stated (#237).

    Two parts sharing no space render nothing. That is a real result and, for a
    probe, the passing one — but an empty build is a hard failure before any
    claim is evaluated, so `volume(max=0)` was SKIPPED rather than satisfied and
    the only gradeable outcome was the bad one.

    `builds` passes here: the engine ran, completed, and produced what the
    contract asked for. No `needs_scad_tier` on purpose — there is no mesh, so
    this never reaches the backend, which is the whole point.
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_CLEARANCE_PROBE.format(z=15))
    p = Part("clear", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS, [c.to_json() for c in report.checks]

    builds = next(c for c in report.checks if c.kind == "builds")
    assert builds.status is Status.PASS
    assert next(c for c in report.checks if c.id == "no-shared-space").status is Status.PASS


@needs_openscad
def test_an_empty_result_caused_by_an_unresolved_name_cannot_satisfy_it(tmp_path: Path):
    """The laundering guard, and the reason this check needed one (#237).

    An empty result means two different things and OpenSCAD 2021.01 reports them
    identically: a genuinely null intersection and a model whose geometry never
    existed both exit 1 with `Current top level object is empty.` and write no
    STL. Measured — the only difference is the WARNING lines above it.

    Without the guard this is the failure that matters: a misspelt module makes
    every clearance probe pass, and the greener the run the more broken the
    contract. The detail names the line, because "declared empty, and it was"
    would be true and useless.
    """
    scad = tmp_path / "typo.scad"
    scad.write_text("include <no_such_lib.scad>\nintersection() { lib_a(); lib_b(); }\n")
    p = Part("typo", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL, [c.to_json() for c in report.checks]

    result = next(c for c in report.checks if c.id == "no-shared-space")
    assert result.status is Status.FAIL
    assert result.detail is not None
    assert "could not resolve a name" in result.detail
    assert "lib_a" in result.detail or "no_such_lib" in result.detail


@needs_scad_tier
def test_a_part_that_builds_geometry_fails_its_declared_empty(tmp_path: Path):
    """The other direction: the parts DO share space, so the claim is disproven.

    This is the outcome a clearance probe is written to catch, and it must read
    as a failed claim rather than as a passing build with nothing said about it.
    """
    scad = tmp_path / "overlap.scad"
    scad.write_text(_CLEARANCE_PROBE.format(z=8))
    p = Part("overlap", openscad(scad))
    p.empty(id="no-shared-space")

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL, [c.to_json() for c in report.checks]

    result = next(c for c in report.checks if c.id == "no-shared-space")
    assert result.status is Status.FAIL
    assert result.detail == "declared empty, but the part built geometry"
    assert next(c for c in report.checks if c.kind == "builds").status is Status.PASS


@needs_openscad
def test_the_empty_VERDICT_and_the_empty_CHECK_are_not_the_same_thing(tmp_path: Path):
    """One word, two unrelated meanings, and they meet in one contract.

    The verdict `empty` means a contract that declared NOTHING — the vacuous-green
    guard above, exit 3. The check `empty` means a contract that declared nothing
    was the RESULT. A part carrying only `p.empty()` is the case where both could
    plausibly apply, and it must take the second: it asserted something, and the
    assertion held.

    Nothing in the code can confuse them — a `Verdict` member and a `kind` string
    live in different namespaces and are never compared — so this pins the
    distinction that a READER can conflate, and that `SPEC-contract.md` §4.2 now
    spells out because `p.empty()` made the collision reachable (#237).
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_CLEARANCE_PROBE.format(z=15))

    declared_nothing_is_the_result = Part("probe", openscad(scad))
    declared_nothing_is_the_result.empty()
    report = run(declared_nothing_is_the_result, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.PASS
    assert report.exit_code == 0

    # And the default id is the kind, which must not be mistaken for the verdict.
    assert [c.id for c in report.checks if c.kind == "empty"] == ["empty"]


@needs_openscad
def test_an_undeclared_empty_build_still_fails_exactly_as_before(tmp_path: Path):
    """`empty` is opt-in, and nothing else moves.

    For an ordinary part contract a null render IS a real fault, and #237 says
    so explicitly — it asks for a way to declare the intent, not for the default
    to soften. Pinned because the change touches the shared build-failure path,
    where a relaxation would be invisible until someone's broken part went green.
    """
    scad = tmp_path / "clear.scad"
    scad.write_text(_CLEARANCE_PROBE.format(z=15))
    p = Part("clear", openscad(scad))
    p.volume(max=0.001)

    report = run(p, out_dir=tmp_path / "out")
    assert report.verdict is Verdict.FAIL
    assert next(c for c in report.checks if c.kind == "builds").status is Status.FAIL
    assert next(c for c in report.checks if c.kind == "volume").status is Status.SKIPPED
