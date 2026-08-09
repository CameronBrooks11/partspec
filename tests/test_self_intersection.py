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
    bend radius, so the inner side overlaps itself through the turn."""
    arc = bd.CenterArc((0, 0, 0), 3, 0, 180)
    profile = (bd.Plane.YZ * bd.Rectangle(10, 2)).located(bd.Location((3, 0, 0)))
    return bd.sweep(profile, arc)


def test_a_sound_part_is_free_exactly():
    outcome = OcctBackend().self_intersection_free(bd.Box(10, 10, 10))
    assert outcome.value is True
    assert outcome.exact is True


def test_the_tight_sweep_fails_with_the_pairs_named():
    backend = OcctBackend()
    shape = _tight_sweep()
    assert backend.self_intersection_free(shape).value is False
    detail = backend.self_intersection_free_detail(shape)
    assert "entity pair" in detail
    assert "edge/face" in detail, "the pair types are the actionable part"


def test_the_spindle_torus_is_the_recorded_limit():
    """A single surface intersecting ITSELF internally has no sub-shape pair
    to flag: the spindle torus passes. This pin is the SPEC-contract 4.9
    limit as executed fact — if the kernel ever starts catching it, this
    test fails and the spec sentence must move."""
    outcome = OcctBackend().self_intersection_free(bd.Torus(6, 10))
    assert outcome.value is True


def test_neither_validity_check_subsumes_the_other():
    """is_valid (BRepCheck) and self_intersection_free answer different
    questions: the tight sweep fails both, the spindle torus passes both —
    executed here so the spec's relationship claim cannot drift."""
    backend = OcctBackend()
    sweep = _tight_sweep()
    assert backend.is_valid(sweep).value is False
    assert backend.self_intersection_free(sweep).value is False
    spindle = bd.Torus(6, 10)
    assert backend.is_valid(spindle).value is True
    assert backend.self_intersection_free(spindle).value is True


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
    assert "entity pair" in check["detail"]


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
