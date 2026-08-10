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


def test_an_empty_compound_is_a_build_error_not_an_assert(tmp_path):
    """#128: build123d's `.wrapped` asserts on `Compound()` with no children,
    and the AssertionError escaped adopt as a traceback with empty stdout —
    for measure and render alike, both of which promise an identity artifact
    on any failure after the target resolves."""
    result = adopt(bd.Compound())
    assert isinstance(result, BuildError)
    assert "no geometry" in result.message

    # Through the verb: the artifact, never the shrug (the #47/#103 shape).
    import json

    from partspec.cli import main

    (tmp_path / "m.py").write_text(
        "from build123d import Compound\n\n\ndef make_part():\n    return Compound()\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["measure", f"{tmp_path / 'spec.py'}:make"])
    assert code == 4
    doc = json.loads(out.getvalue())
    assert doc["part"]["id"] == "subject"
    assert "no geometry" in doc["error"]


def test_a_none_handle_is_named_not_misdescribed():
    """PR #133 review, F4: a wrapper whose .wrapped is None (CadQuery can
    produce one) must get the no-geometry message, not the misleading
    'not a build123d or CadQuery shape'."""

    class _Hollow:
        wrapped = None

    result = adopt(_Hollow())
    assert isinstance(result, BuildError)
    assert "no underlying handle" in result.message


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
    assert measured(backend.cavities(block)).value == 1
    assert measured(backend.genus(block)).value == 0
    assert measured(backend.volume(block)).value == pytest.approx(7000.0)


def test_a_plain_solid_has_no_cavities(backend: OcctBackend):
    assert measured(backend.cavities(bd.Box(10, 10, 10))).value == 0


@pytest.mark.parametrize(
    ("name", "builder", "cavities"),
    [
        ("an open shell alone", lambda: bd.Shell(bd.Box(10, 10, 10).faces()[1:]), 0),
        (
            "a plain solid beside a stray sheet body",
            lambda: bd.Compound(
                children=[
                    bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces()[1:]),
                ]
            ),
            0,
        ),
        (
            "a cavity solid beside a stray sheet body",
            lambda: bd.Compound(
                children=[
                    bd.Box(20, 20, 20) - bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * bd.Shell(bd.Box(10, 10, 10).faces()[1:]),
                ]
            ),
            1,
        ),
        (
            "two cavity solids",
            lambda: bd.Compound(
                children=[
                    bd.Box(20, 20, 20) - bd.Box(10, 10, 10),
                    bd.Pos(60, 0, 0) * (bd.Box(20, 20, 20) - bd.Box(10, 10, 10)),
                ]
            ),
            2,
        ),
    ],
)
def test_a_stray_shell_is_not_a_sealed_void(
    backend: OcctBackend, name: str, builder, cavities: int
):
    """The deslop audit's headline defect, and the deeper version its own
    review found. `cavities` was a global `shells - solids`, so an OPEN
    shell answered 1 - 0 = 1 and the tool certified `cavities = 1, exact`,
    `verdict: pass`, exit 0 on a shape with no material at all.

    The first fix gated on `not a.solids()` and was still wrong: the formula
    assumes every shell belongs to a solid, and nothing enforces that. One
    plain block beside a stray sheet body is 1 solid and 2 shells, so the
    same false pass came straight back through the CLI on a part that does
    build. Counting each solid's own shells minus its outer one is right by
    construction for every arrangement here, and needs no precondition.
    """
    shape = builder()
    assert measured(backend.cavities(shape)).value == cavities, name


def test_the_two_tiers_agree_about_a_shape_with_no_material(backend: OcctBackend):
    """The other half of the defect, which the first fix moved rather than
    closed: OCCT refused where the mesh tier answered 0, so one contract
    still adjudicated two ways depending on the engine. Zero is the honest
    answer — a shape with no solid encloses no sealed void — and both tiers
    give it now."""
    trimesh = pytest.importorskip("trimesh", reason="mesh extra not installed")
    import tempfile
    from pathlib import Path

    from partspec.backends.mesh import MeshBackend

    shell = bd.Shell(bd.Box(10, 10, 10).faces()[1:])
    assert measured(backend.solid_count(shell)).value == 0, "the fixture really has no solid"
    assert measured(backend.cavities(shell)).value == 0

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shell.stl"
        bd.export_stl(shell, str(path))
        mesh = trimesh.load(str(path))
        assert measured(MeshBackend().cavities(mesh)).value == 0, "and the mesh tier agrees"


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
    from partspec import Part, Status, Verdict, build123d
    from partspec.runner import run

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
    from partspec import Part, Status, build123d
    from partspec.runner import run

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


# --------------------------------------------------------------------------
# bore enumeration (#80)
# --------------------------------------------------------------------------


def _plate_with_features():
    """60x40x10 plate: two Ø8 through bores, one Ø12 counterbore over the
    first, a Ø6 boss on top, a Ø5 blind hole. Every classification branch of
    SPEC-contract.md 4.5 on one part."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    plate = Box(60, 40, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    return (
        plate
        - (Location((15, 20, -1)) * Cylinder(4, 12, align=a))
        - (Location((30, 20, -1)) * Cylinder(4, 12, align=a))
        - (Location((15, 20, 6)) * Cylinder(6, 5, align=a))
        + (Location((50, 20, 10)) * Cylinder(3, 5, align=a))
        - (Location((50, 8, 4)) * Cylinder(2.5, 7, align=a))
    )


def test_bores_enumerates_bores_and_only_bores(backend: OcctBackend):
    m = measured(backend.bores(_plate_with_features()))
    assert m.value == (12.0, 8.0, 8.0, 5.0), "counterbore per diameter; boss Ø6 absent"
    assert m.unit == "mm" and m.exact
    assert m.axes == ("bore_1", "bore_2", "bore_3", "bore_4")


def test_a_concave_fillet_is_not_a_bore(backend: OcctBackend):
    """The fillet's surface is inward-facing and cylindrical — everything a
    bore is except full-wrap. Counting it would report a hole that a drill
    never made."""
    from build123d import Align, Box, Location

    step = Box(20, 20, 20, align=(Align.MIN, Align.MIN, Align.MIN)) - Location((10, -1, 10)) * Box(
        11, 22, 11, align=(Align.MIN, Align.MIN, Align.MIN)
    )
    edges = [
        e for e in step.edges() if abs(e.center().X - 10) < 1e-6 and abs(e.center().Z - 10) < 1e-6
    ]
    filleted = step.fillet(radius=3, edge_list=edges)
    assert measured(backend.bores(filleted)).value == ()


def test_two_clevis_lugs_carry_two_bores(backend: OcctBackend):
    """Same axis, same radius, disjoint axial spans: the drawing says 2x Ø8
    and so must the enumeration — an (axis, radius) key alone merges them."""
    from build123d import Align, Box, Cylinder, Location

    lugs = Box(5, 30, 30, align=(Align.MIN, Align.MIN, Align.MIN)) + Location((20, 0, 0)) * Box(
        5, 30, 30, align=(Align.MIN, Align.MIN, Align.MIN)
    )
    clevis = lugs - Location((12.5, 15, 15)) * Cylinder(4, 60, rotation=(0, 90, 0))
    assert measured(backend.bores(clevis)).value == (8.0, 8.0)


def test_bores_refuses_an_empty_shape(backend: OcctBackend):
    from build123d import Compound

    refused(backend.bores(Compound()))


def test_a_trimmed_cylindrical_face_does_not_crash_the_enumeration(backend: OcctBackend):
    """A planar cut part-way around a cylinder — a slit clamp, an obround
    slot — wraps the surface in Geom_RectangularTrimmedSurface. The GeomType
    filter sees through the wrapper; the raw-surface extractor did not, and
    `bores` raised AttributeError on ordinary geometry (PR #87 review
    blocker). The slit clamp's severed bore also must not count as full-wrap."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    clamp = (
        Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN))
        - (Location((15, 15, -1)) * Cylinder(4, 12, align=a))
        - (Location((15, 27, -1)) * Box(2, 26, 12, align=a))
    )
    m = measured(backend.bores(clamp))
    assert 8.0 not in m.value, "a slit bore is not a full circle a pin can bear on"


def test_an_obround_slot_is_not_a_bore(backend: OcctBackend):
    """Two half-cylinders joined by planes: each wraps half the circle on its
    own axis, so neither reaches full-wrap. Also pins the 2π threshold — a
    mutant accepting half-wraps counts this slot twice."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    slot = (
        Location((10, 15, -1)) * Cylinder(4, 12, align=a)
        + Location((20, 15, -1)) * Cylinder(4, 12, align=a)
        + Location((15, 15, -1)) * Box(10, 8, 12, align=a)
    )
    part = Box(40, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN)) - slot
    assert measured(backend.bores(part)).value == ()


def test_the_reported_diameter_is_the_surface_parameter_not_the_grouping_key(
    backend: OcctBackend,
):
    """Grouping rounds to 1e-6 to absorb kernel noise; the *measurement* must
    be the un-rounded radius. Reporting the key produced a demonstrated false
    pass at tol below the quantum, with the true value nowhere in the report."""
    from build123d import Align, Box, Cylinder, Location

    a = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Box(30, 30, 10, align=(Align.MIN, Align.MIN, Align.MIN)) - (
        Location((15, 15, -1)) * Cylinder(4.0000004, 12, align=a)
    )
    m = measured(backend.bores(part))
    assert m.value == (8.0000008,), "the exact modelled diameter, not its quantisation"


def test_axis_sign_normalisation_agrees_with_its_own_rounding():
    """The flip threshold must sit at the rounding quantum: deciding the sign
    on a component the rounding then erases keys one axis line two ways,
    splitting a bore into sub-2pi groups — a hole that exists, reported
    absent."""
    from partspec.backends.occt import _axis_key

    noisy_pos, _ = _axis_key((0, 0, 0), (2e-9, -1.0, 0.0), 4.0)
    noisy_neg, _ = _axis_key((0, 0, 0), (-2e-9, -1.0, 0.0), 4.0)
    clean, _ = _axis_key((0, 0, 0), (0.0, -1.0, 0.0), 4.0)
    assert noisy_pos == noisy_neg == clean


def test_the_grouping_quantum_is_a_micrometre():
    """1e-6 rounding absorbs kernel noise without merging real features: radii
    a nanometre apart share a key, radii ten micrometres apart do not."""
    from partspec.backends.occt import _axis_key

    same_a, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.0)
    same_b, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.00000001)
    distinct, _ = _axis_key((0, 0, 0), (0, 0, 1.0), 4.00001)
    assert same_a == same_b
    assert same_a != distinct
