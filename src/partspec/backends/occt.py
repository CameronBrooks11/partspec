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
    }
)


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

    def bbox(self, a: Any) -> Measurement:
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

    def area(self, a: Any) -> Measurement:
        """Total surface area. Total, like the mesh tier's — defined for a face
        and a shell as much as for a solid."""
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

    def watertight(self, a: Any) -> Measurement:
        """`is_manifold` on a BREP: every edge bounded by exactly two faces."""
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
        return Measurement(float((a & b).volume), "mm3", exact=True)

    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> Unsupported:
        """Not implemented on this tier yet.

        `find_intersection_points` exists in build123d, but no v0 check calls it
        and it serves min_wall, which is post-v0. Declared absent rather than
        written untested.
        """
        return Unsupported("raycast is not implemented on the occt tier yet")
