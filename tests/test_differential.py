"""Engine parity: the same nominal part through OpenSCAD and build123d.

`SPEC-backend.md` §6 declares this a MUST — one contract, two engines, the
report's `checks[]` compared field-by-field excluding `engine` and `geometry`
— and until this file existed the only implementation was a throwaway in the
untracked dogfood workspace: a normative MUST with no test, the tracker's own
version of a vacuous green (#42). This is also the shape of test that catches
F13 — the same source building a different part on a different engine — as a
failure rather than a dogfood anecdote.

The subject is deliberately polyhedral (a plate with a rectangular through
slot), so both tiers measure it exactly and parity means equality to float
tolerance — not a tolerance wide enough to hide a defect. Engine parity
(OpenSCAD vs build123d), distinct from #11's mesh-vs-OCCT tier parity.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from support import OPENSCAD

from partspec import Part, build123d, openscad, region
from partspec.runner import run
from partspec.status import Status

needs_both_engines = pytest.mark.skipif(
    OPENSCAD is None
    or importlib.util.find_spec("trimesh") is None
    or importlib.util.find_spec("build123d") is None,
    reason="engine parity needs the mesh tier and build123d",
)

# 40 x 30 x 10 plate, 10 x 10 slot straight through: volume 11000, genus 1.
SCAD = "difference() { cube([40, 30, 10]); translate([15, 10, -1]) cube([10, 10, 12]); }\n"
PY = (
    "from build123d import Box, Location, Align\n\n\n"
    "def make_part():\n"
    "    plate = Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    slot = Location((15, 10, -1)) * Box(10, 10, 12, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    return plate - slot\n"
)


def _contracted(part: Part) -> Part:
    part.envelope(max=(40, 30, 10))
    part.watertight()
    part.solid_count(1)
    part.genus(1)
    part.volume(min=10999.99, max=11000.01)
    # Area catches what volume cannot: a reshaped slot (5 x 20, volume-
    # identical) changes wall area. A purely TRANSLATED slot is what the
    # keep_out below pins — the residual this file used to declare open.
    part.area(min=3999.99, max=4000.01)
    # Every coordinate is exactly float32-representable, so the mesh tier's
    # quantised booleans and the OCCT tier's doubles must agree to float
    # tolerance, not merely to a loose band.
    part.keep_out(region.box(min=(16, 11, 1), max=(24, 19, 9)), shell=3.0, id="slot_clear")
    part.keep_in(region.box(min=(2, 2, 2), max=(12, 8, 8)), shell=3.0, id="web_solid")
    return part


@needs_both_engines
def test_one_contract_measures_the_same_part_on_both_engines(tmp_path: Path):
    scad = tmp_path / "plate.scad"
    scad.write_text(SCAD)
    model = tmp_path / "plate.py"
    model.write_text(PY)

    mesh_report = run(_contracted(Part("diff", openscad(scad))), out_dir=tmp_path / "mesh")
    occt_report = run(_contracted(Part("diff", build123d(model))), out_dir=tmp_path / "occt")

    mesh_checks = [c.to_json() for c in mesh_report.checks]
    occt_checks = [c.to_json() for c in occt_report.checks]
    assert [c["id"] for c in mesh_checks] == [c["id"] for c in occt_checks]

    compared = 0
    for m, o in zip(mesh_checks, occt_checks, strict=True):
        assert m["status"] == o["status"] == Status.PASS.value, (m, o)
        mv, ov = m.pop("measurement"), o.pop("measurement")
        # detail is prose and may honestly differ between tiers; every other
        # field — kind, phase, limit, expr, operands — must agree exactly.
        m.pop("detail")
        o.pop("detail")
        assert m == o
        if mv is None or ov is None:
            assert mv == ov, (m, o)
            continue
        compared += 1
        assert mv.pop("unit") == ov.pop("unit")
        assert mv.pop("exactness") == ov.pop("exactness") == "exact"
        mval, oval = mv.pop("value"), ov.pop("value")
        assert mv == ov  # whatever remains (axes, bounds) must agree too
        if isinstance(mval, bool):
            assert mval == oval
        else:
            assert mval == pytest.approx(oval, abs=1e-6)
    # The comparison must be provably non-vacuous: an earlier draft read a
    # key that does not exist and every value comparison passed on
    # None == None. At least envelope, volume, solid_count and genus carry
    # measurements here.
    assert compared >= 4, f"only {compared} measured comparisons ran — parity was not tested"


@needs_both_engines
def test_cylinder_region_verdicts_agree_across_engines(tmp_path: Path):
    """Cylinder regions cannot join the strict field-by-field contract above:
    their polygon vertices are irrational, so the mesh tier's float32 booleans
    quantise them (~1e-7 relative) where the OCCT tier's doubles do not — and
    the modelled holes themselves differ by tier (inscribed 64-gon vs true
    cylinder). What must still agree exactly: the verdicts, and the earned
    zero of an empty region."""
    scad = tmp_path / "round.scad"
    scad.write_text(
        "difference() { cube([40, 30, 10]);"
        " translate([20, 15, -1]) cylinder(d=10, h=12, $fn=64); }\n"
    )
    model = tmp_path / "round.py"
    model.write_text(
        "from build123d import Box, Location, Align, Cylinder\n\n\n"
        "def make_part():\n"
        "    plate = Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
        "    hole = Location((20, 15, -1)) * Cylinder(\n"
        "        5, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "    return plate - hole\n"
    )

    def contracted(part: Part) -> Part:
        part.keep_out(region.cylinder(d=8.0, h=12.0, at=(20, 15, -1)), shell=3.0, id="bore")
        return part

    mesh = run(contracted(Part("r", openscad(scad))), out_dir=tmp_path / "mesh")
    occt = run(contracted(Part("r", build123d(model))), out_dir=tmp_path / "occt")
    for report in (mesh, occt):
        check = next(c for c in report.checks if c.id == "bore")
        assert check.status is Status.PASS, check.to_json()
        assert check.measurement is not None
        in_region, in_shell = check.measurement.value
        assert in_region == 0.0, "an empty region is an earned exact zero on every tier"
        assert in_shell > 0.0
