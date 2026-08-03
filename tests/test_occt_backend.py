"""The OCCT backend, and the claim that one implementation serves both engines.

Fixtures are built in-process with build123d and CadQuery rather than loaded from
files, so these run wherever the occt extra is installed and assert against
closed-form geometry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from partspec.backend import BuildError, Tier, Unsupported
from partspec.backends.occt import OcctBackend
from partspec.engines.pycad import PyCADSource, adopt

bd = pytest.importorskip("build123d", reason="occt extra not installed")


@pytest.fixture
def backend() -> OcctBackend:
    return OcctBackend("build123d")


# --------------------------------------------------------------------------
# adoption — the D3 claim
# --------------------------------------------------------------------------


def test_build123d_shape_is_adopted():
    adopted = adopt(bd.Box(10, 20, 30))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0)


def test_cadquery_shape_is_adopted_losslessly():
    """The whole basis for 'two backends, not three': a CadQuery result is a
    handle rewrap away from a build123d one, with no conversion."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    adopted = adopt(cq.Workplane("XY").box(10, 20, 30))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0)
    assert len(adopted.faces()) == 6, "real topology, not triangles"


def test_cadquery_multi_solid_adopts_as_a_compound():
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    w = cq.Workplane("XY").box(5, 5, 5).moveTo(20, 0).box(5, 5, 5)
    adopted = adopt(cq.Compound.makeCompound(w.vals()))
    assert not isinstance(adopted, BuildError)
    assert len(adopted.solids()) == 2
    assert adopted.volume == pytest.approx(250.0)


def test_wrong_wrapper_would_have_been_worse_than_failing():
    """Guards the reason adoption dispatches on ShapeType rather than using
    Shape.cast (which returns None) or a single wrapper: Compound(solid)
    constructs happily and reports volume 0."""
    solid = bd.Box(10, 20, 30).solids()[0]
    assert bd.Compound(solid.wrapped).volume == 0, "premise: the wrong wrapper lies"

    adopted = adopt(solid)
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(6000.0), "adoption picks the right one"


def test_is_valid_uses_the_property_not_the_method(backend: OcctBackend):
    """build123d exposes `is_valid` as a property; CadQuery as `isValid()`.
    Calling it as a method here raised `TypeError: 'bool' object is not
    callable` — the exact divergence SPEC-backend section 4 names as the reason
    the adopt shim exists."""
    assert backend.is_valid(bd.Box(1, 1, 1)).value is True


def test_a_non_shape_is_a_build_error():
    result = adopt("not a shape")
    assert isinstance(result, BuildError)
    assert "not a build123d or CadQuery shape" in result.message


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------


def test_closed_form_measurements(backend: OcctBackend):
    box = bd.Box(10, 20, 30)
    assert backend.volume(box).value == pytest.approx(6000.0)
    assert backend.area(box).value == pytest.approx(2 * (200 + 600 + 300))
    assert backend.bbox(box).value == pytest.approx((10.0, 20.0, 30.0))
    assert backend.center_of_mass(box).value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert backend.watertight(box).value is True
    assert backend.solid_count(box).value == 1


def test_everything_on_this_tier_is_exact(backend: OcctBackend):
    """No tessellation anywhere, so nothing carries an error bound."""
    box = bd.Box(10, 20, 30)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measure(box)
        assert result.exact and result.bounds is None


def test_curved_geometry_is_analytic_not_faceted(backend: OcctBackend):
    """The tier difference in one assertion: OCCT gives pi*r^2*h exactly, where
    the mesh tier would give an inscribed prism."""
    import math

    cyl = bd.Cylinder(radius=5, height=10)
    assert backend.volume(cyl).value == pytest.approx(math.pi * 25 * 10, rel=1e-9)
    assert backend.volume(cyl).exact


# --------------------------------------------------------------------------
# topology — the reason this tier exists
# --------------------------------------------------------------------------


def test_topology_counts_are_answered_here(backend: OcctBackend):
    """Refused on mesh, answered here. That asymmetry is the point of tiers."""
    result = backend.topology_counts(bd.Box(10, 20, 30))
    assert not isinstance(result, Unsupported)
    assert result.value == (6, 12, 8), "faces, edges, vertices of a box"
    assert result.axes == ("faces", "edges", "vertices")


def test_a_cylinder_has_analytic_faces_not_facets(backend: OcctBackend):
    """3 faces (top, bottom, one cylindrical), never $fn of them."""
    assert backend.topology_counts(bd.Cylinder(radius=5, height=10)).value[0] == 3


# --------------------------------------------------------------------------
# genus — where the naive formula is wrong
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "shape", "expected"),
    [
        ("box", bd.Box(30, 20, 10), 0),
        ("one through-hole", bd.Box(30, 20, 10) - bd.Cylinder(3, 20), 1),
        (
            "two through-holes",
            bd.Box(30, 20, 10)
            - bd.Cylinder(2, 20).moved(bd.Location((8, 0, 0)))
            - bd.Cylinder(2, 20).moved(bd.Location((-8, 0, 0))),
            2,
        ),
        ("blind hole", bd.Box(30, 20, 10) - bd.Cylinder(3, 5).moved(bd.Location((0, 0, 3))), 0),
        ("tube", bd.Cylinder(10, 5) - bd.Cylinder(5, 20), 1),
    ],
)
def test_genus_via_euler_poincare(backend: OcctBackend, name, shape, expected):
    """The naive V - E + F is wrong on a BREP and quietly so.

    OCCT faces carry inner wires, so a face with a hole is an annulus rather
    than a disc. Measured, the naive form calls a through-hole genus 0 and a
    *blind* hole genus -1. Including the wire count fixes both.
    """
    result = backend.genus(shape)
    assert not isinstance(result, Unsupported), result
    assert result.value == expected, name


def test_the_naive_euler_formula_would_be_wrong():
    """Pins the premise of the test above, so a future simplification fails."""
    part = bd.Box(30, 20, 10) - bd.Cylinder(3, 20)
    v, e, f = len(part.vertices()), len(part.edges()), len(part.faces())
    naive_genus = (2 - (v - e + f)) // 2
    assert naive_genus == 0, "the naive formula reports a through-hole as genus 0"


def test_genus_is_refused_for_multi_body_parts(backend: OcctBackend):
    two = bd.Box(5, 5, 5) + bd.Box(5, 5, 5).moved(bd.Location((20, 0, 0)))
    result = backend.genus(two)
    assert isinstance(result, Unsupported)
    assert "per body" in result.reason


# --------------------------------------------------------------------------
# relational primitives
# --------------------------------------------------------------------------


def test_min_distance_and_intersection(backend: OcctBackend):
    a = bd.Box(10, 10, 10)
    far = bd.Box(10, 10, 10).moved(bd.Location((20, 0, 0)))
    assert backend.min_distance(a, far).value == pytest.approx(10.0)

    half = bd.Box(10, 10, 10).moved(bd.Location((5, 0, 0)))
    assert backend.intersect_volume(a, half).value == pytest.approx(500.0)


def test_provenance_is_empty_on_this_tier(backend: OcctBackend):
    """triangles/distinct_normals describe a tessellation this tier does not
    have; emitting one would invite a meaningless cross-tier comparison."""
    assert backend.provenance(bd.Box(1, 1, 1)) == {}


def test_capabilities_include_topology(backend: OcctBackend):
    assert "topology_counts" in backend.capabilities()
    assert backend.kind == Tier.OCCT


# --------------------------------------------------------------------------
# the engine adapter
# --------------------------------------------------------------------------


def test_model_is_called_with_params(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text(
        "import build123d as bd\ndef make_part(w: float, h: float):\n    return bd.Box(w, w, h)\n"
    )
    source = PyCADSource(path=model, engine="build123d", params={"w": 4.0, "h": 5.0})
    shape = backend.build(source, tmp_path)
    assert not isinstance(shape, BuildError), shape
    assert backend.volume(shape).value == pytest.approx(80.0)


def test_a_signature_mismatch_explains_the_calling_convention(backend: OcctBackend, tmp_path: Path):
    """The convention is deliberately dumb — method(**params), no inspection —
    so the failure has to say so."""
    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part(spec):\n    return bd.Box(1, 1, 1)\n")
    result = backend.build(PyCADSource(path=model, engine="build123d", params={"w": 1}), tmp_path)
    assert isinstance(result, BuildError)
    assert "method(**params)" in (result.hint or "")


def test_a_missing_callable_lists_what_is_available(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef other():\n    return bd.Box(1, 1, 1)\n")
    result = backend.build(PyCADSource(path=model, engine="build123d", method="nope"), tmp_path)
    assert isinstance(result, BuildError)
    assert "other" in (result.hint or "")


def test_a_model_raising_is_a_build_error(backend: OcctBackend, tmp_path: Path):
    model = tmp_path / "m.py"
    model.write_text("def make_part():\n    raise ValueError('bad geometry')\n")
    result = backend.build(PyCADSource(path=model, engine="build123d"), tmp_path)
    assert isinstance(result, BuildError)
    assert "bad geometry" in result.message
