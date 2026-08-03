"""The mesh backend: measures a triangle mesh, which is what OpenSCAD emits.

Every quantity here is reported `exact`, and that is not a shortcut. Under D15 a
measurement describes *the artifact as authored and exported*, and a mesh **is** a
polyhedron — its volume, area, bounding box, watertightness, solid count and genus
are computed exactly from its triangles. There is no smooth ideal being
approximated, so there is no tessellation error to bound. Changing $fn does not
degrade a measurement; it produces a *different part*, which is a design change
the tool should report loudly rather than absorb into an error bar.

The one genuine inexactness is float32 quantisation in binary STL (~1e-7
relative), which is narrower than the comparison epsilon and so carries no
information — see `SPEC-backend.md` 5.2 for why collapsing it is permitted here
and nowhere else.

Spec: SPEC-backend.md section 5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..backend import BuildError, Tier, Unsupported, Vec3
from ..engines import openscad
from ..status import Measurement

__all__ = ["CAPABILITIES", "MeshBackend"]

CAPABILITIES = frozenset(
    {
        "bbox",
        "volume",
        "area",
        "center_of_mass",
        "watertight",
        "solid_count",
        "genus",
        "triangles",
        "min_distance",
        "intersect_volume",
        "raycast",
    }
)
"""What this tier can answer at all. `topology_counts` is absent on purpose: a
triangle count is not a face count, and returning one is exactly the failure this
tool exists to prevent."""

_NORMAL_DECIMALS = 4


class MeshBackend:
    """Measures a triangle mesh. Currently fed by OpenSCAD.

    Nothing here is OpenSCAD-specific — a tessellated OCCT shape would measure
    identically — but OpenSCAD is the only producer in v0.
    """

    kind = Tier.MESH
    engine = "openscad"

    def __init__(self) -> None:
        self._version: str | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def engine_version(self) -> str:
        if self._version is None:
            self._version = openscad.version()
        return self._version

    def build(self, source: openscad.OpenSCADSource, out_dir: Path) -> Any | BuildError:
        result = openscad.render(source, out_dir)
        if isinstance(result, BuildError):
            return result
        return self.load(result)

    def load(self, stl: Path) -> Any | BuildError:
        """Load an exported mesh.

        `load_mesh` explicitly rather than `load`: the latter can return a Scene
        for a multi-body file, which has different semantics for the same
        attribute names. A silent type change is not something a measurement
        layer should be exposed to.
        """
        import trimesh

        mesh = trimesh.load_mesh(stl)
        if getattr(mesh, "faces", None) is None or len(mesh.faces) == 0:
            return BuildError(f"exported mesh has no triangles: {stl}")
        return mesh

    def capabilities(self) -> frozenset[str]:
        return CAPABILITIES

    def provenance(self, a: Any) -> dict[str, Any]:
        """The report's `geometry` block.

        Takes the artifact rather than reading instance state: a backend that
        remembers its last build is one shared instance away from reporting
        provenance for the wrong part.

        Both counts, not either. `distinct_normals` is the identity signal: it
        tracks $fn one-to-one (a cylinder at $fn=n gives n+2) and is invariant
        under retriangulation, so two runs of the same design agree even if the
        triangulation differs. `triangles` is the drift explainer, because chord
        error scales with edge length.
        """
        return {
            "triangles": int(len(a.faces)),
            "distinct_normals": _distinct_normals(a),
        }

    # -- the primitives ----------------------------------------------------

    def bbox(self, a: Any) -> Measurement:
        extents = tuple(float(v) for v in a.extents)
        return Measurement(extents, "mm", exact=True, axes=("x", "y", "z"))

    def volume(self, a: Any) -> Measurement:
        return Measurement(float(a.volume), "mm3", exact=True)

    def area(self, a: Any) -> Measurement:
        return Measurement(float(a.area), "mm2", exact=True)

    def center_of_mass(self, a: Any) -> Measurement:
        com = tuple(float(v) for v in a.center_mass)
        return Measurement(com, "mm", exact=True, axes=("x", "y", "z"))

    def is_valid(self, a: Any) -> Measurement:
        return Measurement(bool(a.is_volume), "bool", exact=True)

    def watertight(self, a: Any) -> Measurement:
        return Measurement(bool(a.is_watertight), "bool", exact=True)

    def watertight_detail(self, a: Any) -> str | None:
        """Why a mesh is not watertight — boundary edges or non-manifold ones.

        trimesh's `is_watertight` means "every edge is used by exactly two
        faces", which conflates two different defects: an edge used **once** is
        a hole, an edge used **more than twice** is a non-manifold junction
        where surfaces touch. They have different causes and different fixes, so
        reporting only "not watertight" makes the reader go and find out which.

        Found by dogfooding: a community gridfinity bin rendered by OpenSCAD's
        default Manifold backend has 0 boundary edges and 4 non-manifold ones,
        and "not watertight" alone reads as "it has holes", which it does not.
        """
        import numpy as np

        if a.is_watertight:
            return None
        _, counts = np.unique(a.edges_sorted, axis=0, return_counts=True)
        boundary = int((counts == 1).sum())
        nonmanifold = int((counts > 2).sum())
        parts = []
        if boundary:
            parts.append(f"{boundary} boundary edge(s) — the surface is open")
        if nonmanifold:
            parts.append(
                f"{nonmanifold} non-manifold edge(s) — more than two faces meet along them"
            )
        return "; ".join(parts) or "not watertight for an unclassified reason"

    def solid_count(self, a: Any) -> Measurement:
        """Connected component count, via manifold3d.

        Not trimesh's `body_count`, which routes through
        `graph.connected_components` and raises ImportError without scipy or
        networkx. manifold3d is already a dependency and answers directly.
        """
        return Measurement(len(_manifold(a).decompose()), "count", exact=True)

    def genus(self, a: Any) -> Measurement | Unsupported:
        """Topological genus — through-holes — for a single-body part.

        Refused for multi-body parts, and the reason is worth stating: genus is
        defined per body, but manifold3d reports the genus of the whole complex,
        which is a different number. Two disjoint boxes give -1, not 0. Rather
        than return a mathematically correct value that answers a question nobody
        asked, this reports unsupported and says to check `solid_count` first.
        """
        manifold = _manifold(a)
        bodies = len(manifold.decompose())
        if bodies != 1:
            return Unsupported(
                f"genus is defined per body; this part has {bodies} solids "
                f"(check solid_count first, or split the part)"
            )
        return Measurement(int(manifold.genus()), "count", exact=True)

    def topology_counts(self, a: Any) -> Unsupported:
        """Always refused on this tier.

        A mesh has triangles, not engineering topology. Reporting a triangle
        count as a face count is precisely how PartCAD's OpenSCAD path misleads:
        the query runs, returns a number, and nothing signals that the number
        means something else.
        """
        return Unsupported(
            "a triangle mesh has no engineering topology; face and edge counts "
            "would be triangle counts wearing the wrong name",
            requires=Tier.OCCT,
        )

    def triangles(self, a: Any) -> Any:
        return a.triangles

    def min_distance(self, a: Any, b: Any) -> Measurement:
        return Measurement(float(_manifold(a).min_gap(_manifold(b), 1e6)), "mm", exact=True)

    def intersect_volume(self, a: Any, b: Any) -> Measurement:
        return Measurement(float((_manifold(a) ^ _manifold(b)).volume()), "mm3", exact=True)

    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> list[Vec3]:
        locations = a.ray.intersects_location(
            ray_origins=[list(origin.as_tuple())],
            ray_directions=[list(direction.as_tuple())],
        )[0]
        return [Vec3(*(float(c) for c in point)) for point in locations]


def _distinct_normals(mesh: Any, decimals: int = _NORMAL_DECIMALS) -> int:
    """Count distinct face normals.

    Deliberately NOT trimesh's `.facets` (coplanar-region grouping), which needs
    scipy or networkx — a large dependency for one provenance field, against D14's
    "light, pure wheels". Distinct normals serve the same purpose: 6 for a cube,
    n+2 for a cylinder at $fn=n, and unchanged by subdivision.

    It differs from a true facet count only where two disjoint coplanar regions
    share a normal, which merges them. That is why the field is named for what it
    measures rather than borrowed from CGAL's vocabulary.
    """
    import numpy as np

    normals = np.round(np.asarray(mesh.face_normals, dtype=np.float64), decimals)
    normals += 0.0  # normalise -0.0 to 0.0 so it does not read as a distinct row
    return int(len(np.unique(normals, axis=0)))


def _manifold(mesh: Any) -> Any:
    """Wrap a trimesh into a manifold3d Manifold."""
    import numpy as np
    from manifold3d import Manifold, Mesh

    return Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )
