"""Regions: the declared data, its canonical materialization, and the contract surface.

Everything here is engine-free on purpose — `partspec.region` is stdlib-only
(SPEC-contract.md 1.1), so its geometry is verified with stdlib arithmetic: the
signed volume of the canonical triangulation against the closed form, and edge
pairing for watertightness. A region whose own polyhedron is open or inverted
would poison every keep_out/keep_in verdict built on it.
"""

from __future__ import annotations

import math

import pytest

from partspec import Part, openscad
from partspec.contract import GEOMETRY_KINDS
from partspec.region import BoxRegion, CylinderRegion, box, cylinder
from partspec.status import ContractError


def _signed_volume(vertices, faces) -> float:
    total = 0.0
    for a, b, c in faces:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = vertices[a], vertices[b], vertices[c]
        total += (
            ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        ) / 6.0
    return total


def _assert_closed_and_outward(vertices, faces) -> None:
    """Watertight with consistent winding: every directed edge appears exactly
    once, and so does its reverse. Positive signed volume then means outward."""
    directed: set[tuple[int, int]] = set()
    for a, b, c in faces:
        for e in ((a, b), (b, c), (c, a)):
            assert e not in directed, f"edge {e} appears twice with the same orientation"
            directed.add(e)
    for e in directed:
        assert (e[1], e[0]) in directed, f"edge {e} has no opposing twin: the surface is open"


# --------------------------------------------------------------------------
# the canonical polyhedron
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "region",
    [
        box(min=(1, 2, 3), max=(4, 6, 9)),
        cylinder(d=5, h=6, at=(1, 2, 3), axis="x"),
        cylinder(d=5, h=6, at=(1, 2, 3), axis="y"),
        cylinder(d=5, h=6, at=(1, 2, 3), axis="z"),
        cylinder(d=5, h=6, at=(-1, -2, -3), axis="z", segments=16),
    ],
)
def test_canonical_mesh_is_closed_outward_and_matches_the_closed_form(region):
    vertices, faces = region.mesh()
    _assert_closed_and_outward(vertices, faces)
    assert _signed_volume(vertices, faces) == pytest.approx(region.volume(), abs=1e-9)
    assert region.volume() > 0


def test_cylinder_polygon_circumscribes_the_declared_circle():
    """Every flat's distance from the axis is >= the declared radius, so the
    prism contains the declared cylinder — which is what makes an 'empty'
    verdict on it an earned claim about the circle it stands for."""
    r = cylinder(d=5, h=6, at=(0, 0, 0), segments=64)
    poly = [(x, y) for x, y, _ in r.base_polygon()]
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        flat_distance = abs(x1 * y2 - x2 * y1) / math.hypot(x2 - x1, y2 - y1)
        assert flat_distance >= 2.5 - 1e-12


def test_cylinder_volume_exceeds_the_true_cylinder_by_the_documented_ratio():
    """The over-approximation is sec(pi/n)^2-ish in area, ~0.24% at n=64. Pinned
    so a silent switch to an inscribed polygon — which would let material hide
    between polygon and circle — cannot pass."""
    r = cylinder(d=10, h=10, segments=64)
    true_cylinder = math.pi * 25 * 10
    assert r.volume() > true_cylinder
    assert r.volume() / true_cylinder == pytest.approx(1.0, abs=0.005)


def test_expand_contains_the_original():
    r = cylinder(d=5, h=6, at=(1, 2, 3), axis="y")
    o = r.expand(1.0)
    assert o.d == 7.0 and o.h == 8.0 and o.segments == r.segments and o.axis == r.axis
    assert o.at == (1, 1, 3)  # shifted -1 along the axis so both ends grow
    b = box(min=(0, 0, 0), max=(2, 2, 2)).expand(0.5)
    assert b.min == (-0.5, -0.5, -0.5) and b.max == (2.5, 2.5, 2.5)


def test_region_json_is_self_describing():
    assert box(min=(0, 0, 0), max=(1, 2, 3)).to_json() == {
        "shape": "box",
        "min": [0.0, 0.0, 0.0],
        "max": [1.0, 2.0, 3.0],
    }
    assert cylinder(d=5, h=6, at=(1, 2, 3), axis="x").to_json() == {
        "shape": "cylinder",
        "d": 5,
        "h": 6,
        "at": [1.0, 2.0, 3.0],
        "axis": "x",
        "segments": 64,
    }


# --------------------------------------------------------------------------
# declaration refusals — a region that encloses nothing can claim nothing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda: box(min=(0, 0, 0), max=(1, 0, 1)), "strictly below"),
        (lambda: box(min=(0, 0, 0), max=(1, -1, 1)), "strictly below"),
        (lambda: box(min=(0, 0), max=(1, 1)), "3-component"),  # type: ignore[arg-type]
        (lambda: box(min=(0, 0, float("nan")), max=(1, 1, 1)), "not a number"),
        (lambda: cylinder(d=0, h=5), "d > 0"),
        (lambda: cylinder(d=5, h=-1), "h > 0"),
        (lambda: cylinder(d=float("inf"), h=5), "not a number"),
        (lambda: cylinder(d=5, h=5, axis="w"), "axis"),
        (lambda: cylinder(d=5, h=5, axis=(0, 0, 1)), "axis"),  # type: ignore[arg-type]
        (lambda: cylinder(d=5, h=5, segments=4), "at least 8"),
    ],
)
def test_degenerate_regions_are_refused_at_declaration(build, match):
    with pytest.raises(ContractError, match=match):
        build()


@pytest.mark.parametrize(
    "axis",
    [
        [0, 0, 1],  # the list form -- the filed case
        {"z": 1},
        {0, 1},
        bytearray(b"z"),
    ],
)
def test_an_unhashable_axis_gets_partspecs_own_message(axis):
    """#199: the guard died INSIDE itself rather than at it.

    `self.axis not in _AXES` hashes its operand, so an unhashable value raised
    `TypeError: cannot use 'list' as a dict key` — partspec's own
    implementation detail, that `_AXES` happens to be a dict, offered as the
    diagnosis for a user error one keystroke away from the one #193 exists to
    document. Two fleet agents wrote `axis=(0, 0, 1)`; a tuple is hashable and
    reached the message, a list is not and did not.

    Same exit code either way (4), so nothing was ever misclassified — this is
    entirely about the sentence the reader gets. The parametrisation covers
    every unhashable builtin a plausible typo produces, not just the list,
    because the hole is the missing type check and not the list specifically.
    """
    with pytest.raises(ContractError, match="must be the string"):
        cylinder(d=5, h=5, axis=axis)


# --------------------------------------------------------------------------
# contract surface
# --------------------------------------------------------------------------


def _part() -> Part:
    return Part("p", openscad("a.scad"))


def test_keep_out_and_keep_in_declare_region_and_shell():
    p = _part()
    p.keep_out(cylinder(d=5, h=8, at=(10, 10, -1)), shell=2.0)
    p.keep_in(box(min=(0, 0, 0), max=(1, 1, 1)), shell=1.0, id="boss")
    out, kin = p.checks
    assert (out.kind, out.id, out.shell) == ("keep_out", "keep_out", 2.0)
    assert isinstance(out.region, CylinderRegion)
    assert (kin.kind, kin.id, kin.shell) == ("keep_in", "boss", 1.0)
    assert isinstance(kin.region, BoxRegion)
    assert out.limit is None and out.expr is None


def test_region_kinds_gate_on_the_region_primitive():
    assert GEOMETRY_KINDS["keep_out"] == GEOMETRY_KINDS["keep_in"] == "region_solid"


def test_shell_is_mandatory_and_must_be_positive():
    """The shell is what makes an absent feature fail rather than vacuously
    pass, so there is no default and no zero."""
    p = _part()
    with pytest.raises(TypeError):
        p.keep_out(box(min=(0, 0, 0), max=(1, 1, 1)))  # type: ignore[call-arg]
    for bad in (0, -1.0, float("nan")):
        with pytest.raises(ContractError, match="shell > 0"):
            p.keep_out(box(min=(0, 0, 0), max=(1, 1, 1)), shell=bad)


def test_a_non_region_is_refused_with_the_path_to_the_right_one():
    with pytest.raises(ContractError, match=r"partspec\.region"):
        _part().keep_out((0, 0, 0, 1, 1, 1), shell=1.0)  # type: ignore[arg-type]


def test_two_regions_of_one_kind_need_distinct_ids():
    p = _part()
    p.keep_out(box(min=(0, 0, 0), max=(1, 1, 1)), shell=1.0)
    with pytest.raises(ContractError, match="duplicate check id"):
        p.keep_out(box(min=(2, 2, 2), max=(3, 3, 3)), shell=1.0)
