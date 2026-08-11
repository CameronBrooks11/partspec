"""The runner path for `keep_out` / `keep_in`, both tiers.

Split out of `test_runner.py` (#153), and named for its subject rather than its
method: it was `test_regions_e2e.py` until #159. Counting is what settled it —
of the 18 tests it held then, only 7 drove `run()`; the other 11 attack the
adjudication through `_BoxWorld`, the honest one-box stub, with no kernel at
all, so a reader filtering `_e2e` for end-to-end coverage was over-counting by
eleven. After the four attribution tests left for `test_attribution.py` the
ratio is starker still — **3 of the 14 here drive `run()`** — because the ones
that left were among the end-to-end ones. `test_region_checks` is true of every
test in this file and claims no tier.

The four per-component attribution tests that came along in the original split
have moved to `test_attribution.py`; they were #84's subject, not this one's.
`test_region_clauses_appear_as_components` stays, because a region clause
appearing as a component IS a claim about the region check.

`test_region.py` holds the region *data* (the canonical polyhedron both tiers
materialize); this file holds the runner path that consumes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_scad_tier

from partspec import Measurement, Part, Status, Unsupported, Verdict, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
PLATE = FIXTURES / "parametric_plate.scad"


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


@needs_scad_tier
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


@needs_scad_tier
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
