"""The mesh backend, verified against analytically-known geometry.

Two tiers of test, deliberately separated:

* Measurement tests build their input with trimesh, so they run anywhere the
  mesh extra is installed — including CI, which has no OpenSCAD binary.
* Engine tests shell out to OpenSCAD and skip when it is absent. Their fixtures
  are chosen so every expected number has a closed form; asserting against
  whatever the tool produced would test nothing.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from partspec.backend import BuildError, Tier, Unsupported
from partspec.backends.mesh import MeshBackend
from partspec.engines import openscad
from partspec.engines.openscad import OpenSCADSource, scad_literal

trimesh = pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"

needs_openscad = pytest.mark.skipif(
    openscad.find_executable() is None, reason="openscad binary not installed"
)


@pytest.fixture
def backend() -> MeshBackend:
    return MeshBackend()


# --------------------------------------------------------------------------
# scad_literal — pure, no engine
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, "10"),
        (0.2, "0.2"),
        ("pin", '"pin"'),
        (None, "undef"),
        ([1, 2, 3], "[1, 2, 3]"),
        ((1.5, "a"), '[1.5, "a"]'),
    ],
)
def test_scad_literal(value, expected):
    assert scad_literal(value) == expected


def test_bools_do_not_degrade_into_ints():
    """`bool` subclasses `int` in Python, so the obvious isinstance ordering
    silently renders True as 1. OpenSCAD then compares a number where a boolean
    was meant."""
    assert scad_literal(True) == "true"
    assert scad_literal(False) == "false"


def test_strings_are_escaped():
    assert scad_literal('a"b') == '"a\\"b"'
    assert scad_literal("a\nb") == '"a\\nb"'


def test_unrenderable_value_is_rejected_loudly():
    with pytest.raises(TypeError):
        scad_literal({"a": 1})


# --------------------------------------------------------------------------
# measurement — analytic, engine-free
# --------------------------------------------------------------------------


def test_cube_measures_exactly(backend: MeshBackend):
    """A polyhedron's volume and area are closed-form. Under D15 the mesh *is*
    the part, so these are exact — not approximations of anything."""
    mesh = trimesh.creation.box(extents=(10, 20, 30))

    volume = backend.volume(mesh)
    assert volume.value == pytest.approx(6000.0)
    assert volume.exact and volume.bounds is None

    area = backend.area(mesh)
    assert area.value == pytest.approx(2 * (10 * 20 + 20 * 30 + 10 * 30))
    assert area.exact


def test_bbox_is_a_named_vector(backend: MeshBackend):
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    bbox = backend.bbox(mesh)
    assert bbox.value == pytest.approx((10.0, 20.0, 30.0))
    assert bbox.axes == ("x", "y", "z")
    assert bbox.exact


def test_watertight_and_validity(backend: MeshBackend):
    mesh = trimesh.creation.box(extents=(1, 1, 1))
    assert backend.watertight(mesh).value is True
    assert backend.is_valid(mesh).value is True


def test_open_shell_is_not_watertight(backend: MeshBackend):
    """The case OpenSCAD's own --summary gets wrong: it omits the validity key
    entirely and exits 0, so `.get("simple", True)` passes a broken part."""
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        faces=[[0, 1, 2], [0, 1, 3], [0, 2, 3]],  # one face short of closed
    )
    assert backend.watertight(mesh).value is False


def test_solid_count_without_scipy(backend: MeshBackend):
    """Via manifold3d. trimesh's body_count needs a graph engine we do not ship."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))
    assert backend.solid_count(a).value == 1
    assert backend.solid_count(trimesh.util.concatenate([a, b])).value == 2


def test_genus_counts_through_holes(backend: MeshBackend):
    solid = backend.genus(trimesh.creation.box(extents=(2, 2, 2)))
    assert not isinstance(solid, Unsupported)
    assert solid.value == 0

    torus = backend.genus(trimesh.creation.torus(major_radius=10, minor_radius=3))
    assert not isinstance(torus, Unsupported)
    assert torus.value == 1


def test_genus_is_refused_for_multi_body_parts(backend: MeshBackend):
    """manifold3d reports the genus of the whole complex, which for two disjoint
    boxes is -1 — mathematically correct, and an answer to a question nobody
    asked. Refusing beats returning it."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))

    result = backend.genus(trimesh.util.concatenate([a, b]))
    assert isinstance(result, Unsupported)
    assert "per body" in result.reason
    assert "2 solids" in result.reason


def test_topology_counts_are_always_refused(backend: MeshBackend):
    """The PartCAD failure, prevented structurally: a triangle count is not a
    face count, so the query is refused rather than answered wrongly."""
    result = backend.topology_counts(trimesh.creation.box(extents=(1, 1, 1)))
    assert isinstance(result, Unsupported)
    assert result.requires == Tier.OCCT


def test_topology_is_not_in_capabilities(backend: MeshBackend):
    assert "topology_counts" not in backend.capabilities()
    assert "volume" in backend.capabilities()


def test_min_distance_is_exact_on_polyhedra(backend: MeshBackend):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10))
    b.apply_translation((20, 0, 0))  # 10mm gap between facing walls
    gap = backend.min_distance(a, b)
    assert gap.value == pytest.approx(10.0, abs=1e-4)
    assert gap.exact


def test_intersect_volume_is_exact_on_polyhedra(backend: MeshBackend):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10))
    b.apply_translation((5, 0, 0))  # half overlap
    assert backend.intersect_volume(a, b).value == pytest.approx(500.0, rel=1e-3)


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def test_distinct_normals_track_facet_resolution(backend: MeshBackend):
    """The identity signal: a cylinder at $fn=n has n+2 distinct normals."""
    for sections in (16, 32, 64):
        mesh = trimesh.creation.cylinder(radius=5, height=10, sections=sections)
        assert backend.provenance(mesh)["distinct_normals"] == sections + 2


def test_distinct_normals_survive_retriangulation(backend: MeshBackend):
    """Why it is the identity signal and `triangles` is not: subdividing changes
    the triangle count without changing the design."""
    cube = trimesh.creation.box(extents=(10, 20, 30))
    coarse = backend.provenance(cube)
    fine = backend.provenance(cube.subdivide())

    assert fine["triangles"] > coarse["triangles"]
    assert fine["distinct_normals"] == coarse["distinct_normals"] == 6


# --------------------------------------------------------------------------
# engine — needs the OpenSCAD binary
# --------------------------------------------------------------------------


@needs_openscad
def test_block_with_hole_matches_closed_form(backend: MeshBackend, tmp_path: Path):
    """The P1 exit criterion, on a shape whose every quantity has a closed form.

    30x20x10 block with a 6x6 square through-hole along Z.
    """
    source = OpenSCADSource(path=FIXTURES / "block_with_hole.scad")
    mesh = backend.build(source, tmp_path)
    assert not isinstance(mesh, BuildError), mesh

    expected_volume = 30 * 20 * 10 - 6 * 6 * 10
    outer = 2 * (30 * 20) + 2 * (30 * 10) + 2 * (20 * 10)
    expected_area = outer - 2 * (6 * 6) + 4 * (6 * 10)

    assert backend.volume(mesh).value == pytest.approx(expected_volume)
    assert backend.area(mesh).value == pytest.approx(expected_area)
    assert backend.bbox(mesh).value == pytest.approx((30.0, 20.0, 10.0))
    assert backend.watertight(mesh).value is True
    assert backend.solid_count(mesh).value == 1
    assert backend.center_of_mass(mesh).value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)

    genus = backend.genus(mesh)
    assert not isinstance(genus, Unsupported), genus
    assert genus.value == 1, "a through-hole is genus 1"


@needs_openscad
def test_every_measured_quantity_is_flagged_exact(backend: MeshBackend, tmp_path: Path):
    """Under D15 nothing on this tier is approximate, and each measurement must
    say so rather than leaving a consumer to assume it."""
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "block_with_hole.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measure(mesh)
        assert result.exact, measure.__name__
        assert result.bounds is None, measure.__name__


@needs_openscad
def test_two_bodies(backend: MeshBackend, tmp_path: Path):
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "two_bodies.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    assert backend.solid_count(mesh).value == 2
    assert backend.volume(mesh).value == pytest.approx(2 * 5**3)
    assert isinstance(backend.genus(mesh), Unsupported)


@needs_openscad
def test_parameters_reach_the_engine(backend: MeshBackend, tmp_path: Path):
    """-D overrides actually change the geometry — the thing every parametric
    contract depends on."""
    source = OpenSCADSource(
        path=FIXTURES / "parametric_plate.scad",
        params={"plate_x": 100, "plate_y": 50, "plate_z": 2},
    )
    mesh = backend.build(source, tmp_path)
    assert not isinstance(mesh, BuildError)
    assert backend.bbox(mesh).value == pytest.approx((100.0, 50.0, 2.0))
    assert backend.volume(mesh).value == pytest.approx(100 * 50 * 2)


@needs_openscad
def test_curved_geometry_is_still_exact_for_the_polyhedron(backend: MeshBackend, tmp_path: Path):
    """A $fn=16 cylinder is a 16-gon prism, and partspec measures the prism.

    The volume is the prism's closed form, NOT pi*r^2*h. That difference is the
    whole of D15: the smooth cylinder was never the part.
    """
    scad = tmp_path / "cyl.scad"
    scad.write_text("cylinder(h = 10, r = 5, $fn = 16);\n")
    mesh = backend.build(OpenSCADSource(path=scad), tmp_path)
    assert not isinstance(mesh, BuildError)

    n, r, h = 16, 5.0, 10.0
    prism_volume = 0.5 * n * r**2 * math.sin(2 * math.pi / n) * h
    assert backend.volume(mesh).value == pytest.approx(prism_volume, rel=1e-4)
    assert backend.volume(mesh).value < math.pi * r**2 * h, "inscribed prism reads low"
    assert backend.volume(mesh).exact


# --------------------------------------------------------------------------
# build errors
# --------------------------------------------------------------------------


@needs_openscad
def test_missing_source_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    result = backend.build(OpenSCADSource(path=tmp_path / "nope.scad"), tmp_path)
    assert isinstance(result, BuildError)
    assert "not found" in result.message


@needs_openscad
def test_syntax_error_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    bad = tmp_path / "bad.scad"
    bad.write_text("cube([1,2,3)\n")
    result = backend.build(OpenSCADSource(path=bad), tmp_path)
    assert isinstance(result, BuildError)


@needs_openscad
def test_empty_geometry_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    """OpenSCAD exits 0 on a file that produces nothing, so the artifact is
    checked rather than the exit code trusted."""
    empty = tmp_path / "empty.scad"
    empty.write_text("// nothing here\n")
    result = backend.build(OpenSCADSource(path=empty), tmp_path)
    assert isinstance(result, BuildError)
