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
from support import measured, refused

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


def test_the_openscad_binary_can_be_pinned(monkeypatch):
    """The engine version changes the artifact, so it must be pinnable.

    Measured on a gear library: 2021.01 honours the removed `assign()` construct
    and 2026.08.01 ignores it, so the same source yields a part 35% smaller in
    every planar dimension — both exiting 0 with clean watertight meshes.

    An environment variable rather than a contract field, because which binary
    is installed is a property of the machine, not of the design.
    """
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, "/some/pinned/openscad")
    assert openscad.find_executable() == "/some/pinned/openscad"


def test_without_the_pin_discovery_is_used(monkeypatch):
    monkeypatch.delenv(openscad.ENV_EXECUTABLE, raising=False)
    found = openscad.find_executable()
    assert found is None or "openscad" in found.lower()


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

    volume = measured(backend.volume(mesh))
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


def test_watertight_detail_distinguishes_the_two_defects(backend: MeshBackend):
    """ "Not watertight" conflates a hole with a non-manifold junction.

    trimesh's `is_watertight` means "every edge used by exactly two faces". An
    edge used **once** is a hole; an edge used **more than twice** is a place
    where surfaces touch. Different causes, different fixes — and dogfooding hit
    the second on a community gridfinity bin whose mesh has 0 boundary edges and
    4 non-manifold ones, where "not watertight" alone reads as "it has holes".
    """
    open_shell = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        faces=[[0, 1, 2], [0, 1, 3], [0, 2, 3]],
    )
    detail = backend.watertight_detail(open_shell)
    assert detail is not None and "boundary edge" in detail

    # Two tetrahedra sharing a single edge: closed, but non-manifold along it.
    verts = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0]]
    faces = [
        [0, 1, 2],
        [0, 1, 3],
        [0, 2, 3],
        [1, 2, 3],
        [0, 4, 5],
        [0, 4, 3],
        [0, 5, 3],
        [4, 5, 3],
    ]
    touching = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    detail = backend.watertight_detail(touching)
    assert detail is not None and "non-manifold" in detail


def test_watertight_detail_is_none_when_fine(backend: MeshBackend):
    assert backend.watertight_detail(trimesh.creation.box(extents=(1, 1, 1))) is None


def test_solid_count_without_scipy(backend: MeshBackend):
    """trimesh's `body_count` needs scipy, which the mesh extra does not install."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))
    assert measured(backend.solid_count(a)).value == 1
    assert measured(backend.solid_count(trimesh.util.concatenate([a, b]))).value == 2


def test_genus_counts_through_holes(backend: MeshBackend):
    assert measured(backend.genus(trimesh.creation.box(extents=(2, 2, 2)))).value == 0
    torus = trimesh.creation.torus(major_radius=10, minor_radius=3)
    assert measured(backend.genus(torus)).value == 1


def test_genus_counts_two_separate_through_holes(backend: MeshBackend):
    """Genus 2 — the case separating a real Euler characteristic from anything
    that merely detects "has a hole".

    A block drilled twice, mirroring the OCCT tier's parametrisation so the two
    backends are checked against the same claim. Two disjoint bores through one
    body are two independent handles by construction, which is why this is
    asserted from theory rather than from what the tool returned.
    """
    block = trimesh.creation.box(extents=(30, 20, 10))
    holes = [
        trimesh.creation.cylinder(radius=2, height=40, transform=t)
        for t in (
            trimesh.transformations.translation_matrix((8, 0, 0)),
            trimesh.transformations.translation_matrix((-8, 0, 0)),
        )
    ]
    drilled = block.difference(holes[0]).difference(holes[1])

    assert drilled.is_watertight, "premise: the boolean produced a sound mesh"
    assert measured(backend.solid_count(drilled)).value == 1
    assert measured(backend.genus(drilled)).value == 2


def test_genus_is_refused_for_multi_body_parts(backend: MeshBackend):
    """Genus is defined per body; the Euler characteristic of a complex is a
    different number. Two disjoint boxes give -1 — mathematically correct, and
    an answer to a question nobody asked. Refusing beats returning it."""
    a = trimesh.creation.box(extents=(5, 5, 5))
    b = trimesh.creation.box(extents=(5, 5, 5))
    b.apply_translation((20, 0, 0))

    result = refused(backend.genus(trimesh.util.concatenate([a, b])))
    assert "per body" in result.reason
    assert "2 solids" in result.reason


# --------------------------------------------------------------------------
# refusal — the preconditions each measurement presumes (dogfood F14)
#
# Until 2026-08-05 every one of these returned a confident number flagged
# `exact`. None of the 169 tests then in the suite covered it, because all of
# them measured meshes that were already sound — which is why the probe that
# found it built a deliberately broken one.
# --------------------------------------------------------------------------


@pytest.fixture
def open_cube():
    """A cube with one face (2 triangles) removed. Encloses nothing."""
    cube = trimesh.creation.box(extents=(10, 10, 10))
    return trimesh.Trimesh(
        vertices=cube.vertices.copy(), faces=cube.faces[:-2].copy(), process=False
    )


@pytest.fixture
def touching_tets():
    """Two tetrahedra sharing one edge: closed, but non-manifold along it."""
    return trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0]],
        faces=[
            [0, 1, 2],
            [0, 1, 3],
            [0, 2, 3],
            [1, 2, 3],
            [0, 4, 5],
            [0, 4, 3],
            [0, 5, 3],
            [4, 5, 3],
        ],
        process=False,
    )


def test_volume_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """The headline case. trimesh does not raise or return NaN — it returns half
    the volume of the closed cube, which reads as an ordinary measurement."""
    assert open_cube.volume == pytest.approx(500.0), "premise: the raw property answers"
    reason = refused(backend.volume(open_cube)).reason
    assert "closed surface" in reason
    assert "boundary edge" in reason, "the refusal names the actual defect"


def test_center_of_mass_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """It previously reported (-2.5, 0, 0) — a point outside the material."""
    assert "closed surface" in refused(backend.center_of_mass(open_cube)).reason


def test_genus_is_refused_on_an_open_mesh(backend: MeshBackend, open_cube):
    """It previously reported genus 1: a through-hole that does not exist."""
    assert "closed surface" in refused(backend.genus(open_cube)).reason


def test_volume_is_refused_when_the_winding_is_inconsistent(backend: MeshBackend):
    """Closed is not sufficient. The divergence theorem sums *signed*
    contributions, so a flipped triangle subtracts where it should add. Edge use
    is unchanged by winding, so `is_watertight` cannot see this."""
    cube = trimesh.creation.box(extents=(10, 10, 10))
    faces = cube.faces.copy()
    faces[0] = faces[0][::-1]
    flipped = trimesh.Trimesh(vertices=cube.vertices.copy(), faces=faces, process=False)

    assert flipped.is_watertight, "premise: still closed"
    assert not flipped.is_winding_consistent
    assert "winding" in refused(backend.volume(flipped)).reason


def test_body_count_is_refused_where_the_geometry_does_not_fix_it(
    backend: MeshBackend, touching_tets
):
    """A non-manifold edge leaves the count genuinely undetermined: counting
    through the junction gives 1 and counting across it gives 2. On the F10
    gridfinity bin manifold3d welds and says 1 while the exported triangles say
    3. Both are defensible, so neither may be reported as exact."""
    assert "non-manifold" in refused(backend.solid_count(touching_tets)).reason


def test_body_count_survives_an_open_mesh(backend: MeshBackend, open_cube):
    """Refuse the undefined, not the merely unusual. With no non-manifold edge
    the adjacency is unambiguous, so the count is determined even though the
    surface is open — and over-refusal inflates `incomplete`, which is its own
    way of failing to answer an answerable question."""
    assert measured(backend.solid_count(open_cube)).value == 1


def test_area_and_bbox_survive_an_open_mesh(backend: MeshBackend, open_cube):
    """Both are statements about the triangles as exported, not about what they
    enclose. Five faces of a 10mm cube: 500mm2."""
    assert backend.area(open_cube).value == pytest.approx(500.0)
    assert backend.bbox(open_cube).value == pytest.approx((10.0, 10.0, 10.0))
    assert backend.watertight(open_cube).value is False


def test_a_rejected_manifold_is_never_read(backend: MeshBackend, open_cube):
    """Pins the dependency behaviour that caused the bug.

    Handed an open mesh, manifold3d returns an object reporting
    `Error.NotManifold` with zero triangles — and `.decompose()` on that empty
    object still returns a one-element list while `.genus()` still returns 1.
    Reading those without checking `status()` is exactly how this backend came
    to report a through-hole in an open shell.
    """
    import numpy as np
    from manifold3d import Error, Manifold, Mesh

    raw = Manifold(
        Mesh(
            vert_properties=np.asarray(open_cube.vertices, dtype=np.float32),
            tri_verts=np.asarray(open_cube.faces, dtype=np.uint32),
        )
    )
    assert raw.status() != Error.NoError, "premise: manifold3d knows"
    assert raw.is_empty() and raw.num_tri() == 0
    assert len(raw.decompose()) == 1, "premise: the empty object still answers"
    assert raw.genus() == 1, "premise: and answers wrongly"

    from partspec.backends.mesh import _manifold

    assert isinstance(_manifold(open_cube), Unsupported), "so the wrapper must refuse"


# --------------------------------------------------------------------------
# D15 — measuring the artifact as exported, not a library's rebuild of it
# --------------------------------------------------------------------------


def test_measurements_do_not_route_through_manifold3d(backend: MeshBackend):
    """manifold3d rebuilds the mesh it is handed, so nothing absolute may be
    read from it.

    Measured on the clean CGAL-rendered gridfinity bin: same 5,330 vertices,
    none moved, yet it retriangulated 55 of 10,688 triangles and moved the
    enclosed volume by 25.31 mm3 (0.078%). An independent divergence-theorem sum
    agrees with trimesh, not with manifold3d. Reporting genus and body count
    from that rebuild described a solid the engine never exported.
    """
    torus = trimesh.creation.torus(major_radius=10, minor_radius=3)
    calls: list[str] = []

    def tripwire(mesh):
        calls.append("manifold3d")
        raise AssertionError("no absolute measurement may go through manifold3d")

    import partspec.backends.mesh as mesh_mod

    original = mesh_mod._manifold
    mesh_mod._manifold = tripwire
    try:
        assert measured(backend.volume(torus)).value > 0
        assert measured(backend.solid_count(torus)).value == 1
        assert measured(backend.genus(torus)).value == 1
        assert measured(backend.center_of_mass(torus)).value is not None
    finally:
        mesh_mod._manifold = original
    assert calls == []


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("box", lambda: trimesh.creation.box(extents=(5, 5, 5))),
        ("torus", lambda: trimesh.creation.torus(major_radius=10, minor_radius=3)),
        ("cylinder", lambda: trimesh.creation.cylinder(radius=4, height=9, sections=24)),
    ],
)
def test_the_replacement_agrees_with_manifold3d_on_sound_meshes(backend: MeshBackend, name, build):
    """The equivalence claim behind dropping manifold3d: on input it accepts,
    the direct computation gives the same answer. It is only on input manifold3d
    silently repairs that the two part company — and there the direct one is
    right, because it measures what was exported."""
    import numpy as np
    from manifold3d import Manifold, Mesh

    mesh = build()
    reference = Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )
    assert measured(backend.solid_count(mesh)).value == len(reference.decompose()), name
    assert measured(backend.genus(mesh)).value == reference.genus(), name


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
    gap = measured(backend.min_distance(a, b))
    assert gap.value == pytest.approx(10.0, abs=1e-4)
    assert gap.exact


def test_intersect_volume_is_exact_on_polyhedra(backend: MeshBackend):
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.box(extents=(10, 10, 10))
    b.apply_translation((5, 0, 0))  # half overlap
    assert measured(backend.intersect_volume(a, b)).value == pytest.approx(500.0, rel=1e-3)


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

    assert measured(backend.volume(mesh)).value == pytest.approx(expected_volume)
    assert backend.area(mesh).value == pytest.approx(expected_area)
    assert backend.bbox(mesh).value == pytest.approx((30.0, 20.0, 10.0))
    assert backend.watertight(mesh).value is True
    assert measured(backend.solid_count(mesh)).value == 1
    com = measured(backend.center_of_mass(mesh))
    assert com.value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert measured(backend.genus(mesh)).value == 1, "a through-hole is genus 1"


@needs_openscad
def test_every_measured_quantity_is_flagged_exact(backend: MeshBackend, tmp_path: Path):
    """Under D15 nothing on this tier is approximate, and each measurement must
    say so rather than leaving a consumer to assume it."""
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "block_with_hole.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measured(measure(mesh))
        assert result.exact, measure.__name__
        assert result.bounds is None, measure.__name__


@needs_openscad
def test_render_backend_is_passed_through_when_set(backend: MeshBackend, tmp_path: Path):
    """The backend changes the artifact, not just the speed: on a community
    gridfinity bin, Manifold produced 4 non-manifold edges where CGAL produced
    a clean mesh from identical source. So it must be selectable and recorded.

    Only asserts the flag is accepted and geometry still measures — the two
    backends agree on a simple polyhedron, which is the point.
    """
    src = OpenSCADSource(path=FIXTURES / "block_with_hole.scad", backend="CGAL")
    mesh = backend.build(src, tmp_path)
    assert not isinstance(mesh, BuildError), mesh
    assert measured(backend.volume(mesh)).value == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)


@needs_openscad
def test_two_bodies(backend: MeshBackend, tmp_path: Path):
    mesh = backend.build(OpenSCADSource(path=FIXTURES / "two_bodies.scad"), tmp_path)
    assert not isinstance(mesh, BuildError)
    assert measured(backend.solid_count(mesh)).value == 2
    assert measured(backend.volume(mesh)).value == pytest.approx(2 * 5**3)
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
    assert measured(backend.volume(mesh)).value == pytest.approx(100 * 50 * 2)


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
    volume = measured(backend.volume(mesh))
    assert volume.value == pytest.approx(prism_volume, rel=1e-4)
    assert volume.value < math.pi * r**2 * h, "inscribed prism reads low"
    assert volume.exact


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
