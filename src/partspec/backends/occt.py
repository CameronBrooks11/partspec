"""The OCCT backend: measures a BREP shape.

Serves **build123d and CadQuery from one implementation** (D3). Verified: both
expose a `TopoDS_Shape` from the same OCP module, and a CadQuery result is
adopted by rewrapping the handle — no conversion, no copy, no loss. There is no
second code path to keep in sync, which is why CadQuery costs an afternoon
rather than a parallel backend.

This is the tier where topology is real. `topology_counts` is answered here and
refused on mesh, and that asymmetry is the whole point of having tiers.

Spec: SPEC-backend.md section 4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..backend import BuildError, Tier, Unsupported, Vec3
from ..engines import pycad
from ..status import Measurement

__all__ = ["CAPABILITIES", "OcctBackend"]

CAPABILITIES = frozenset(
    {
        "bbox",
        "volume",
        "area",
        "center_of_mass",
        "is_valid",
        "watertight",
        "solid_count",
        "cavities",
        "genus",
        "topology_counts",
        "triangles",
        "min_distance",
        "intersect_volume",
        "region_solid",
        "bores",
        "bore_table",
        "blend_radii",
    }
)


_EMPTY_REASON = "this shape contains no geometry, so there is nothing to measure"


def _radial(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    """The outward radial vector from a cylinder's axis to a surface point."""
    rel = tuple(p - o for p, o in zip(point, origin, strict=True))
    along = sum(r * d for r, d in zip(rel, direction, strict=True))
    return tuple(r - along * d for r, d in zip(rel, direction, strict=True))  # type: ignore[return-value]


def _axis_key(
    origin: tuple[float, float, float], direction: tuple[float, float, float], radius: float
) -> tuple[tuple, tuple[float, ...]]:
    """A grouping key identifying (axis line, radius) up to representation,
    plus the canonical direction it chose.

    Two faces of one bore can carry the axis with opposite directions and
    different origin points along the same line; the key must not care. The
    direction is sign-normalised on its first non-negligible component, and the
    origin is replaced by the axis line's foot of perpendicular from the world
    origin — the one point every representation of the line agrees on. Rounding
    to 6 decimals absorbs kernel noise; two genuinely distinct axes closer than
    a micrometre are a modelling pathology this deliberately merges rather than
    guesses about.
    """
    # The sign threshold matches the rounding quantum below: deciding the flip
    # on a component the rounding then erases would give two representations
    # of one axis line different keys, splitting a bore's faces into sub-2π
    # groups and reporting a hole that exists as absent.
    canonical = direction
    if next((c for c in canonical if abs(c) > 5e-7), 1.0) < 0:
        canonical = tuple(-c for c in canonical)  # type: ignore[assignment]
    along = sum(o * d for o, d in zip(origin, canonical, strict=True))
    foot = tuple(o - along * d for o, d in zip(origin, canonical, strict=True))
    key = (
        tuple(round(c, 6) for c in canonical),
        tuple(round(c, 6) for c in foot),
        round(radius, 6),
    )
    return key, canonical


def _axial_clusters(spans: list[tuple]) -> list[list[tuple]]:
    """Group spans `(lo, hi, ...)` into contiguous axial clusters.

    Faces whose axial spans touch or overlap belong to one bore (a seam-split
    cylinder, a bore interrupted by nothing); a gap along the axis separates
    two bores that merely share an axis line — the clevis's two lugs.
    """
    clusters: list[list[tuple]] = []
    hi: float | None = None
    for span in sorted(spans, key=lambda s: (s[0], s[1])):
        if hi is None or span[0] > hi + 1e-6:
            clusters.append([span])
            hi = span[1]
        else:
            clusters[-1].append(span)
            hi = max(hi, span[1])
    return clusters


def _empty(a: Any) -> bool:
    """No sub-shapes at all — an empty compound, not merely a shape without
    faces. A Wire or an Edge has vertices and is honestly measurable."""
    return not a.vertices()


class OcctBackend:
    """Measures an OCCT BREP shape, from either Python engine."""

    kind = Tier.OCCT

    def __init__(self, engine: str = "build123d") -> None:
        self.engine = engine
        self._version: str | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def engine_version(self) -> str:
        if self._version is None:
            self._version = pycad.version(self.engine)
        return self._version

    def build(self, source: pycad.PyCADSource, out_dir: Path) -> Any | BuildError:
        """Build the part. `out_dir` is unused — nothing is exported to measure.

        The mesh tier has to round-trip through a file because OpenSCAD is a
        separate process. Here the shape is already in memory, and exporting it
        only to read it back would introduce the float32 quantisation this tier
        does not otherwise suffer.
        """
        return pycad.build(source)

    def capabilities(self) -> frozenset[str]:
        return CAPABILITIES

    def provenance(self, a: Any) -> dict[str, Any]:
        """Empty on this tier.

        `triangles` and `distinct_normals` describe a tessellation, and this tier
        does not have one — the shape is analytic. Emitting a tessellation-shaped
        number here would invite a comparison between tiers that does not mean
        anything.
        """
        return {}

    # -- the primitives ----------------------------------------------------

    def bbox(self, a: Any) -> Measurement | Unsupported:
        """Refused for a shape with no geometry in it.

        An empty compound is not null, so `adopt` used to pass it through and
        this returned `(0.0, 0.0, 0.0)` flagged exact -- a number that satisfies
        `envelope(max=...)` for a part that does not exist. `adopt` now rejects
        it at the boundary; this is the same precondition stated where the
        measurement is taken, so the library path is closed too.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        size = a.bounding_box().size
        return Measurement(
            (float(size.X), float(size.Y), float(size.Z)), "mm", exact=True, axes=("x", "y", "z")
        )

    def volume(self, a: Any) -> Measurement | Unsupported:
        """Refused for a shape that bounds no solid.

        The mesh tier's version of this returned a plausible wrong number; here
        it returns a plausible wrong *zero*. An open shell and a bare face both
        report `volume 0.0` while `is_valid` is True, so validity does not catch
        it — and `volume(max=...)` on a shape containing no material would pass.
        """
        if not a.solids():
            return Unsupported(
                "this shape bounds no solid, so it has no volume (check solid_count first)"
            )
        return Measurement(float(a.volume), "mm3", exact=True)

    def area(self, a: Any) -> Measurement | Unsupported:
        """Total surface area. Total, like the mesh tier's — defined for a face
        and a shell as much as for a solid, and so deliberately not gated on
        `solids()`. Gated only on there being geometry at all: `area(max=...)`
        would otherwise pass on an empty compound's 0.0."""
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        return Measurement(float(a.area), "mm2", exact=True)

    def center_of_mass(self, a: Any) -> Measurement | Unsupported:
        """Refused on the same precondition as `volume`, and for a sharper
        reason: on a shape with no solid, build123d's `center()` still answers,
        but with the centroid of the *surface* — a different quantity under the
        same name."""
        if not a.solids():
            return Unsupported(
                "this shape bounds no solid, so it has no centre of mass (check solid_count first)"
            )
        c = a.center()
        return Measurement(
            (float(c.X), float(c.Y), float(c.Z)), "mm", exact=True, axes=("x", "y", "z")
        )

    def is_valid(self, a: Any) -> Measurement:
        """`is_valid` is a **property** on build123d and a **method**
        (`isValid()`) on CadQuery. Adoption normalises the object, so only the
        build123d spelling is needed here — but the divergence is the reason the
        adopt shim exists at all, and calling it as a method here was a real bug
        caught by a test on the adjacent path."""
        return Measurement(bool(a.is_valid), "bool", exact=True)

    def watertight(self, a: Any) -> Measurement | Unsupported:
        """`is_manifold` on a BREP: every edge bounded by exactly two faces.

        Vacuously true of a shape with no edges, which is why the emptiness gate
        has to sit in front of it rather than trusting the answer.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        return Measurement(bool(a.is_manifold), "bool", exact=True)

    def solid_count(self, a: Any) -> Measurement:
        return Measurement(len(a.solids()), "count", exact=True)

    def cavities(self, a: Any) -> Measurement:
        """Sealed internal voids.

        A solid is bounded by one outer shell plus one shell per enclosed void,
        so the difference is the void count. This tier has always counted solids
        correctly — a block with a sealed cavity is 1 solid and 2 shells — and
        the quantity was simply never exposed. The mesh tier reaches the same
        two numbers from triangle orientation.
        """
        return Measurement(max(len(a.shells()) - len(a.solids()), 0), "count", exact=True)

    def genus(self, a: Any) -> Measurement | Unsupported:
        """Through-holes, via the Euler-Poincare formula.

            V - E + 2F - W = 2(S - G)

        The naive `V - E + F` is **wrong on a BREP** and quietly so: OCCT faces
        carry inner wires, so a face with a hole is an annulus rather than a
        disc. Measured, the naive form reports a box with a through-hole as
        genus 0 and a box with a *blind* hole as genus -1. Including the wire
        count fixes both — verified against a box (0), one and two through-holes
        (1, 2), a blind hole (0) and a tube (1).

        Refused for multi-body parts for the same reason as the mesh tier: genus
        is defined per body.
        """
        solids = a.solids()
        if len(solids) != 1:
            return Unsupported(
                f"genus is defined per body; this part has {len(solids)} solids "
                f"(check solid_count first, or split the part)"
            )
        v, e, f, w = len(a.vertices()), len(a.edges()), len(a.faces()), len(a.wires())
        shells = max(len(a.shells()), 1)
        genus = shells - (v - e + 2 * f - w) / 2
        return Measurement(int(genus), "count", exact=True)

    def topology_counts(self, a: Any) -> Measurement:
        """Real engineering topology — the reason this tier exists.

        On a mesh these would be triangle counts wearing the wrong name, so the
        mesh backend refuses them. Here they are faces, edges and vertices as
        modelled.
        """
        counts = (len(a.faces()), len(a.edges()), len(a.vertices()))
        return Measurement(counts, "count", exact=True, axes=("faces", "edges", "vertices"))

    def triangles(self, a: Any) -> Any:
        return a.tessellate(0.1)

    def min_distance(self, a: Any, b: Any) -> Measurement:
        return Measurement(float(a.distance_to(b)), "mm", exact=True)

    def intersect_volume(self, a: Any, b: Any) -> Measurement:
        """Volume of the boolean common.

        The empty case is explicit because build123d's `&` returns `None` for
        disjoint shapes rather than an empty compound — found by this
        primitive's first caller (keep_out, whose conforming case is exactly
        "these two shapes are disjoint"); `(a & b).volume` crashed on it.
        """
        common = a & b
        return Measurement(0.0 if common is None else float(common.volume), "mm3", exact=True)

    def region_solid(self, region: Any) -> Any:
        """Materialize a declared region as a native solid.

        A cylinder region is extruded from the same polygon vertex list the mesh
        tier triangulates (SPEC-contract.md 4.4): the two tiers must adjudicate
        the identical polyhedron, so a true OCCT cylinder — available here —
        is deliberately not used.
        """
        import build123d as bd

        from ..region import BoxRegion

        if isinstance(region, BoxRegion):
            (x0, y0, z0), (x1, y1, z1) = region.min, region.max
            return bd.Pos(x0, y0, z0) * bd.Solid.make_box(x1 - x0, y1 - y0, z1 - z0)
        points = [bd.Vector(*p) for p in region.base_polygon()]
        face = bd.Face(bd.Wire.make_polygon(points, close=True))
        return bd.extrude(face, amount=region.h, dir=region.axis_vector())

    def bore_table(self, a: Any) -> list[dict[str, Any]] | Unsupported:
        """Every bore with its geometry: `{"d", "direction", "center"}`.

        The raw data `bores` summarises and `bolt_circle` positions against
        (SPEC-contract.md 4.6): `direction` is the canonical unit axis (sign
        normalised, so parallel bores compare equal), `center` the midpoint of
        the bore's axial span on its axis — a real point of the feature, where
        the axis-line foot would be an artifact of where the world origin
        happens to sit. Like `triangles` and `region_solid`, this returns raw
        data rather than a Measurement; one detection implementation serves
        every consumer, so the bore definition cannot fork.
        """
        import math

        clusters = self._cylinder_clusters(a)
        if isinstance(clusters, Unsupported):
            return clusters
        table = [
            {"d": c["radius"] * 2, "direction": c["direction"], "center": c["center"]}
            for c in clusters
            if c["inward"] and c["wrap"] >= 2 * math.pi - 1e-6
        ]
        table.sort(key=lambda bore: -bore["d"])
        return table

    def _cylinder_clusters(self, a: Any) -> list[dict[str, Any]] | Unsupported:
        """Every cylindrical surface cluster: one entry per (axis line, radius,
        orientation, contiguous axial span), with its summed angular wrap.

        The single detection implementation beneath `bore_table` (inward,
        full-wrap clusters) and `blend_radii` (partial-wrap clusters): both
        kinds read one walk, so their definitions cannot fork.
        """
        if _empty(a):
            return Unsupported(_EMPTY_REASON)
        from build123d import GeomType
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepTools import BRepTools  # type: ignore[attr-defined]

        # (key, inward) -> list of (axial_lo, axial_hi, extent, radius, dir, foot)
        groups: dict[tuple, list[tuple]] = {}
        for face in a.faces().filter_by(GeomType.CYLINDER):
            # BRepAdaptor, not the raw Geom surface: a planar cut part-way
            # around a cylinder (a slit clamp, an obround slot) wraps the
            # surface in Geom_RectangularTrimmedSurface, which the GeomType
            # filter sees through and the raw surface object cannot answer
            # Cylinder() on — the mismatch crashed on ordinary geometry.
            cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
            radius = float(cylinder.Radius())
            axis_location, axis_direction = cylinder.Axis().Location(), cylinder.Axis().Direction()
            origin = (axis_location.X(), axis_location.Y(), axis_location.Z())
            direction = (axis_direction.X(), axis_direction.Y(), axis_direction.Z())

            umin, umax, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
            surface_point = face.position_at(0.5, 0.5)  # u, v are normalised here
            point = (float(surface_point.X), float(surface_point.Y), float(surface_point.Z))
            normal_vec = face.normal_at(surface_point)
            normal = (float(normal_vec.X), float(normal_vec.Y), float(normal_vec.Z))
            radial = _radial(point, origin, direction)
            inward = sum(n * r for n, r in zip(normal, radial, strict=True)) < 0

            key, canonical = _axis_key(origin, direction, radius)
            # The v parameter measures axial distance from the face's own
            # surface origin along its own direction; both vary by face, so
            # spans are re-expressed on the canonical axis before comparison.
            base = sum(o * d for o, d in zip(origin, canonical, strict=True))
            sign = sum(d0 * d for d0, d in zip(direction, canonical, strict=True))
            ends = sorted((base + sign * vmin, base + sign * vmax))
            foot = tuple(o - base * d for o, d in zip(origin, canonical, strict=True))
            groups.setdefault((key, inward), []).append(
                (ends[0], ends[1], umax - umin, radius, canonical, foot)
            )

        clusters: list[dict[str, Any]] = []
        for (_, inward), spans in groups.items():
            for cluster in _axial_clusters(spans):
                # The rounded key groups; the surface parameter is the
                # measurement. Reporting the key's quantised radius flipped
                # verdicts at tolerances below its 1e-6 quantum — a false
                # pass with the true value appearing nowhere in the report.
                _, _, _, radius, canonical, foot = cluster[0]
                mid = (min(e[0] for e in cluster) + max(e[1] for e in cluster)) / 2
                clusters.append(
                    {
                        "radius": radius,
                        "direction": canonical,
                        "center": tuple(f + mid * d for f, d in zip(foot, canonical, strict=True)),
                        "inward": inward,
                        "wrap": sum(entry[2] for entry in cluster),
                    }
                )
        return clusters

    def blend_radii(self, a: Any) -> Measurement | Unsupported:
        """Radii of every partial-wrap cylindrical surface, sorted ascending.

        The blend candidates a `fillet_radius` claim ranges over
        (SPEC-contract.md 4.7). Partial wrap is the definition: a full wrap is
        a bore or a boss, whose radii are `hole_diameter`'s business, and the
        clustering shared with `bore_table` is what stops a seam-split bore's
        two half faces from masquerading as blends. Both orientations count —
        a convex-corner round and a concave-corner fillet are the same claim —
        and so do slot ends and grooves, deliberately: nothing at the surface
        level distinguishes them from fillets, and for the machinability claim
        this kind exists for they constrain the tool identically.
        """
        import math

        clusters = self._cylinder_clusters(a)
        if isinstance(clusters, Unsupported):
            return clusters
        radii = sorted(c["radius"] for c in clusters if c["wrap"] < 2 * math.pi - 1e-6)
        return Measurement(
            tuple(radii),
            "mm",
            exact=True,
            axes=tuple(f"blend_{i + 1}" for i in range(len(radii))),
        )

    def bores(self, a: Any) -> Measurement | Unsupported:
        """Diameters of every cylindrical bore on the shape, sorted descending.

        A bore is a set of cylindrical faces sharing one axis line, one radius
        and one **contiguous axial span**, that (a) face **inward** — the
        surface normal points toward the axis, so material surrounds the void;
        a boss is the same surface facing out — and (b) wrap the **full
        circle**: angular extents summing to 2π. Full-wrap is what keeps a
        concave fillet (a quarter-wrap) and a half-round groove (a half-wrap)
        from being counted as holes they are not. Coaxial groups of different
        radius stay distinct, so a counterbore reports one bore per diameter —
        each portion is a real seat with a real drawing callout. The axial-span
        clustering is what makes two aligned holes through two clevis lugs
        count as the two bores the drawing calls out, not one.

        Diameters are read from the BREP surface parameter, so they are exact:
        the predicted first exercise of `approximate` (POST-V0 §4) did not
        materialise, because a modelled cylinder's radius is a parameter, not
        an estimate.
        """
        table = self.bore_table(a)
        if isinstance(table, Unsupported):
            return table
        diameters = [bore["d"] for bore in table]
        return Measurement(
            tuple(diameters),
            "mm",
            exact=True,
            axes=tuple(f"bore_{i + 1}" for i in range(len(diameters))),
        )

    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> Unsupported:
        """Not implemented on this tier yet.

        `find_intersection_points` exists in build123d, but no v0 check calls it
        and it serves min_wall, which is post-v0. Declared absent rather than
        written untested.
        """
        return Unsupported("raycast is not implemented on the occt tier yet")
