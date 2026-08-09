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


def test_the_gap_is_not_a_wall():
    """The U-channel trap: walls 3.0, gap 1.0 — the two-signal test must
    reject the gap pair, or min_wall silently becomes min_gap."""
    channel = bd.Box(7, 20, 10) - bd.Pos(0, 0, 1.5) * bd.Box(1, 20, 7)
    raw = _raw(channel)
    assert isinstance(raw, dict)
    assert raw["lo"] == pytest.approx(3.0, abs=1e-9)


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
