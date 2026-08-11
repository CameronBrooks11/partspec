"""End-to-end: `fillet_radius`.

Split out of `test_runner.py` (#153). Its own file rather than riding with the
bores: `_FILLETED_MODEL` is used by nothing else, and blend radii are a
different measurand from a bore table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import needs_build123d, needs_scad_tier

from partspec import Part, Status, Verdict, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
BLOCK = FIXTURES / "block_with_hole.scad"


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


@needs_scad_tier
def test_fillet_radius_is_refused_on_the_mesh_tier(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).fillet_radius(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "fillet_radius")
    assert check.status is Status.UNSUPPORTED
    assert check.requires == "occt"
    assert report.verdict is Verdict.INCOMPLETE
