"""min_wall (#140): a guaranteed interval, executed against known walls.

Every fixture's true minimum wall is hand-computable; the research record
behind the method (four candidates executed, three refused) is in the issue
and SPEC-contract 4.11. The straddle fixture is the first genuine exercise of
the approximate machinery — POST-V0 section 4's outstanding obligation.
"""

from __future__ import annotations

import json

import pytest

bd = pytest.importorskip("build123d", reason="occt extra not installed")

from partspec.backend import Unsupported  # noqa: E402
from partspec.backends.occt import OcctBackend  # noqa: E402
from partspec.cli import main  # noqa: E402
from partspec.contract import ContractError, Part  # noqa: E402
from partspec.runner import _run_geometry_check  # noqa: E402
from partspec.status import Status  # noqa: E402


def _shell():
    return bd.Box(30, 20, 10) - bd.Box(26, 16, 6)


def _raw(shape):
    return OcctBackend()._min_wall_raw(shape)


# ---------------------------------------------------------------------------
# exact walls, hand-computed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "builder", "truth"),
    [
        ("uniform shell", _shell, 2.0),
        ("thin patch", lambda: _shell() - bd.Pos(0, 0, 4.4) * bd.Box(6, 6, 1.2), 0.8),
        ("tube", lambda: bd.Cylinder(10, 20) - bd.Cylinder(8.5, 20), 1.5),
        ("sphere shell", lambda: bd.Sphere(10) - bd.Sphere(9), 1.0),
        ("hidden thin spot", lambda: bd.Box(30, 20, 10) - bd.Sphere(4.2), 0.8),
    ],
)
def test_the_lower_bound_lands_on_the_truth(name, builder, truth):
    raw = _raw(builder())
    assert isinstance(raw, dict) and "lo" in raw, name
    assert raw["lo"] == pytest.approx(truth, abs=1e-9), name


def test_the_gap_limits_the_bound_honestly():
    """The U-channel: walls 3.0, gap 1.0. PR #144's review (F2) proved that
    EXCLUDING gap-classified pairs can hide a real wall, so the gap pair is
    retained: lo is the gap distance (sound — any wall between two faces is
    at least their pair distance), the claim straddles honestly instead of
    passing on a falsely tight 3.0, and the gap limitation is flagged."""
    channel = bd.Box(7, 20, 10) - bd.Pos(0, 0, 1.5) * bd.Box(1, 20, 7)
    raw = _raw(channel)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(1.0, abs=1e-9), "the gap bounds from below"
    assert raw["gap_limited"] is True
    assert raw["hi"] >= 3.0 - 1e-9, "the interval still contains the true wall"

    result = _run_geometry_check(_spec(min=2.0), OcctBackend(), channel, "subject")
    assert result.status is Status.APPROXIMATE
    assert result.detail is not None and "gap-like pair" in result.detail
    conclusive = _run_geometry_check(_spec(min=0.5), OcctBackend(), channel, "subject")
    assert conclusive.status is Status.PASS


def test_closed_faces_answer_by_self_span():
    """A rod and a bead have no face PAIRS — the analytic self-span (the
    diameter) is the wall, achieved and therefore exact."""
    rod = _raw(bd.Cylinder(0.5, 20))
    assert isinstance(rod, dict)
    assert rod["lo"] == rod["hi"] == pytest.approx(1.0)
    assert "self-span" in rod["witness"]

    bead = _raw(bd.Sphere(0.6))
    assert isinstance(bead, dict)
    assert bead["lo"] == bead["hi"] == pytest.approx(1.2)


def test_a_bore_self_span_is_a_void_not_a_wall():
    """The tube's inner cylinder face is closed too — its self-span (the
    bore diameter, 17) must be excluded by the axis-in-void test, or every
    tube would report its hole as its wall."""
    raw = _raw(bd.Cylinder(10, 20) - bd.Cylinder(8.5, 20))
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(1.5, abs=1e-9), "1.5, not 17.0 and not 20.0"


def test_the_wedge_is_a_feature_and_its_truncation_is_a_wall():
    """The structural wedge policy: faces sharing an edge are never a wall,
    so a 5.71-degree taper does not fail as a sliver — but the moment the
    tip is truncated, the faces stop sharing the edge and the 0.05 sliver
    is measured exactly."""
    tri = bd.make_face(bd.Polyline((0, 0), (40, 0), (40, 4), close=True))
    wedge = bd.extrude(tri, 10)
    raw = _raw(wedge)
    assert isinstance(raw, dict)
    assert raw["lo"] > 3.0, "the taper's thinness is the edge feature, not a wall"

    cut = bd.make_face(bd.Polyline((0, 0), (40, 0), (40, 4), (0.5, 0.05), (0, 0.05), close=True))
    truncated = bd.extrude(cut, 10)
    raw = _raw(truncated)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(0.05, abs=1e-9)


def test_an_eccentric_wall_is_bounded_not_guessed():
    """The bore offset makes the wall vary 1.1..1.9; lo must land on the
    true minimum exactly, and the interval must contain it."""
    raw = _raw(bd.Cylinder(10, 20) - bd.Pos(0.4, 0, 0) * bd.Cylinder(8.5, 20))
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(1.1, abs=1e-9)
    assert raw["hi"] >= raw["lo"]


# ---------------------------------------------------------------------------
# the approximate machinery, finally exercised (POST-V0 section 4's debt)
# ---------------------------------------------------------------------------


def _spec(**kwargs):
    from partspec import build123d

    part = Part("subject", build123d("m.py"))
    part.min_wall(**kwargs)
    return part.checks[0]


def _tilted_pocket():
    return _shell() - bd.Pos(0, 0, 5.6) * bd.Rot(8, 0, 0) * bd.Box(6, 6, 3)


def test_a_straddling_limit_adjudicates_approximate():
    """The first check whose interval genuinely straddles a limit: the
    tilted pocket's guaranteed [lo, hi] brackets the truth, a limit inside
    it must adjudicate APPROXIMATE — the tool does not know and will not
    guess — and limits clear of the interval stay conclusive."""
    shape = _tilted_pocket()
    raw = _raw(shape)
    assert isinstance(raw, dict)
    assert raw["hi"] - raw["lo"] > 0.01, "the fixture must have a real interval"
    inside_limit = (raw["lo"] + raw["hi"]) / 2

    backend = OcctBackend()
    result = _run_geometry_check(_spec(min=inside_limit), backend, shape, "subject")
    assert result.status is Status.APPROXIMATE
    assert result.detail is not None and "will not guess" in result.detail
    assert result.measurement is not None and result.measurement.exact is False
    assert result.measurement.bounds == (raw["lo"], raw["hi"])

    conclusive_pass = _run_geometry_check(_spec(min=raw["lo"] / 2), backend, shape, "subject")
    assert conclusive_pass.status is Status.PASS
    conclusive_fail = _run_geometry_check(_spec(min=raw["hi"] * 2), backend, shape, "subject")
    assert conclusive_fail.status is Status.FAIL


def test_approximate_surfaces_in_the_verdict(tmp_path):
    """Exit 2: a straddling wall claim leaves the run INCOMPLETE — unproven,
    not failing — through the whole CLI."""
    (tmp_path / "m.py").write_text(
        "import build123d as bd\n\n\ndef make_part():\n"
        "    shell = bd.Box(30, 20, 10) - bd.Box(26, 16, 6)\n"
        "    return shell - bd.Pos(0, 0, 5.6) * bd.Rot(8, 0, 0) * bd.Box(6, 6, 3)\n"
    )
    raw = _raw(_tilted_pocket())
    assert isinstance(raw, dict)
    limit = (raw["lo"] + raw["hi"]) / 2
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        f"    p.min_wall(min={limit})\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 2
    check = next(
        c
        for c in json.loads((out / "report.json").read_text())["checks"]
        if c["kind"] == "min_wall"
    )
    assert check["status"] == "approximate"
    assert check["measurement"]["exactness"] == "approximate"
    assert check["measurement"]["bounds"] is not None


# ---------------------------------------------------------------------------
# PR #144's falsified certificates, as regressions
# ---------------------------------------------------------------------------


def test_the_cross_drilled_rod_reads_its_diameter():
    """PR #144 review, F1: the single-point axis probe landed inside the
    cross-hole and discarded the rod's 4 mm diametric wall — the tool
    certified 19 mm on a 4 mm part, exact, and min_wall(min=10) passed. The
    exact segment-material certificate closes it: drilling a hole must
    never RAISE the reported wall."""
    rod = bd.Cylinder(2, 40) - bd.Rot(90, 0, 0) * bd.Cylinder(1, 10)
    raw = _raw(rod)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(4.0, abs=1e-9)
    assert "self-span" in raw["witness"]
    result = _run_geometry_check(_spec(min=10.0), OcctBackend(), rod, "subject")
    assert result.status is Status.FAIL, "the reviewer's false pass, dead"


def test_the_spiral_wall_cannot_false_pass():
    """PR #144 review, F2: a spline spiral whose inner/outer pair minimum
    crosses the 2 mm air gap — excluding that pair as a gap took its real
    3 mm wall with it, and min_wall(min=10) passed end to end reading 20.0
    exact. With gap pairs retained, lo <= the gap < the wall < 10: the
    claim can no longer pass."""
    import math

    a0, b, t, n = 10.0, 5.0 / (2 * math.pi), 3.0, 200
    thetas = [3 * math.pi * i / n for i in range(n + 1)]
    inner = bd.Spline(
        *[((a0 + b * th) * math.cos(th), (a0 + b * th) * math.sin(th)) for th in thetas]
    )
    outer = bd.Spline(
        *[((a0 + t + b * th) * math.cos(th), (a0 + t + b * th) * math.sin(th)) for th in thetas]
    )
    e1 = bd.Line(inner @ 0, outer @ 0)
    e2 = bd.Line(inner @ 1, outer @ 1)
    profile = bd.make_face([inner, e2, outer.reversed(), e1.reversed()])
    spiral = bd.extrude(profile, 20)
    raw = _raw(spiral)
    assert isinstance(raw, dict)
    assert raw["lo"] <= 3.0 + 1e-6, "lo can never exceed the true wall"
    result = _run_geometry_check(_spec(min=10.0), OcctBackend(), spiral, "subject")
    assert result.status is not Status.PASS, "the reviewer's false pass, dead"


def test_a_tiny_bore_is_still_a_void():
    """The mutant-(c) killer the reviewer demanded: a thick tube with a tiny
    bore — the bore's 2 mm self-span must be excluded (certified void), or
    lo drops to 2 on a 9 mm wall and every thick claim false-alarms."""
    raw = _raw(bd.Cylinder(10, 20) - bd.Cylinder(1, 20))
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(9.0, abs=1e-9), "9.0, not the bore's 2.0"


def test_the_analytic_families_have_fixtures():
    """The mutant-(e) coverage the reviewer demanded: frustum, solid torus
    and torus shell all answer, and the solid cone's apex stays a feature
    (vacuous FAIL with the empty-set detail, never a near-zero sliver)."""
    backend = OcctBackend()
    donut = _raw(bd.Torus(10, 2))
    assert isinstance(donut, dict) and donut["lo"] == pytest.approx(4.0, abs=1e-9)
    shell = _raw(bd.Torus(10, 2) - bd.Torus(10, 1.4))
    assert isinstance(shell, dict) and shell["lo"] == pytest.approx(0.6, abs=1e-9)
    frustum = _raw(bd.Cone(8, 5, 6))
    assert isinstance(frustum, dict) and frustum["lo"] > 0

    cone = _run_geometry_check(_spec(min=1.0), backend, bd.Cone(8, 0, 6), "subject")
    assert cone.status is Status.FAIL
    assert cone.detail is not None and "no wall spans exist" in cone.detail, (
        "the apex skip makes the solid cone vacuous, never a near-zero sliver"
    )


def test_the_exactness_threshold_binds():
    """The mutant-(g) killer: a near-threshold interval must stay honest."""
    from partspec.backends.occt import _min_wall_measurement

    wide = _min_wall_measurement({"lo": 1.0, "hi": 1.0005, "witness": "x"})
    assert wide.exact is False and wide.bounds == (1.0, 1.0005)
    tight = _min_wall_measurement({"lo": 1.0, "hi": 1.0 + 1e-10, "witness": "x"})
    assert tight.exact is True


def test_a_witnessed_span_below_lo_refuses(monkeypatch):
    """PR #144 review, F3: the old floor-clamp DELETED witnessed crossings
    thinner than lo — counter-evidence silenced into an exact false
    certificate. A contradicting witness now refuses the whole check."""
    monkeypatch.setattr(
        OcctBackend,
        "_min_wall_witnessed_span",
        lambda self, a, faces, edge_sets, spans, witness, floor: floor / 2,
    )
    raw = _raw(bd.Box(30, 20, 10) - bd.Box(26, 16, 6))
    assert isinstance(raw, Unsupported)
    assert "contradicts itself" in raw.reason


def test_the_drilled_web_escape_is_documented_behavior():
    """The recorded escape (SPEC 4.11): material bounded by edge-SHARING
    faces — the web beside the cross-hole — is outside the measurand. This
    pin documents the boundary as executed fact: the rod reads its
    diametric 4.0, NOT the ~1 mm web, and the spec says why. If pair
    analysis ever grows web coverage, this pin moves with the spec."""
    rod = bd.Cylinder(2, 40) - bd.Rot(90, 0, 0) * bd.Cylinder(1, 10)
    raw = _raw(rod)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(4.0, abs=1e-9)


# ---------------------------------------------------------------------------
# issue #145: the certified chord, and the ledge the measurand cannot tighten
# ---------------------------------------------------------------------------


def test_a_frustum_is_exact_again_through_its_certified_chord():
    """#145 item 2: the narrow rim of a frustum is where its thinnest span
    lives, and a fixed 6x6 ray grid never samples it — the interval read
    [4, 6.88] on a part whose wall is exactly 4. The chord certificate
    reaches it: a diametric chord at the rim, certified material end to end,
    is an ACHIEVED span, so the upper end collapses onto the lower one.

    The consequence is a conclusive verdict where there was an honest shrug,
    and it moves toward FAIL, never toward PASS — a claim below lo passes on
    lo alone, so a tighter hi can only turn approximate into fail."""
    frustum = bd.Cone(8, 2, 20)
    raw = _raw(frustum)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(4.0, abs=1e-9)
    assert raw["hi"] == pytest.approx(4.0, abs=1e-9), "the rim chord caps the interval"

    result = _run_geometry_check(_spec(min=5.0), OcctBackend(), frustum, "subject")
    assert result.status is Status.FAIL, "5 mm is refuted by a certified 4 mm crossing"
    assert _run_geometry_check(_spec(min=3.0), OcctBackend(), frustum, "subject").status is (
        Status.PASS
    )


def test_a_short_frustum_no_longer_refuses_outright():
    """#145 item 2, the sibling the fixture hunt turned up: on a 45-degree
    frustum every inward normal exits through an ADJACENT cap, so the ray
    witness found nothing and the whole check refused ('no witnessed span
    could be measured') on an entirely ordinary part. The certified chord is
    the witness the rays could not be."""
    raw = _raw(bd.Cone(8, 2, 6))
    assert isinstance(raw, dict), "an ordinary frustum must not refuse"
    assert raw["lo"] == raw["hi"] == pytest.approx(4.0, abs=1e-9)


def test_the_chord_certificate_is_the_whole_chord_or_nothing():
    """The certificate's teeth: a chord crossing a bore is NOT material end
    to end and must not certify, or the achieved-span argument collapses into
    the point-probe fallacy PR #144 (F1) killed. Same rod, two chords: the
    one through the cross-hole declines, the one clear of it certifies."""
    from partspec.backends.occt import _chord_span

    rod = bd.Cylinder(2, 40) - bd.Rot(90, 0, 0) * bd.Cylinder(1, 10)
    through_the_hole = ((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    clear_of_the_hole = ((-2.0, 0.0, 12.0), (2.0, 0.0, 12.0))
    assert _chord_span(rod.wrapped, *through_the_hole) is None, "the void breaks the chord"
    assert _chord_span(rod.wrapped, *clear_of_the_hole) == pytest.approx(4.0, abs=1e-9)


def test_the_antipodal_maps_are_diametric():
    """The chord machinery rests on one fact per family — that the antipodal
    parameter map really does land on the far side — and the map differs for
    each: `(u+pi, v)` for cylinder and cone, `(u+pi, -v)` for sphere,
    `(u, v+pi)` for torus. Executed here rather than reasoned about, because
    a map that is merely close certifies a SHORTER chord while the value
    reported stays the face's analytic span — nothing downstream would
    notice, so this assertion IS the guard (PR #146 review, MINOR 1: the
    contradiction tripwire cannot catch it, since a certified span is by
    construction one of the values `lo` minimised over). The flatted bead is
    the fixture that makes the sphere's `-v` bite — a full sphere's
    mid-parameter is the equator, where v and -v coincide and a wrong map
    hides."""
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]

    from partspec.backends.occt import _diametric_chords

    flatted = bd.Sphere(6) - bd.Pos(0, 0, 10) * bd.Box(20, 20, 10)  # a flat at z=5
    families = [
        (bd.Cylinder(2, 40), 4.0),
        (bd.Sphere(6), 12.0),
        (flatted, 12.0),
        (bd.Torus(10, 2), 4.0),
        (bd.Cone(8, 2, 20), 4.0),
    ]
    for shape, span in families:
        seen = False  # noqa: SIM113
        for face in shape.faces():
            surf = BRepAdaptor_Surface(face.wrapped)
            if not (surf.IsUClosed() or surf.IsVClosed()):
                continue
            for p1, p2 in _diametric_chords(surf, surf.GetType()):
                assert math.dist(p1, p2) == pytest.approx(span, abs=1e-9)
                seen = True
        assert seen, "the fixture must actually have a closed analytic face"

    raw = _raw(flatted)
    assert isinstance(raw, dict)
    assert raw["lo"] == raw["hi"] == pytest.approx(12.0, abs=1e-9), "a machined flat stays exact"


def _closed_analytic_candidates(shape):
    """The (span, chords) candidates `_min_wall_raw` builds, for unit-level
    tests of the certificate itself."""
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]

    from partspec.backends.occt import _diametric_chords

    out = []
    for face in shape.faces():
        surf = BRepAdaptor_Surface(face.wrapped)
        if not (surf.IsUClosed() or surf.IsVClosed()):
            continue
        chords = _diametric_chords(surf, surf.GetType())
        out.append((math.dist(*chords[0]), chords))
    return out


def test_the_certificate_is_tested_where_the_ray_witness_cannot_mask_it():
    """Two properties of the certificate are invisible end to end, because
    for cylinders the ray witness independently reaches the same number and
    quietly supplies the answer: the search's ORDER, and its spread along the
    face. Both are asserted at the unit level instead, where nothing else can
    answer for them.

    Order: a ball on a shaft certifies both 12 and 4; fed largest-first, the
    search must still return the smaller, or the interval it just proved
    exact would open to [4, 12].

    Spread: the cross-drilled rod's mid-height chords cross the hole and
    cannot certify (`None` above), so a certificate sampled only at the
    middle would find nothing on the very geometry PR #144 (F1) was about.
    The offsets certify 4.0."""
    from partspec.backends.occt import _certified_self_span

    ball_on_shaft = bd.Sphere(6) + bd.Cylinder(2, 40)
    candidates = _closed_analytic_candidates(ball_on_shaft)
    assert len(candidates) >= 2, "the fixture must offer two certifiable spans"
    largest_first = sorted(candidates, key=lambda item: -item[0])
    assert _certified_self_span(ball_on_shaft.wrapped, largest_first, None) == pytest.approx(4.0)

    rod = bd.Cylinder(2, 40) - bd.Rot(90, 0, 0) * bd.Cylinder(1, 10)
    rod_candidates = [c for c in _closed_analytic_candidates(rod) if c[0] == pytest.approx(4.0)]
    assert rod_candidates, "the rod's own diametric span must be a candidate"
    mid_only = [(span, chords[:2]) for span, chords in rod_candidates]
    assert _certified_self_span(rod.wrapped, mid_only, None) is None, "the hole blocks the middle"
    assert _certified_self_span(rod.wrapped, rod_candidates, None) == pytest.approx(4.0, abs=1e-9)


def test_the_spread_along_a_face_is_pinned_for_every_family():
    """PR #146 review, MINOR 4/N5-N6: the docstring claims each family is
    sampled along the face 'so a chord blocked by a bore can be answered by
    one that is not', and only the cylinder's spread was pinned. Two
    fixtures make the claim executed fact for the other two.

    A bead with blind bores at both sampled azimuths of its equator: the
    mid-parameter chords are interrupted, the off-equator ones are not. A
    torus with shallow pockets in its outer surface: the radial tube
    diameter is interrupted, the axial one is not. In both, a sample taken
    only at the middle would find nothing on a part whose span is real."""
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]

    from partspec.backends.occt import _certified_self_span, _diametric_chords

    bead = bd.Sphere(6)
    for fraction in (0.3, 0.7):
        theta = 2 * math.pi * fraction
        bead -= (
            bd.Pos(5 * math.cos(theta), 5 * math.sin(theta), 0)
            * bd.Rot(0, 90, math.degrees(theta))
            * bd.Cylinder(0.5, 4)
        )
    donut = bd.Torus(10, 2)
    for fraction in (0.3, 0.7):
        theta = 2 * math.pi * fraction
        donut -= (
            bd.Pos(11.8 * math.cos(theta), 11.8 * math.sin(theta), 0)
            * bd.Rot(0, 90, math.degrees(theta))
            * bd.Cylinder(0.4, 1.2)
        )

    for shape, family, span in ((bead, "Sphere", 12.0), (donut, "Torus", 4.0)):
        surf = next(
            s
            for s in (BRepAdaptor_Surface(f.wrapped) for f in shape.faces())
            if str(s.GetType()).endswith(family)
        )
        chords = _diametric_chords(surf, surf.GetType())
        assert _certified_self_span(shape.wrapped, [(span, chords[:2])], None) is None, (
            f"the {family} fixture must block its mid-parameter chords"
        )
        assert _certified_self_span(shape.wrapped, [(span, chords)], None) == pytest.approx(span)


def test_a_certified_span_can_only_tighten_the_upper_end():
    """PR #146 review, MINOR 4/N3: the ceiling is load-bearing and was
    untested — a certified span must never RAISE `hi`. A rod with a 0.5 mm
    flange is the fixture: the ray witness reaches 0.5 across the flange
    while the smallest certifiable span is the rod's 4.0, so an unbounded
    search would report [0.5, 4.0] and turn a conclusive fail into a shrug.
    The ceiling also stops the work: nothing at or above it can help, and
    the list is sorted, so the search ends there rather than paying for
    every blocked chord (MINOR 3 measured 2.4x on such a part)."""
    from partspec.backends.occt import _certified_self_span

    flange = bd.Cylinder(2, 40) + bd.Cylinder(8, 0.5)
    raw = _raw(flange)
    assert isinstance(raw, dict)
    assert raw["lo"] == raw["hi"] == pytest.approx(0.5, abs=1e-9), "the flange, not the rod"

    candidates = _closed_analytic_candidates(flange)
    assert any(span == pytest.approx(4.0) for span, _ in candidates), "the rod's 4.0 is offered"
    assert _certified_self_span(flange.wrapped, candidates, 0.5) is None, "the ceiling binds"
    assert _certified_self_span(flange.wrapped, candidates, None) == pytest.approx(4.0)

    result = _run_geometry_check(_spec(min=0.6), OcctBackend(), flange, "subject")
    assert result.status is Status.FAIL, "0.6 is refuted by the 0.5 flange"


def test_a_trimmed_periodic_face_certifies_a_span_that_is_not_a_crossing():
    """PR #146 review, MAJOR: the certificate proves material along the
    chord, NOT that the chord runs between two points of the face. A 1 mm
    round on an edge leaves a fillet band that is a QUARTER tube — closed in
    u, trimmed to v in [0, pi/2] — so the antipodal parameter lands off the
    face, 1.85 mm inside the solid, and the chord certifies anyway.

    Pinned as declared behavior rather than fixed, because the bound is
    sound for a different reason than 'a crossing exists': the face's
    diametric span is a member of the declared measurand (SPEC 4.11) and
    every member is an upper bound on the measurand's minimum. The value is
    also the one the LOWER bound already minimised over, so refusing it here
    would leave the two ends ranging over different sets. What the review
    corrected is the claim, not the number."""
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface  # pyright: ignore[reportAttributeAccessIssue]
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeVertex,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.BRepExtrema import (
        BRepExtrema_DistShapeShape,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.gp import gp_Pnt  # pyright: ignore[reportAttributeAccessIssue]

    from partspec.backends.occt import _chord_span, _diametric_chords

    boss = bd.fillet(bd.Cylinder(10, 20).edges().filter_by(bd.GeomType.CIRCLE)[0], 1.0)
    band = next(
        face
        for face in boss.faces()
        if str(BRepAdaptor_Surface(face.wrapped).GetType()).endswith("Torus")
    )
    surf = BRepAdaptor_Surface(band.wrapped)
    assert surf.IsUClosed() and not surf.IsVClosed(), "a quarter tube, not a full one"

    p1, p2 = _diametric_chords(surf, surf.GetType())[0]
    assert math.dist(p1, p2) == pytest.approx(2.0, abs=1e-9), "2 * the fillet radius"
    assert _chord_span(boss.wrapped, p1, p2) is not None, "material end to end"
    off_face = BRepExtrema_DistShapeShape(
        BRepBuilderAPI_MakeVertex(gp_Pnt(*p2)).Vertex(), band.wrapped
    )
    assert off_face.Value() > 1.0, "and yet the far end is not on the face at all"

    raw = _raw(boss)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(2**0.5, abs=1e-9), "the documented fillet-flip escape"
    assert raw["hi"] == pytest.approx(2.0, abs=1e-9)


def test_the_fillet_flip_now_fails_conclusively():
    """PR #146 review, MINOR 5: an unrecorded verdict escalation, pinned so
    it stays deliberate. SPEC 4.11 already warned that filleting a knife
    edge flips it from feature to wall; before the chord witness a rounded
    boss reported [1.414, 20.0] and a min=3 claim could only shrug. The
    upper end now collapses to 2.0, so the same claim FAILS conclusively.
    Correct within the measurand — the 1.414 span is real — but a stronger
    verdict than the escape's wording implied, so 4.11 says so."""
    boss = bd.fillet(bd.Cylinder(10, 20).edges().filter_by(bd.GeomType.CIRCLE)[0], 1.0)
    result = _run_geometry_check(_spec(min=3.0), OcctBackend(), boss, "subject")
    assert result.status is Status.FAIL
    assert result.measurement is not None and result.measurement.bounds is not None
    assert result.measurement.bounds[0] == pytest.approx(2**0.5, abs=1e-9)
    # Exactly 2.0, not 2.0000000000000013 (PR #146 review, MINOR 6): the
    # certified value reported is the face's analytic span, not the chord's
    # measured length, and this is the number a report consumer reads.
    assert result.measurement.bounds[1] == 2.0


def test_the_certificate_declines_a_chord_that_is_nearly_material(monkeypatch):
    """PR #146 review, MINOR 4/N2: the 1e-7 comparison was unpinned — a
    tolerance of 10% changed nothing in the whole suite. A chord that is 95%
    material is not a certificate, and a bore that removes a twentieth of it
    must still stop it."""
    from partspec.backends.occt import _chord_span

    rod = bd.Cylinder(2, 40) - bd.Rot(90, 0, 0) * bd.Cylinder(0.1, 10)
    chord = ((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert _chord_span(rod.wrapped, *chord) is None, "0.2 mm of void is still void"
    assert _chord_span(bd.Cylinder(2, 40).wrapped, *chord) == pytest.approx(4.0, abs=1e-9)


def test_an_unanswerable_chord_is_never_a_certificate(monkeypatch):
    """PR #146 review, MINOR 4: issue #145's own item 3 held that a branch no
    fixture can reach must be forced at the seam rather than accepted as
    untestable — and the new function had two such branches. Both are forced
    here: a kernel that reports failure, and a kernel that raises."""
    import OCP.BRepAlgoAPI  # pyright: ignore[reportMissingImports]

    from partspec.backends.occt import _chord_span

    rod = bd.Cylinder(2, 40)
    chord = ((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert _chord_span(rod.wrapped, *chord) == pytest.approx(4.0, abs=1e-9)

    real_common = OCP.BRepAlgoAPI.BRepAlgoAPI_Common  # pyright: ignore[reportAttributeAccessIssue]

    class _NotDone:
        """Reports failure while still offering a perfectly good shape — so
        a check that ignored `IsDone()` would certify from it. A stub that
        merely lacked `Shape()` would be caught by the exception handler and
        prove nothing about the guard."""

        def __init__(self, *args):
            self._real = real_common(*args)

        def IsDone(self):
            return False

        def Shape(self):
            return self._real.Shape()

    monkeypatch.setattr(OCP.BRepAlgoAPI, "BRepAlgoAPI_Common", _NotDone)
    assert _chord_span(rod.wrapped, *chord) is None, "an unfinished boolean certifies nothing"

    def _explode(*args):
        raise RuntimeError("the kernel gave up")

    monkeypatch.setattr(OCP.BRepAlgoAPI, "BRepAlgoAPI_Common", _explode)
    assert _chord_span(rod.wrapped, *chord) is None, "nor does one that raises"


def test_an_unanswerable_certificate_keeps_the_span(monkeypatch):
    """#145 item 3: the kernel-failure fallback (`include=None -> True`) had
    no fixture — `BRepAlgoAPI_Common` failing on a segment is not
    constructible — so the mutant that flips it to False survived the suite.
    The seam is forced instead: an unanswerable certificate must KEEP the
    span, because keeping one can only lower lo (safe), while dropping one
    raised a cross-drilled rod's wall to 19 mm (PR #144, F1)."""
    from partspec.backends import occt

    monkeypatch.setattr(occt, "_segment_has_material", lambda *args: None)
    raw = _raw(bd.Cylinder(2, 40))
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(4.0, abs=1e-9), (
        "dropping an unanswerable span leaves the 40 mm cap pair as the bound"
    )


def test_a_stepped_ledge_bounds_from_the_ledge_and_says_so():
    """#145 item 1: a 1.5 mm ledge on a slab whose every wall is 2.0 reads
    lo = 1.5. That is not a bug in the bound — the ledge IS a 1.5 mm span
    between two non-adjacent faces through material, so the measurand
    contains it — it is the planar sibling of the counterbore ledge recorded
    in SPEC 4.11. The interval still brackets the truth and the claim
    adjudicates approximate rather than passing on a number the tool cannot
    prove. Pinned so the looseness stays visible and cannot drift into
    silence."""
    slab = bd.Box(30, 20, 2) + bd.Pos(0, 0, 2) * bd.Box(27, 20, 2)
    raw = _raw(slab)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(1.5, abs=1e-9), "the ledge width, not the 2.0 wall"
    assert raw["hi"] >= 2.0 - 1e-9, "the interval still contains the true wall"

    backend = OcctBackend()
    straddle = _run_geometry_check(_spec(min=2.0), backend, slab, "subject")
    assert straddle.status is Status.APPROXIMATE, "never a pass on the unproven 2.0"
    assert _run_geometry_check(_spec(min=1.0), backend, slab, "subject").status is Status.PASS


# ---------------------------------------------------------------------------
# refusals and the vacuous set
# ---------------------------------------------------------------------------


def test_a_corner_only_part_fails_vacuously():
    """A tetrahedron: every face pair shares an edge, so there are no walls
    — and 'every wall is thick enough' over zero walls is the vacuous green
    this tool refuses, mirroring fillet_radius's empty set."""
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_Sewing,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.TopoDS import TopoDS

    points = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)]
    triangles = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
    sew = BRepBuilderAPI_Sewing()
    for a, b, c in triangles:
        face = bd.make_face(bd.Polyline(points[a], points[b], points[c], close=True))
        sew.Add(face.wrapped)
    sew.Perform()
    tetra = bd.Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew.SewedShape())).Solid())
    result = _run_geometry_check(_spec(min=1.0), OcctBackend(), tetra, "subject")
    assert result.status is Status.FAIL
    assert result.detail is not None and "vacuous green" in result.detail


def test_a_closed_freeform_face_refuses_the_whole_check():
    """A closed surface of revolution outside the analytic families has no
    guaranteed self-span: the check refuses by name rather than sampling."""
    profile = bd.Polyline((6, 0, -5), (8, 0, 0), (6, 0, 5))
    revolved = bd.revolve(
        bd.make_face(
            bd.Polyline((6, 0, -5), (8, 0, 0), (6, 0, 5), (5, 0, 5), (5, 0, -5), close=True)
        ),
        bd.Axis.Z,
    )
    del profile
    raw = _raw(revolved)
    if isinstance(raw, Unsupported):
        assert "no analytic self-span" in raw.reason
    else:
        # The kernel may classify the revolved band as cone/cylinder pieces;
        # then the check answers normally and this fixture cannot probe the
        # branch — record which happened rather than pretending.
        assert "lo" in raw


def test_declaration_and_dimensional_membership():
    for bad in (0, -1, True, float("nan"), "2"):
        with pytest.raises(ContractError, match="min_wall min"):
            _spec(min=bad)
    from partspec.contract import DIMENSIONAL_KINDS

    assert "min_wall" in DIMENSIONAL_KINDS, "min= is a number an author chose"


def test_measure_lists_the_quantity_with_bounds_honesty(tmp_path):
    (tmp_path / "m.py").write_text(
        "import build123d as bd\n\n\ndef make_part():\n"
        "    return bd.Box(30, 20, 10) - bd.Box(26, 16, 6)\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(["measure", f"{tmp_path / 'spec.py'}:make"]) == 0
    doc = json.loads(buf.getvalue())
    entry = doc["measurements"]["min_wall"]
    assert entry["value"] == pytest.approx(2.0, abs=1e-9)
    assert entry["exactness"] == "exact"


def test_the_mesh_tier_refuses_with_the_tier_named(tmp_path):
    pytest.importorskip("trimesh", reason="mesh extra not installed")
    import shutil
    from pathlib import Path

    from support import OPENSCAD

    if OPENSCAD is None:
        pytest.skip("openscad binary not installed")
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copy(fixtures / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('block_with_hole.scad'))\n"
        "    p.min_wall(min=2.0)\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 2
    check = next(
        c
        for c in json.loads((out / "report.json").read_text())["checks"]
        if c["kind"] == "min_wall"
    )
    assert check["status"] == "unsupported"
    assert check["requires"] == "occt"
