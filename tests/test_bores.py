"""End-to-end: `hole_diameter` and `bolt_circle`.

Split out of `test_runner.py` (#153). Grouped by subject — both are BREP bore
measurements on the OCCT tier — and NOT because they share machinery: they
share none. `hole_diameter` uses `_HOLE_MODEL`; `bolt_circle` uses
`_FLANGE_MODEL` and `_BoreWorld`, the canned-table stub that lets the circle
search be attacked at speed. An earlier version of this docstring claimed the
two shared `_BoreWorld` and `_FLANGE_MODEL`, which is false and was the file's
stated reason for existing (PR #158 review).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import needs_build123d, needs_scad_tier

from partspec import Part, Status, Verdict, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
BLOCK = FIXTURES / "block_with_hole.scad"


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


@needs_scad_tier
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


@needs_scad_tier
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
    tilted = {
        "d": 5.0,
        "direction": (0.0, 0.2588, 0.9659),
        "center": _ring(20.0)[3]["center"],
    }
    table = [*_ring(20.0)[:3], tilted]
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
