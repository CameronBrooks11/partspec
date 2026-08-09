"""self_intersection_free (#138): the check D14 deferred, on the tier that
answers it. Every claim here is executed fact, including the recorded limit.
"""

from __future__ import annotations

import json

import pytest

bd = pytest.importorskip("build123d", reason="occt extra not installed")

from partspec.backends.occt import OcctBackend  # noqa: E402
from partspec.cli import main  # noqa: E402


def _tight_sweep():
    """The classic self-intersecting solid: a profile wider than twice the
    bend radius, so the inner side overlaps itself through the turn. The
    profile plane is built from the path's own frame — the first fixture put
    the width along the path tangent and produced a degenerate zero-volume
    shape that failed for the wrong reason (PR #142 review, F3)."""
    arc = bd.CenterArc((0, 0, 0), 3, 0, 180)
    profile = bd.Plane(origin=arc @ 0, x_dir=(1, 0, 0), z_dir=arc % 0) * bd.Rectangle(10, 2)
    return bd.sweep(profile, arc)


def _overlapping_helix():
    """Adjacent coils overlap (pitch 2 < profile diameter 3): the kernel
    catches the swept face against ITSELF, a pair-less fault."""
    helix = bd.Helix(2, 3, 3)
    profile = bd.Plane(origin=helix @ 0, z_dir=helix % 0) * bd.Circle(1.5)
    return bd.sweep(profile, helix)


def test_a_sound_part_is_free_exactly():
    outcome = OcctBackend().self_intersection_free(bd.Box(10, 10, 10))
    assert outcome.value is True
    assert outcome.exact is True


def test_the_tight_sweep_fails_with_the_faults_named():
    backend = OcctBackend()
    shape = _tight_sweep()
    assert shape.volume > 100, "the fixture must be real material, not degenerate"
    assert backend.self_intersection_free(shape).value is False
    detail = backend.self_intersection_free_detail(shape)
    assert "entity fault" in detail
    assert "edge/face" in detail, "the fault types are the actionable part"


def test_a_self_overlapping_swept_face_is_caught_pair_less():
    """PR #142 review, F1: the first draft claimed single-surface
    self-intersection is invisible in general. It is not — the kernel tests
    a face against itself, and the overlapping helix is caught as a
    pair-less fault. This pins the kernel's reach so the recorded limit
    stays exactly as wide as reality."""
    backend = OcctBackend()
    shape = _overlapping_helix()
    assert backend.self_intersection_free(shape).value is False
    detail = backend.self_intersection_free_detail(shape)
    assert "1 face" in detail, "the pair-less fault: a face against itself"


def test_the_spindle_torus_is_the_recorded_limit():
    """The escape that remains: a self-intersection lying within a single
    ANALYTIC surface goes undetected — alone and fused into a multi-face
    shape. If the kernel ever starts catching it, this fails and the
    SPEC 4.9 sentence must move."""
    backend = OcctBackend()
    assert backend.self_intersection_free(bd.Torus(6, 10)).value is True
    # Genuinely overlapping fuse (reviewer-verified: volume < sum, real
    # intersection seams cut into the torus surface) — the strongest form
    # of the escape. The boolean even splits the result into two solids,
    # OCCT already misbehaving on the self-intersecting operand: the
    # motivation prose made flesh.
    fused = bd.Torus(6, 10) + bd.Pos(0, 0, -12) * bd.Box(30, 30, 8)
    assert backend.self_intersection_free(fused).value is True


def test_neither_validity_check_subsumes_the_other():
    """PR #142 review, F2: the first pin used two AGREEMENT cases, which is
    consistent with the checks being identical. These are the disagreement
    witnesses, one per direction — the only evidence that proves
    non-subsumption."""
    backend = OcctBackend()
    # valid but self-intersecting: the overlapping helix.
    helix = _overlapping_helix()
    assert backend.is_valid(helix).value is True
    assert backend.self_intersection_free(helix).value is False
    # invalid but self-intersection-free: an open shell forced into a solid.
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_Sewing,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing()
    for face in bd.Box(10, 10, 10).faces()[:5]:
        sew.Add(face.wrapped)
    sew.Perform()
    forced = bd.Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew.SewedShape())).Solid())
    assert backend.is_valid(forced).value is False
    assert backend.self_intersection_free(forced).value is True


def test_the_status_filter_is_load_bearing():
    """PR #142 review, F4: dropping the SelfIntersect status filter survived
    the suite. The tight sweep's analysis emits non-SI results too (a
    NotValid summary); the fault count must reflect only the
    self-intersections."""
    backend = OcctBackend()
    faults = backend._self_intersections(_tight_sweep())
    assert len(faults) == 8, "exactly the SI faults, no phantom entries"
    assert all(f for f in faults), "no empty-kind entries from non-SI results"


def test_an_overlapping_compound_fails_as_its_own_boundary():
    """SPEC 4.9's multi-solid sentence, executed: two overlapping unfused
    solids in one part are that part's boundary contradicting itself — a
    fail, loudly, not D11 clearance business."""
    backend = OcctBackend()
    overlapping = bd.Compound([bd.Box(10, 10, 10), bd.Pos(4, 0, 0) * bd.Box(10, 10, 10)])
    assert backend.self_intersection_free(overlapping).value is False


def test_the_check_through_the_cli_names_the_defect(tmp_path):
    (tmp_path / "m.py").write_text(
        "import build123d as bd\n\n\ndef make_part():\n"
        "    arc = bd.CenterArc((0, 0, 0), 3, 0, 180)\n"
        "    profile = (bd.Plane.YZ * bd.Rectangle(10, 2)).located(bd.Location((3, 0, 0)))\n"
        "    return bd.sweep(profile, arc)\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.self_intersection_free()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 1
    check = next(
        c
        for c in json.loads((out / "report.json").read_text())["checks"]
        if c["kind"] == "self_intersection_free"
    )
    assert check["status"] == "fail"
    assert check["measurement"]["value"] is False
    assert "entity fault" in check["detail"]


def test_a_sound_part_passes_through_the_cli(tmp_path):
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.self_intersection_free()\n"
        "    return p\n"
    )
    assert (
        main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(tmp_path / "o")])
        == 0
    )


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
        "    p.self_intersection_free()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 2
    check = next(
        c
        for c in json.loads((out / "report.json").read_text())["checks"]
        if c["kind"] == "self_intersection_free"
    )
    assert check["status"] == "unsupported"
    assert check["requires"] == "occt"


def test_measure_lists_the_quantity(tmp_path):
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
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
    assert doc["measurements"]["self_intersection_free"]["value"] is True
    assert doc["measurements"]["self_intersection_free"]["exactness"] == "exact"
