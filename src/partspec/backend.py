"""The geometry backend protocol.

The finding this design rests on (investigations/03): cad-khana's build123d
coupling is *pervasive by type but shallow by behaviour* — twelve geometry
primitives carry its entire diagnostic vocabulary, and most of the valuable logic
is already engine-independent. So engine neutrality is not a rewrite; it is a
protocol over a dozen methods plus value types of our own.

Two backends, not three (D3). One OCCT backend serves build123d *and* CadQuery
via a `.wrapped` adopt shim at the front door — verified: both expose a
`TopoDS_Shape` from the same OCP module, and `bd.Solid(cq_shape.wrapped)` adopts
losslessly. The only genuinely separate backend is mesh, for OpenSCAD.

Spec: SPEC-backend.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .status import Measurement

__all__ = [
    "BBox",
    "BuildError",
    "GeometryBackend",
    "Tier",
    "Unsupported",
    "Vec3",
]

# `Transform` and `Plane` are deliberately absent in v0. They are needed for
# placement and datum targets, which are assembly concerns (D11). Adding them
# later is additive and breaks nothing.


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True, slots=True)
class BBox:
    lo: Vec3
    hi: Vec3

    @property
    def size(self) -> Vec3:
        return Vec3(self.hi.x - self.lo.x, self.hi.y - self.lo.y, self.hi.z - self.lo.z)


class Tier:
    """Capability class of a backend, as opposed to its implementation."""

    MESH = "mesh"
    OCCT = "occt"


@dataclass(frozen=True, slots=True)
class Unsupported:
    """A backend's honest refusal — a *return value*, never an exception.

    This is the protocol-level enforcement of the rule that gives the tool its
    point. A backend MUST NOT satisfy a query by reconstructing an entity its
    representation does not contain, and it MUST NOT return a plausible-looking
    number in place of an answer.

    It is also precisely where PartCAD goes wrong: by normalising an OpenSCAD
    mesh into a faceted TopoDS_Shape, its topology queries *run* and return
    triangle counts dressed as engineering topology, with no capability
    declaration and no degradation signal.

    The second, less obvious route here is a quantity with no honest error
    bound. Wall thickness is sampled on both tiers, and sampling is one-sided by
    construction — more samples can only ever find a *thinner* wall — so a
    measurement is an upper bound on the true minimum, not an interval. That is
    `Unsupported`, not `approximate`.
    """

    reason: str
    requires: str | None = None
    """The tier that would answer *for an equivalent part*. The hedge matters:
    porting a 16-gon bore to build123d does not merely enable the check, it
    changes the part."""


@dataclass(frozen=True, slots=True)
class BuildError:
    """The engine failed to produce an artifact.

    `origin` separates two failures that used to be reported identically and
    mean opposite things. `"model"` is a statement about the part -- the design
    does not compile -- and adjudicates as a failing `builds` check, exit 1.
    `"environment"` is not a statement about the part at all: no engine on PATH,
    a mistyped pin, a missing package, an absent source file, a render that ran
    out of time. Every one of those used to land on `builds: fail`, so a CI run
    on a machine without OpenSCAD reported the *design* as disproven.
    """

    message: str
    hint: str | None = None
    origin: Literal["environment", "model"] = "model"
    stderr: str | None = None
    """The engine's full stderr, when the failure came from a subprocess.

    `hint` is one selected line; selection can be wrong, so the unabridged
    diagnosis rides along and reaches the report (#37). None for failures
    with no engine output (missing binary, unbound parameter)."""


@runtime_checkable
class GeometryBackend(Protocol):
    """What every backend implements.

    Sixteen primitives, plus lifecycle and an explicit capability declaration.
    Each returns a `Measurement` carrying its own `exact` flag, so a caller
    cannot accidentally lose provenance by receiving a bare float.
    """

    kind: str  # Tier.MESH | Tier.OCCT
    engine: str  # "openscad" | "build123d" | "cadquery"
    engine_version: str

    # --- lifecycle ---

    def build(self, source: Any, params: dict[str, Any]) -> Any | BuildError:
        """Run the engine and return an opaque artifact handle."""
        ...

    def provenance(self, a: Any) -> dict[str, Any]:
        """Populate the report's `geometry` block.

        Mesh tier emits `triangles` and `facets`; both, not either. `facets` is
        the coplanar-grouped count — retriangulation-invariant, and it tracks
        $fn nearly one-to-one, so it is the identity signal. `triangles` is the
        drift explainer, because chord error scales with edge length.
        """
        ...

    def capabilities(self) -> frozenset[str]:
        """Primitives this backend can answer at all.

        Consulted before dispatch, so an `unsupported` result costs nothing.
        Capability is static; exactness is not, and is decided per evaluation.
        """
        ...

    # --- the sixteen primitives ---

    # `bbox`, `area` and `watertight` are total: they are statements about the
    # triangles or the shape as given, and stay answerable however broken it is.
    # The rest are conditional, and each returns `Unsupported` rather than a
    # number when its precondition fails — volume and centre of mass presume a
    # closed consistently-wound surface, genus presumes a single closed body,
    # and a body count presumes no edge shared by more than two faces.
    def bbox(self, a: Any) -> Measurement: ...
    def volume(self, a: Any) -> Measurement | Unsupported: ...
    def area(self, a: Any) -> Measurement: ...
    def center_of_mass(self, a: Any) -> Measurement | Unsupported: ...
    def is_valid(self, a: Any) -> Measurement: ...
    def watertight(self, a: Any) -> Measurement: ...
    def solid_count(self, a: Any) -> Measurement | Unsupported: ...
    def genus(self, a: Any) -> Measurement | Unsupported: ...
    def topology_counts(self, a: Any) -> Measurement | Unsupported: ...
    def triangles(self, a: Any) -> Any: ...

    # Present because they are part of the twelve and the mesh backend
    # implements them cheaply. No v0 check calls them — they serve clearance,
    # interference and min_wall, all post-v0 — but specifying them now means the
    # protocol does not change when those land.
    def min_distance(self, a: Any, b: Any) -> Measurement | Unsupported: ...
    def intersect_volume(self, a: Any, b: Any) -> Measurement | Unsupported: ...
    def raycast(self, a: Any, origin: Vec3, direction: Vec3) -> list[Vec3] | Unsupported: ...

    def region_solid(self, region: Any) -> Any:
        """Materialize a declared `partspec.region` as this backend's native solid.

        Both tiers MUST realise the same polyhedron from the region's canonical
        vertex list (SPEC-contract.md 4.4) — a backend that substitutes an exact
        cylinder for the polygon prism is answering a different question than
        the other tier, however much better its representation could do.
        """
        ...

    def bores(self, a: Any) -> Measurement | Unsupported:
        """Every cylindrical bore's diameter (SPEC-contract.md 4.5).

        OCCT-only, like `topology_counts`, and for the same reason: a mesh has
        no cylindrical face to enumerate, and fitting one to the facets
        manufactures the confident wrong number this protocol exists to refuse.
        The mesh backend MUST NOT declare this capability.
        """
        ...

    def bore_table(self, a: Any) -> Any:
        """The raw per-bore view beneath `bores` — `{d, direction, center}`
        per bore — consumed by `bolt_circle` (SPEC-contract.md 4.6). OCCT-only,
        with `bores`."""
        ...

    def blend_radii(self, a: Any) -> Measurement | Unsupported:
        """Every partial-wrap cylindrical cluster's radius, ascending — the
        candidates a `fillet_radius` claim ranges over (SPEC-contract.md 4.7).
        OCCT-only, with `bores`; MUST share its clustering, so a seam-split
        bore cannot masquerade as two blends."""
        ...
