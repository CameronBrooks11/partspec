"""The OCCT backend, and the claim that one implementation serves both engines.

Fixtures are built in-process with build123d and CadQuery rather than loaded from
files, so these run wherever the occt extra is installed and assert against
closed-form geometry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import measured, refused

from partspec.backend import BuildError, Tier, Unsupported
from partspec.backends.occt import OcctBackend
from partspec.engines.pycad import PyCADSource, adopt, build

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
    """Replaced, not adjusted. The old fixture used the default `combine=True`,
    so its stack was already a single Compound and it stayed green against the
    bug below. It has to be a stack of *separate* Solids to test anything."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    w = cq.Workplane("XY").rect(20, 20, forConstruction=True).vertices().box(5, 5, 5, combine=False)
    assert len(w.vals()) == 4, "premise: four separate solids on the stack"

    adopted = adopt(w)
    assert not isinstance(adopted, BuildError)
    assert len(adopted.solids()) == 4, "`.val()` kept one and discarded three"
    assert adopted.volume == pytest.approx(500.0)


def test_a_single_body_workplane_is_unchanged():
    """The default combine=True path must not grow a Compound wrapper."""
    cq = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    adopted = adopt(cq.Workplane("XY").box(10, 10, 10))
    assert not isinstance(adopted, BuildError)
    assert adopted.volume == pytest.approx(1000.0)
    assert len(adopted.solids()) == 1


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
    assert measured(backend.volume(box)).value == pytest.approx(6000.0)
    assert measured(backend.area(box)).value == pytest.approx(2 * (200 + 600 + 300))
    assert measured(backend.bbox(box)).value == pytest.approx((10.0, 20.0, 30.0))
    com = measured(backend.center_of_mass(box))
    assert com.value == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert measured(backend.watertight(box)).value is True
    assert backend.solid_count(box).value == 1


def test_a_sealed_cavity_is_one_solid_with_one_void(backend: OcctBackend):
    """This tier was always right about the solid count — a block enclosing a
    sealed void is 1 solid and 2 shells. What was missing is that the void had
    no name, so a contract could not say "one block, one cavity" and the mesh
    tier's miscount had nothing to be checked against.

    The mesh tier reaches the same three numbers from triangle orientation; see
    `test_a_sealed_cavity_is_one_solid_not_two` there, and `evals/BASELINE.md`
    for the agent-loop failure that made this load-bearing.
    """
    block = bd.Box(20, 20, 20) - bd.Box(10, 10, 10)
    assert backend.solid_count(block).value == 1
    assert backend.cavities(block).value == 1
    assert measured(backend.genus(block)).value == 0
    assert measured(backend.volume(block)).value == pytest.approx(7000.0)


def test_a_plain_solid_has_no_cavities(backend: OcctBackend):
    assert backend.cavities(bd.Box(10, 10, 10)).value == 0


def test_a_cut_that_consumes_the_part_does_not_build():
    """`Box(s) - Box(2s)` is an ordinary slip and yields a non-null but empty
    Compound, which `IsNull()` does not catch. It used to be adopted as a
    legitimate artifact and then measured: bbox (0,0,0), area 0.0, watertight
    False, all exact, so a contract asserting those three passed green on a part
    that does not exist."""
    result = adopt(bd.Box(10, 10, 10) - bd.Box(20, 20, 20))
    assert isinstance(result, BuildError)
    assert "no geometry" in result.message


def test_geometry_without_faces_is_still_measurable(backend: OcctBackend):
    """The gate is "no vertices", not "no faces". A wire has no faces and no
    solids, and its bounding box and area are honest answers about it — refusing
    there would be the over-refusal D17 part 2 forbids."""
    wire = bd.Wire.make_circle(5)
    assert adopt(wire) is not None and not isinstance(adopt(wire), BuildError)
    assert measured(backend.bbox(wire)).value == pytest.approx((10.0, 10.0, 0.0))
    assert measured(backend.area(wire)).value == pytest.approx(0.0)
    assert measured(backend.watertight(wire)).value is False


def test_everything_on_this_tier_is_exact(backend: OcctBackend):
    """No tessellation anywhere, so nothing carries an error bound."""
    box = bd.Box(10, 20, 30)
    for measure in (backend.volume, backend.area, backend.bbox, backend.center_of_mass):
        result = measured(measure(box))
        assert result.exact and result.bounds is None


def test_curved_geometry_is_analytic_not_faceted(backend: OcctBackend):
    """The tier difference in one assertion: OCCT gives pi*r^2*h exactly, where
    the mesh tier would give an inscribed prism."""
    import math

    cyl = bd.Cylinder(radius=5, height=10)
    volume = measured(backend.volume(cyl))
    assert volume.value == pytest.approx(math.pi * 25 * 10, rel=1e-9)
    assert volume.exact


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


def test_a_topology_contract_is_answered_on_this_tier(tmp_path):
    """The counterpart of `test_a_tier_that_cannot_answer_says_which_one_can`:
    the identical check that reports `unsupported` on OpenSCAD passes here.

    That asymmetry, reachable from one contract, is the whole claim of having
    tiers — the check means the same thing on both, and says so where it cannot
    be evaluated rather than inventing an answer.
    """
    from partspec import Part, Status, Verdict, build123d, run

    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part():\n    return bd.Box(10, 20, 30)\n")

    p = Part("topo-box", build123d(model))
    p.topology(faces=6, edges=12, vertices=8)

    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.PASS
    assert check.measurement is not None
    assert check.measurement.value == (6, 12, 8)
    assert report.verdict is Verdict.PASS


def test_a_wrong_topology_claim_fails(tmp_path):
    from partspec import Part, Status, build123d, run

    model = tmp_path / "m.py"
    model.write_text("import build123d as bd\ndef make_part():\n    return bd.Box(10, 20, 30)\n")

    p = Part("topo-box", build123d(model)).topology(faces=7)
    report = run(p, out_dir=tmp_path)
    assert next(c for c in report.checks if c.id == "topology").status is Status.FAIL


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
    assert "per body" in refused(backend.genus(two)).reason


# --------------------------------------------------------------------------
# refusal — a shape that bounds no solid
# --------------------------------------------------------------------------


@pytest.fixture
def open_shell():
    """A box with one face removed: valid as a shape, but encloses nothing."""
    return bd.Shell(bd.Box(10, 10, 10).faces()[:-1])


def test_volume_is_refused_when_no_solid_is_bounded(backend: OcctBackend, open_shell):
    """`is_valid` does not catch this — an open shell reports True — and the raw
    `volume` is 0.0, which `volume(max=...)` would happily pass."""
    assert backend.is_valid(open_shell).value is True, "premise: validity does not catch it"
    assert open_shell.volume == 0.0, "premise: the raw property answers anyway"
    assert "bounds no solid" in refused(backend.volume(open_shell)).reason


def test_center_of_mass_is_refused_when_no_solid_is_bounded(backend: OcctBackend, open_shell):
    """build123d's `center()` still answers here, with the centroid of the
    *surface* — a different quantity under the same name."""
    assert pytest.approx(-1.0) == open_shell.center().Z, "premise: it answers, wrongly"
    assert "bounds no solid" in refused(backend.center_of_mass(open_shell)).reason


def test_area_and_solid_count_stay_answerable(backend: OcctBackend, open_shell):
    """Refuse the undefined, not the merely unusual: five faces of a 10mm cube
    have an area whatever they enclose, and `0 solids` is a true answer."""
    assert measured(backend.area(open_shell)).value == pytest.approx(500.0)
    assert backend.solid_count(open_shell).value == 0


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
    assert measured(backend.volume(shape)).value == pytest.approx(80.0)


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


def test_a_missing_engine_is_an_environment_fault_not_a_failing_part(tmp_path: Path):
    """An engine that will not import says nothing about the design.

    The case this guards is silent until it is fatal: `cadquery-ocp` and
    `cadquery-ocp-novtk` both install the same top-level `OCP/` package, neither
    pip nor uv detects the conflict, and when the novtk build wins CadQuery
    cannot import at all. This repo drops novtk with a `[tool.uv]` override, but
    that is a workspace setting and is not carried in wheel metadata -- a plain
    `pip install partspec[occt,cadquery]` reproduces it with no override in
    scope, so the guard has to be in the code.
    """
    model = tmp_path / "m.py"
    model.write_text("def part():\n    return None\n")
    result = build(PyCADSource(path=model, engine="definitely_not_installed", method="part"))
    assert isinstance(result, BuildError)
    assert result.origin == "environment", "not a verdict on the part"
    assert "not importable" in result.message


# --------------------------------------------------------------------------
# region materialization (#49)
# --------------------------------------------------------------------------


def test_region_solid_realises_the_canonical_polyhedron(backend: OcctBackend):
    """The materialized solid must match the region's own closed form — which is
    computed from the same vertex list the mesh tier triangulates. A true OCCT
    cylinder here would be a different (larger-by-zero, rounder) region than the
    other tier adjudicates, so exact volume agreement is the pin."""
    from partspec.region import box, cylinder

    b = backend.region_solid(box(min=(1, 2, 3), max=(4, 6, 9)))
    assert b.volume == pytest.approx(72.0, abs=1e-9)

    for axis in ("x", "y", "z"):
        r = cylinder(d=5, h=6, at=(1, 2, 3), axis=axis)
        s = backend.region_solid(r)
        assert s.volume == pytest.approx(r.volume(), abs=1e-9)


def test_intersect_volume_of_disjoint_shapes_is_zero_not_a_crash(backend: OcctBackend):
    """build123d's `&` returns None for disjoint shapes, and the naive
    `.volume` read crashed on it — found by this primitive's first caller,
    whose conforming case (an empty keep-out) is exactly two disjoint shapes."""
    a = bd.Box(2, 2, 2)
    b = bd.Pos(10, 10, 10) * bd.Box(2, 2, 2)
    m = measured(backend.intersect_volume(a, b))
    assert m.value == 0.0
    assert m.unit == "mm3"
