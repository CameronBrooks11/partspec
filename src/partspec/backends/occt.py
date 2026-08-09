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

import math
from pathlib import Path
from typing import Any

from ..backend import BuildError, Tier, Unsupported, Vec3, effective_timeout
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
        "draft_angle",
        "self_intersection_free",
        "step_roundtrip",
        "min_wall",
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


def _min_draft_deg(a_coef: float, b_coef: float, c_coef: float, u1: float, u2: float) -> float:
    """min over u in [u1, u2] of asin(|a cos u + b sin u + c|), in degrees.

    The normal of a cylinder or cone dotted with the pull direction is exactly
    this sinusoid in the surface's angular parameter; its extreme over the
    face's wrap interval is at an endpoint, a crest (u = phi + k*pi), or a zero
    crossing (where the |.| bottoms out at 0). All candidates are enumerated,
    so the minimum is exact — no sampling.
    """
    radius = math.hypot(a_coef, b_coef)
    phi = math.atan2(b_coef, a_coef)

    candidates = [u1, u2]

    def add_periodic(base: float) -> None:
        k = math.floor((u1 - base) / math.tau)
        u = base + k * math.tau
        while u <= u2 + 1e-12:
            if u >= u1 - 1e-12:
                candidates.append(min(max(u, u1), u2))
            u += math.tau

    add_periodic(phi)  # crest
    add_periodic(phi + math.pi)  # trough
    if radius > 0.0 and abs(c_coef) <= radius:
        # |A cos u + B sin u + C| reaches 0 where cos(u - phi) = -C/R.
        offset = math.acos(max(-1.0, min(1.0, -c_coef / radius)))
        add_periodic(phi + offset)
        add_periodic(phi - offset)

    best = min(abs(radius * math.cos(u - phi) + c_coef) for u in candidates)
    return math.degrees(math.asin(min(1.0, best)))


def _min_wall_measurement(raw: dict[str, Any]) -> Measurement:
    """The Measurement rule shared by `measure` and the check branch: exact
    when the interval collapses, else the guaranteed [lo, hi]."""
    lo, hi = raw["lo"], raw["hi"]
    if hi - lo <= 1e-9 * max(1.0, lo):
        return Measurement(lo, "mm", exact=True)
    return Measurement(lo, "mm", exact=False, bounds=(lo, hi))


class _quiet_occt:
    """Silence OCCT's console printers for the duration — the STEP machinery
    narrates transfers to stdout, and the CLI's stdout is the artifact
    channel. Printers are restored on exit, whatever happens."""

    def __enter__(self) -> None:
        from OCP.Message import Message  # type: ignore[attr-defined]

        self._messenger = Message.DefaultMessenger_s()
        self._printers = list(self._messenger.Printers())
        for printer in self._printers:
            self._messenger.RemovePrinter(printer)

    def __exit__(self, *exc: object) -> None:
        for printer in self._printers:
            self._messenger.AddPrinter(printer)


def _surface_name(kind: Any) -> str:
    """A human name for a GeomAbs surface type enum, without importing the
    whole enum table: the repr carries the name."""
    text = str(kind).rsplit("_", 1)[-1].rsplit(".", 1)[-1].lower()
    # "bsplinesurface surface" and "surfaceofextrusion surface" read doubled;
    # strip the noun the caller adds (PR #141 review, F5).
    text = text.removeprefix("surfaceof").removesuffix("surface")
    return text or "unknown"


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

    def build(
        self, source: pycad.PyCADSource, out_dir: Path, *, timeout_s: float | None = None
    ) -> Any | BuildError:
        """Build the part. `out_dir` is unused — nothing is exported to measure.

        The mesh tier has to round-trip through a file because OpenSCAD is a
        separate process. Here the shape is already in memory, and exporting it
        only to read it back would introduce the float32 quantisation this tier
        does not otherwise suffer.
        """
        return pycad.build(source, timeout_s=effective_timeout(timeout_s))

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

    def draft_angle(
        self, a: Any, direction: tuple[float, float, float]
    ) -> Measurement | Unsupported:
        """Per-face draft against a two-half parting axis, ascending, exact.

        Draft of a face at a point is the angle between the face and the pull
        line: `asin(|n . d|)` — 0 for a vertical wall, 90 for a face square to
        the pull. The reported value per face is the MINIMUM over the face,
        which for planes is constant and for cylinders and cones is the
        closed-form extreme of `|A cos u + B sin u + C|` over the face's wrap
        interval — no sampling, so `exact=True` is the truth, not a hope.

        Any face outside those three families refuses the WHOLE check: a
        sampled minimum has no guaranteed lower bound (more samples can only
        find a smaller draft — the min_wall one-sidedness, POST-V0 section 5),
        and passing the analytic subset would be silence reading as success
        on the faces that were skipped.
        """
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.GeomAbs import GeomAbs_SurfaceType  # type: ignore[attr-defined]

        dx, dy, dz = direction  # normalised at declaration

        def dot(vec: Any) -> float:
            return vec.X() * dx + vec.Y() * dy + vec.Z() * dz

        drafts: list[tuple[int, float]] = []
        for index, face in enumerate(a.faces()):
            surf = BRepAdaptor_Surface(face.wrapped)
            kind = surf.GetType()
            if kind == GeomAbs_SurfaceType.GeomAbs_Plane:
                c = abs(dot(surf.Plane().Axis().Direction()))
                drafts.append((index, math.degrees(math.asin(min(1.0, c)))))
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                pos = surf.Cylinder().Position()
                drafts.append(
                    (
                        index,
                        _min_draft_deg(
                            dot(pos.XDirection()),
                            dot(pos.YDirection()),
                            0.0,
                            surf.FirstUParameter(),
                            surf.LastUParameter(),
                        ),
                    )
                )
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cone:
                cone = surf.Cone()
                pos = cone.Position()
                ca, sa = math.cos(cone.SemiAngle()), math.sin(cone.SemiAngle())
                drafts.append(
                    (
                        index,
                        _min_draft_deg(
                            ca * dot(pos.XDirection()),
                            ca * dot(pos.YDirection()),
                            -sa * dot(pos.Direction()),
                            surf.FirstUParameter(),
                            surf.LastUParameter(),
                        ),
                    )
                )
            else:
                return Unsupported(
                    f"face_{index} is a {_surface_name(kind)} surface; draft needs "
                    "the normal field's extreme, which this backend derives in "
                    "closed form only for planes, cylinders and cones — a sampled "
                    "minimum would have no guaranteed bound, and a verdict that "
                    "skipped this face would be silence reading as success"
                )
        drafts.sort(key=lambda entry: entry[1])
        return Measurement(
            tuple(value for _, value in drafts),
            "deg",
            exact=True,
            axes=tuple(f"face_{i}" for i, _ in drafts),
        )

    def self_intersection_free(self, a: Any) -> Measurement:
        """Whether the shape is free of pairwise self-intersection — exact.

        The kernel's own argument analysis (`BRepAlgoAPI_Check` in
        self-intersection mode): every sub-shape pair that intersects where
        the boundary says it must not is a fault. Exact because it is
        analysis, not sampling.

        The recorded limit (SPEC-contract.md 4.9, executed): a
        self-intersection lying within a single ANALYTIC surface — the
        spindle torus — goes undetected and passes. The kernel does test a
        face against itself and catches a self-overlapping swept face (a
        pair-less fault), so the escape is specifically the analytic case,
        not single-surface faults in general (PR #142 review, F1).
        """
        return Measurement(not self._self_intersections(a), "bool", exact=True)

    def self_intersection_free_detail(self, a: Any) -> str:
        """Name the intersecting entity pairs, for the failure detail."""
        pairs = self._self_intersections(a)
        counts: dict[str, int] = {}
        for kinds in pairs:
            counts[kinds] = counts.get(kinds, 0) + 1
        inventory = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        # "fault(s)", not "pair(s)": a face caught against ITSELF reports as
        # a single entity (PR #142 review, F1).
        return f"{len(pairs)} self-intersecting entity fault(s): {inventory}"

    def _self_intersections(self, a: Any) -> list[str]:
        """The faulty pairs as `type/type` strings (e.g. `edge/face`)."""
        from OCP.BOPAlgo import BOPAlgo_CheckStatus  # type: ignore[attr-defined]
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Check  # type: ignore[attr-defined]

        check = BRepAlgoAPI_Check(a.wrapped, False, True)  # SE off, SI on
        pairs: list[str] = []
        for result in check.Result():
            if result.GetCheckStatus() != BOPAlgo_CheckStatus.BOPAlgo_SelfIntersect:
                continue
            kinds = "/".join(
                str(shape.ShapeType()).rsplit("_", 1)[-1].lower()
                for shape in result.GetFaultyShapes1()
            )
            pairs.append(kinds)
        return pairs

    def step_roundtrip(self, a: Any) -> dict[str, Any] | Unsupported:
        """Write the shape to STEP, read it back, measure what survived.

        Returns the raw comparison — relative volume and area deltas (exact:
        both sides are the kernel's own exact quantities, so the delta is a
        computed number, not an estimate), the topology counts before and
        after, and the writer schema, which is recorded because it changes
        the artifact (the F13 lesson). The runner adjudicates.

        The exchange happens in a scratch directory: this check is about
        survivability, not about producing an export.
        """
        import tempfile

        from ..engines.pycad import adopt

        with _quiet_occt(), tempfile.TemporaryDirectory() as scratch:
            path = str(Path(scratch) / "part.step")
            schema = self._write_step(a, path)
            if schema is None:
                return Unsupported(
                    "the STEP writer could not serialise this shape; nothing "
                    "was compared, so nothing may be said about survivability"
                )
            raw = self._read_step(path)
            if raw is None:
                # The writer accepted it and the reader will not: that IS
                # degradation, total — but with nothing to measure, the
                # honest report is the refusal naming the asymmetry.
                return Unsupported(
                    "the STEP reader could not read back what the writer "
                    "wrote — the exchange failed whole"
                )
            back = adopt(raw)
        if isinstance(back, BuildError):
            return Unsupported(f"the round-tripped shape did not survive adoption: {back.message}")

        volume = abs(a.volume)
        area = abs(a.area)
        return {
            "schema": schema,
            "volume_rel": abs(back.volume - a.volume) / max(volume, 1e-12),
            "area_rel": abs(back.area - a.area) / max(area, 1e-12),
            "faces": (len(a.faces()), len(back.faces())),
            "edges": (len(a.edges()), len(back.edges())),
            "solids": (len(a.solids()), len(back.solids())),
        }

    def _write_step(self, a: Any, path: str) -> str | None:
        """Write the shape to `path`; the writer schema on success, None on
        refusal. A seam, so the refusal branch is testable (PR #143, F3)."""
        from OCP.IFSelect import IFSelect_ReturnStatus  # type: ignore[attr-defined]
        from OCP.Interface import Interface_Static  # type: ignore[attr-defined]
        from OCP.STEPControl import (
            STEPControl_StepModelType,  # pyright: ignore[reportAttributeAccessIssue]
            STEPControl_Writer,  # pyright: ignore[reportAttributeAccessIssue]
        )

        writer = STEPControl_Writer()
        writer.Transfer(a.wrapped, STEPControl_StepModelType.STEPControl_AsIs)
        if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
            return None
        return str(Interface_Static.CVal_s("write.step.schema"))

    def _read_step(self, path: str) -> Any | None:
        """Read a STEP file back; the raw shape, or None on refusal."""
        from OCP.IFSelect import IFSelect_ReturnStatus  # type: ignore[attr-defined]
        from OCP.STEPControl import (
            STEPControl_Reader,  # pyright: ignore[reportAttributeAccessIssue]
        )

        reader = STEPControl_Reader()
        if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
            return None
        reader.TransferRoots()
        return reader.OneShape()

    def min_wall(self, a: Any) -> Measurement | Unsupported:
        """The minimum wall for `measure`: the raw analysis as a Measurement,
        witness dropped. The runner's check branch uses `_min_wall_raw` and
        keeps the witness for the failure detail."""
        raw = self._min_wall_raw(a)
        if isinstance(raw, Unsupported):
            return raw
        if raw.get("vacuous"):
            return Unsupported(
                "no wall spans exist: every face pair meets at an edge, and "
                "corner features are not walls"
            )
        return _min_wall_measurement(raw)

    def _min_wall_raw(self, a: Any) -> dict[str, Any] | Unsupported:
        """Method E (#140, executed research): a GUARANTEED interval on the
        minimum wall.

        `lo` = the kernel-exact minimum distance over admissible face pairs
        (`BRepExtrema_DistShapeShape`) plus the analytic self-spans of closed
        faces — every first-exit normal span from F landing on G satisfies
        span >= dist(F, G), so lo can never exceed the true minimum wall.
        `hi` = the smallest WITNESSED span (an achieved self-span, or a
        sampled inward normal ray) — an actual material crossing, so the true
        minimum can never exceed it. [lo, hi] therefore contains the truth
        (SPEC-report 3.1's bar), and collapses to exact on parallel-analytic
        walls.

        Admissible = non-adjacent: faces meeting at a shared edge are a
        modeling feature (a wedge, a corner), never a wall — the structural
        form of the wedge policy; a truncated tip stops sharing the edge and
        is measured. A pair is excluded as a GAP only on the two-signal test
        (min-segment midpoint outside the solid AND the normals at the
        realization facing each other); anything unclassifiable stays in,
        which can only shrink lo — the false-alarm direction, never the
        false-pass one.

        Refusal edges, recorded: a closed periodic face outside the analytic
        families (cylinder / sphere / torus / frustum) has no guaranteed
        self-span; a pair the kernel cannot resolve leaves lo unguaranteed.
        Both refuse the whole check by name. A cone tip (apex radius 0) is
        the wedge-in-the-round and is skipped as a feature, mirroring the
        shared-edge policy.
        """
        from OCP.Bnd import Bnd_Box  # type: ignore[attr-defined]
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepBndLib import BRepBndLib  # type: ignore[attr-defined]
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # type: ignore[attr-defined]
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # type: ignore[attr-defined]
        from OCP.GeomAbs import GeomAbs_SurfaceType  # type: ignore[attr-defined]
        from OCP.gp import gp_Pnt  # type: ignore[attr-defined]
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_IN, TopAbs_ON  # type: ignore[attr-defined]
        from OCP.TopExp import TopExp  # type: ignore[attr-defined]
        from OCP.TopTools import TopTools_IndexedMapOfShape  # type: ignore[attr-defined]

        faces = a.faces()
        solid = a.wrapped

        def inside(x: float, y: float, z: float) -> bool:
            probe = BRepClass3d_SolidClassifier(solid, gp_Pnt(x, y, z), 1e-7)
            return probe.State() in (TopAbs_IN, TopAbs_ON)

        best: float | None = None
        witness = ""
        exact_witness = False  # a self-span is achieved, not just bounded

        # -- analytic self-spans of closed faces ---------------------------
        for index, face in enumerate(faces):
            surf = BRepAdaptor_Surface(face.wrapped)
            if not (surf.IsUClosed() or surf.IsVClosed()):
                continue
            kind = surf.GetType()
            if kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                span = 2.0 * cyl.Radius()
                pos = cyl.Position()
                v_mid = (surf.FirstVParameter() + surf.LastVParameter()) / 2.0
                loc, axis = pos.Location(), pos.Direction()
                px = loc.X() + axis.X() * v_mid
                py = loc.Y() + axis.Y() * v_mid
                pz = loc.Z() + axis.Z() * v_mid
            elif kind == GeomAbs_SurfaceType.GeomAbs_Sphere:
                sph = surf.Sphere()
                span = 2.0 * sph.Radius()
                centre = sph.Location()
                px, py, pz = centre.X(), centre.Y(), centre.Z()
            elif kind == GeomAbs_SurfaceType.GeomAbs_Torus:
                tor = surf.Torus()
                span = 2.0 * tor.MinorRadius()
                pos = tor.Position()
                loc, xdir = pos.Location(), pos.XDirection()
                major = tor.MajorRadius()
                px = loc.X() + xdir.X() * major
                py = loc.Y() + xdir.Y() * major
                pz = loc.Z() + xdir.Z() * major
            elif kind == GeomAbs_SurfaceType.GeomAbs_Cone:
                cone = surf.Cone()
                alpha = cone.SemiAngle()
                ref = cone.RefRadius()
                radii = sorted(
                    abs(ref + v * math.sin(alpha))
                    for v in (surf.FirstVParameter(), surf.LastVParameter())
                )
                if radii[0] <= 1e-9:
                    continue  # the apex: a wedge-in-the-round, a feature
                span = 2.0 * radii[0]
                v_at = min(
                    (surf.FirstVParameter(), surf.LastVParameter()),
                    key=lambda v: abs(ref + v * math.sin(alpha)),
                )
                pos = cone.Position()
                loc, axis = pos.Location(), pos.Direction()
                along = v_at * math.cos(alpha)
                px = loc.X() + axis.X() * along
                py = loc.Y() + axis.Y() * along
                pz = loc.Z() + axis.Z() * along
            else:
                return Unsupported(
                    f"face_{index} is a closed {_surface_name(kind)} surface "
                    "with no analytic self-span; a sampled span has no "
                    "guaranteed bound, so the wall cannot be certified"
                )
            if not inside(px, py, pz):
                continue  # the enclosed axis is void: a bore, not a wall
            if best is None or span < best:
                best, witness, exact_witness = span, f"face_{index} self-span", True

        # -- adjacency by shared edges (IsSame-keyed via OCCT maps) --------
        global_edges = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(solid, TopAbs_EDGE, global_edges)
        edge_sets: list[set[int]] = []
        for face in faces:
            face_edges = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(face.wrapped, TopAbs_EDGE, face_edges)
            edge_sets.append(
                {
                    global_edges.FindIndex(face_edges.FindKey(k))
                    for k in range(1, face_edges.Extent() + 1)
                }
            )

        boxes = []
        for face in faces:
            box = Bnd_Box()
            BRepBndLib.Add_s(face.wrapped, box)
            boxes.append(box)

        # -- the pair loop, AABB-pruned ------------------------------------
        pair_seen = False
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                if edge_sets[i] & edge_sets[j]:
                    continue  # shared edge: a corner feature, not a wall
                pair_seen = True
                if best is not None and boxes[i].Distance(boxes[j]) >= best:
                    continue  # sound pruning: box distance <= true distance
                extrema = BRepExtrema_DistShapeShape(faces[i].wrapped, faces[j].wrapped)
                if not extrema.IsDone() or extrema.NbSolution() == 0:
                    return Unsupported(
                        f"the kernel could not resolve the distance between "
                        f"face_{i} and face_{j}; the bound would not be guaranteed"
                    )
                distance = extrema.Value()
                if best is not None and distance >= best:
                    continue
                p1, p2 = extrema.PointOnShape1(1), extrema.PointOnShape2(1)
                ax_, ay_, az_ = p1.X(), p1.Y(), p1.Z()
                bx_, by_, bz_ = p2.X(), p2.Y(), p2.Z()
                mid_in = inside((ax_ + bx_) / 2, (ay_ + by_) / 2, (az_ + bz_) / 2)
                gap = not mid_in
                if mid_in:
                    ux, uy, uz = bx_ - ax_, by_ - ay_, bz_ - az_
                    norm = math.sqrt(ux * ux + uy * uy + uz * uz)
                    if norm > 1e-12:
                        try:
                            from build123d import Vector

                            n1 = faces[i].normal_at(Vector(ax_, ay_, az_))
                            n2 = faces[j].normal_at(Vector(bx_, by_, bz_))
                            ux, uy, uz = ux / norm, uy / norm, uz / norm
                            facing = (
                                n1.X * ux + n1.Y * uy + n1.Z * uz > 0
                                and n2.X * ux + n2.Y * uy + n2.Z * uz < 0
                            )
                            gap = facing  # normals facing each other: void between
                        except Exception:  # noqa: BLE001 - unclassifiable stays in
                            gap = False
                if gap:
                    continue
                best, witness, exact_witness = (
                    distance,
                    f"face_{i}/face_{j}",
                    False,
                )

        if best is None:
            return {"vacuous": True, "pair_seen": pair_seen}

        if exact_witness:
            return {"lo": best, "hi": best, "witness": witness}

        hi = self._min_wall_witnessed_span(a, faces, witness, best)
        if hi is None:
            return Unsupported(
                "no witnessed span could be measured, so the interval has no "
                "upper end and the wall cannot be honestly bounded"
            )
        return {"lo": best, "hi": max(hi, best), "witness": witness}

    def _min_wall_witnessed_span(
        self, a: Any, faces: list[Any], witness: str, floor: float
    ) -> float | None:
        """The smallest sampled inward-normal span on the realizing faces —
        an ACHIEVED material crossing, hence an upper bound on the minimum.
        A seam, so the sampling density is one place and testable."""
        from build123d import Axis  # type: ignore[import-untyped]
        from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[attr-defined]
        from OCP.BRepGProp import BRepGProp_Face  # type: ignore[attr-defined]
        from OCP.gp import gp_Pnt, gp_Vec  # type: ignore[attr-defined]

        indices = [int(part.split("_")[1]) for part in witness.split("/")]
        hi: float | None = None
        for index in indices:
            face = faces[index]
            surf = BRepAdaptor_Surface(face.wrapped)
            prop = BRepGProp_Face(face.wrapped)
            u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
            v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
            steps = 6
            for iu in range(1, steps):
                for iv in range(1, steps):
                    u = u1 + (u2 - u1) * iu / steps
                    v = v1 + (v2 - v1) * iv / steps
                    pnt, vec = gp_Pnt(), gp_Vec()
                    prop.Normal(u, v, pnt, vec)
                    length = vec.Magnitude()
                    if length < 1e-12:
                        continue
                    direction = (-vec.X() / length, -vec.Y() / length, -vec.Z() / length)
                    origin = (pnt.X(), pnt.Y(), pnt.Z())
                    try:
                        hits = a.find_intersection_points(Axis(origin=origin, direction=direction))
                    except Exception:  # noqa: BLE001 - a failed ray is a missing witness, not a lie
                        continue
                    for hit, _normal in hits:
                        along = (
                            (hit.X - origin[0]) * direction[0]
                            + (hit.Y - origin[1]) * direction[1]
                            + (hit.Z - origin[2]) * direction[2]
                        )
                        if along > 1e-6:
                            if along >= floor - 1e-12 and (hi is None or along < hi):
                                hi = along
                            break
        return hi

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
