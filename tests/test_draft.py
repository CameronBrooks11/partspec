"""draft_angle (#137): exact per-face draft against a two-half parting axis.

The closed-form claim is the load-bearing one — `exact=True` on cylinders and
cones is a statement that the extreme over the wrap interval was computed, not
sampled — so the math helper is tested directly against brute force, and every
CLI-level value is asserted against hand geometry.
"""

from __future__ import annotations

import math

import pytest
from support import check_of, needs_mesh, needs_openscad, py_target, report_of, scad_target

from partspec.contract import ContractError, Part
from partspec.status import Status

bd = pytest.importorskip("build123d", reason="occt extra not installed")

from partspec.backend import Unsupported  # noqa: E402
from partspec.backends.occt import OcctBackend, _min_draft_deg  # noqa: E402


def _check(shape, **kwargs):
    part = Part("subject", __import__("partspec").build123d("unused.py"))
    part.draft_angle(**kwargs)
    spec = part.checks[0]
    assert spec.direction is not None
    backend = OcctBackend()
    outcome = backend.draft_angle(shape, spec.direction)
    return spec, outcome


# ---------------------------------------------------------------------------
# the closed form, against brute force
# ---------------------------------------------------------------------------


def test_the_sinusoid_minimum_is_exact_against_brute_force():
    """min over u of asin(|A cos u + B sin u + C|): the closed form must match
    dense sampling to sub-sampling precision on every regime — zero crossing
    inside the interval, crest-only intervals, partial wraps, offsets that
    lift the sinusoid clear of zero."""
    cases = [
        (1.0, 0.0, 0.0, 0.0, math.tau),  # full wrap, crosses zero
        (0.7, -0.3, 0.0, 0.2, 1.1),  # partial wrap
        (0.5, 0.5, 0.3, -1.0, 1.0),  # offset, zero inside
        (0.2, 0.1, 0.9, 0.0, math.tau),  # offset lifts |c| clear of zero
        (0.0, 0.0, 0.4, 0.0, 1.0),  # degenerate radius: constant
        (0.9, 0.1, -0.85, 2.0, 2.4),  # narrow interval far from crest
    ]
    for a, b, c, u1, u2 in cases:
        exact = _min_draft_deg(a, b, c, u1, u2)
        brute = min(
            math.degrees(math.asin(min(1.0, abs(a * math.cos(u) + b * math.sin(u) + c))))
            for u in [u1 + (u2 - u1) * i / 20000 for i in range(20001)]
        )
        assert exact == pytest.approx(brute, abs=1e-3), (a, b, c, u1, u2)
        assert exact <= brute + 1e-9, "the closed form may never exceed the sampled min"


# ---------------------------------------------------------------------------
# per-face values, hand-checked geometry
# ---------------------------------------------------------------------------


def test_a_box_measures_zero_walls_and_ninety_tops():
    _spec, outcome = _check(bd.Box(20, 10, 6), min=2.0)
    assert not isinstance(outcome, Unsupported)
    values = list(outcome.value)
    assert values[:4] == pytest.approx([0.0, 0.0, 0.0, 0.0], abs=1e-9)
    assert values[4:] == pytest.approx([90.0, 90.0], abs=1e-9)
    assert outcome.exact is True
    assert outcome.axes is not None
    assert all(axis.startswith("face_") for axis in outcome.axes)


def test_a_cone_wall_reads_its_half_angle_exactly():
    """Cone(8, 5, 6): half-angle atan(3/6) — the closed form must land on it
    to float precision, because nothing was sampled."""
    _spec, outcome = _check(bd.Cone(8, 5, 6), min=2.0)
    assert not isinstance(outcome, Unsupported)
    expected = math.degrees(math.atan(0.5))
    assert min(outcome.value) == pytest.approx(expected, abs=1e-9)


def test_a_vertical_cylinder_wall_is_zero_draft():
    _spec, outcome = _check(bd.Cylinder(5, 8), min=1.0)
    assert not isinstance(outcome, Unsupported)
    assert min(outcome.value) == pytest.approx(0.0, abs=1e-9)


def test_a_horizontal_cylinder_contains_its_tangent():
    """Axis perpendicular to the pull: the wrap passes through the vertical
    tangent, so the face's minimum draft is exactly 0."""
    shape = bd.Rot(90, 0, 0) * bd.Cylinder(5, 8)
    _spec, outcome = _check(shape, min=1.0)
    assert not isinstance(outcome, Unsupported)
    assert min(outcome.value) == pytest.approx(0.0, abs=1e-9)


def test_a_tilted_plane_reads_its_exact_elevation():
    """A box rotated 10 degrees: its former walls read exactly 10 and its
    former tops exactly 80 — asin(|n.d|) to float precision."""
    _spec, outcome = _check(bd.Rot(0, 10, 0) * bd.Box(20, 10, 6), min=2.0)
    assert not isinstance(outcome, Unsupported)
    values = sorted(round(v, 6) for v in outcome.value)
    assert values == pytest.approx([0.0, 0.0, 10.0, 10.0, 80.0, 80.0], abs=1e-6)


def test_the_direction_is_honoured():
    """The same box, pulled along X: the roles of walls and tops swap."""
    _spec, outcome = _check(bd.Box(20, 10, 6), min=2.0, direction=(1, 0, 0))
    assert not isinstance(outcome, Unsupported)
    assert list(outcome.value)[:4] == pytest.approx([0, 0, 0, 0], abs=1e-9)
    assert list(outcome.value)[4:] == pytest.approx([90, 90], abs=1e-9)


def test_a_freeform_face_refuses_the_whole_check():
    """A sphere face has no closed-form wrap extreme here; the check refuses
    whole rather than passing the analytic subset — a verdict that skipped a
    face would be silence reading as success."""
    _spec, outcome = _check(bd.Sphere(10), min=2.0)
    assert isinstance(outcome, Unsupported)
    assert "sphere" in outcome.reason
    assert "face_0" in outcome.reason


# ---------------------------------------------------------------------------
# the declaration
# ---------------------------------------------------------------------------


def _part() -> Part:
    from partspec import build123d

    return Part("subject", build123d("m.py"))


def test_the_declaration_validates_its_inputs():
    with pytest.raises(ContractError, match="in \\(0, 90\\]"):
        _part().draft_angle(min=0)
    with pytest.raises(ContractError, match="in \\(0, 90\\]"):
        _part().draft_angle(min=91)
    with pytest.raises(ContractError, match="in \\(0, 90\\]"):
        _part().draft_angle(min=True)
    with pytest.raises(TypeError):
        _part().draft_angle(max=45)  # type: ignore[call-arg] — no max, by design (F1)
    with pytest.raises(ContractError, match="nonzero"):
        _part().draft_angle(min=2, direction=(0, 0, 0))
    with pytest.raises(ContractError, match="3-vector"):
        _part().draft_angle(min=2, direction="up")  # type: ignore[arg-type]


def test_the_direction_is_normalised_at_declaration():
    p = _part()
    p.draft_angle(min=2, direction=(0, 0, 5))
    assert p.checks[0].direction == pytest.approx((0.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# through the runner: adjudication, report shape, tier honesty
# ---------------------------------------------------------------------------


def test_the_report_names_the_failing_faces_and_the_claim(tmp_path):
    from partspec.cli import main

    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    target = py_target(
        tmp_path,
        claims="    p.draft_angle(min=2.0)\n",
    )
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 1
    check = check_of(out, "draft_angle")
    assert check["status"] == "fail"
    assert check["direction"] == [0.0, 0.0, 1.0], "the claim's axis is in the artifact"
    assert "face_" in check["detail"]
    failing = [axis for axis, status in check["components"].items() if status == "fail"]
    assert len(failing) == 4, "the four vertical walls, by name"


def test_a_drafted_part_passes(tmp_path):
    from partspec.cli import main

    (tmp_path / "m.py").write_text(
        "from build123d import Plane, Rectangle, extrude\n\n\ndef make_part():\n"
        "    return extrude(Plane.XY * Rectangle(20, 10), 6, taper=3)\n"
    )
    target = py_target(
        tmp_path,
        claims="    p.draft_angle(min=2.0)\n",
    )
    assert main(["check", target, "--quiet", "--out", str(tmp_path / "o")]) == 0


@needs_openscad
@needs_mesh
def test_the_mesh_tier_refuses_with_the_tier_named(tmp_path):
    from partspec.cli import main

    target = scad_target(
        tmp_path, source="block_with_hole.scad", claims="    p.draft_angle(min=2.0)\n"
    )
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 2
    check = check_of(out, "draft_angle")
    assert check["status"] == "unsupported"
    assert check["requires"] == "occt"


def test_adjudication_uses_the_component_machinery():
    spec, outcome = _check(bd.Cone(8, 5, 6), min=30.0)
    from partspec.status import adjudicate

    assert not isinstance(outcome, Unsupported)
    assert spec.limit is not None
    assert adjudicate(outcome, spec.limit) is Status.FAIL, "26.57 < 30 on the cone wall"


def test_a_generically_rotated_cylinder_wall_still_finds_its_tangent():
    """PR #141 review, F4: every earlier curved-face assertion sat at an
    axis-aligned orientation where the wrap seam coincides with the tangent,
    so swapping the wrap interval's ends survived the suite while reporting
    10.96 where the truth is 0. A generic rotation has no such alignment."""
    shape = bd.Rot(37, 22, 10) * bd.Cylinder(4, 9)
    _spec, outcome = _check(shape, min=1.0)
    assert not isinstance(outcome, Unsupported)
    assert min(outcome.value) == pytest.approx(0.0, abs=1e-9)


def test_an_unattributed_draft_min_draws_the_warning(tmp_path):
    """PR #141 review, F3: min= is a number an author chose — exactly the
    circularizable class the attribution warning exists for — and the check
    was missing from DIMENSIONAL_KINDS, so a draft-only contract drew no
    warning."""

    from partspec.cli import main

    model = "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    (tmp_path / "m.py").write_text(model)
    target = py_target(
        tmp_path,
        claims="    p.draft_angle(min=2.0)\n",
    )
    out = tmp_path / "out"
    main(["check", target, "--quiet", "--out", str(out)])
    report = report_of(out)
    assert report["attribution"]["dimensional"] == 1
    assert report["attribution"]["attributed"] == 0
