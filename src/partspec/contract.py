"""The contract: what an author declares about a part.

An ordinary Python module, not a config file and not a DSL (D6). That buys
expressiveness, costs no schema, and — because the contract references the source
rather than being written in the source's language — works identically for an
OpenSCAD `.scad` and a build123d module.

Spec: SPEC-contract.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .provenance import source_map
from .region import BoxRegion, CylinderRegion, Region
from .status import ContractError, Limit, epsilon

__all__ = [
    "GEOMETRY_KINDS",
    "CheckSpec",
    "Part",
    "Source",
    "build123d",
    "cadquery",
    "openscad",
]

PARAMETER = "parameter"
GEOMETRY = "geometry"

GEOMETRY_KINDS: dict[str, str] = {
    "envelope": "bbox",
    "watertight": "watertight",
    "solid_count": "solid_count",
    "cavities": "cavities",
    "genus": "genus",
    "volume": "volume",
    "area": "area",
    "topology": "topology_counts",
    "keep_out": "region_solid",
    "keep_in": "region_solid",
    "hole_diameter": "bores",
    "bolt_circle": "bore_table",
    "fillet_radius": "blend_radii",
}
"""The closed geometry vocabulary, mapped to the backend primitive that answers
it. `builds` is absent because it is implicit and has no primitive — it is
whether the engine produced anything at all.

`topology` and `hole_diameter` are the entries whose primitives are **not** on
both tiers — the checks that make the tier difference visible to a contract
author rather than merely documented. `topology` was v0's single deliberate
member of that class; `hole_diameter` is the first of the BREP dimensions it
existed to pave the way for.

`keep_out` / `keep_in` map to the primitive that gates them; their evaluation is
composed in the runner from `region_solid` and `intersect_volume` rather than
being one primitive call (SPEC-contract.md 4.4)."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where the geometry comes from, and what to build it with.

    The engine is declared, never inferred from the file extension: a `.py` could
    be either Python engine, and guessing is the kind of implicitness this
    project exists to remove.
    """

    engine: str  # "openscad" | "build123d" | "cadquery"
    path: Path
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None
    backend: str | None = None
    """Engine-specific render backend. OpenSCAD only, for now."""

    def __post_init__(self) -> None:
        """A parameter that is not a number is refused where it enters.

        `float("nan")` reached adjudication and **passed**: every comparison
        against NaN is False, so `_satisfies_scalar` — which asks
        `not (value > hi + epsilon)` — is vacuously satisfied by any range.
        `param("x", min=1.0, max=20.0)` on a NaN reported `ok param:x`, exit 0.

        Caught here rather than at the measurement, because a non-finite
        parameter is a fact about the contract, not about the part: it also
        reaches `params` in the report, where it cannot be serialised as JSON at
        all. A ContractError makes it `verdict: "error"` and exit 4, which is
        what "the tool could not evaluate this" means.
        """
        for name, value in self.params.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ContractError(
                    f"parameter {name!r} is {value}, which is not a number; "
                    f"a non-finite parameter cannot be rendered or compared"
                )


def openscad(
    path: str | Path, /, method: str | None = None, backend: str | None = None, **params: Any
) -> Source:
    """An OpenSCAD source. Parameters become `-D name=value` overrides.

    With `method`, they instead become arguments to a call appended to a
    throwaway copy of the source; the file itself is never modified.

    `backend` selects the render backend ("Manifold" or "CGAL"). It is worth
    pinning: the two produce different meshes from identical source, and the
    default changed between OpenSCAD releases.
    """
    return Source(engine="openscad", path=Path(path), params=params, method=method, backend=backend)


def build123d(path: str | Path, /, method: str | None = None, **params: Any) -> Source:
    return Source(engine="build123d", path=Path(path), params=params, method=method)


def cadquery(path: str | Path, /, method: str | None = None, **params: Any) -> Source:
    return Source(engine="cadquery", path=Path(path), params=params, method=method)


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """One declared claim, before it has been evaluated."""

    id: str
    kind: str
    phase: str
    limit: Limit | None = None
    expr: str | None = None
    unit: str | None = None
    """Overrides the default for a `param_range` measurement. See `Part.param`."""
    region: Region | None = None
    shell: float | None = None
    """The declared region and its mandatory shell thickness, for `keep_out` /
    `keep_in` only. Not a `Limit`: the claim is a paired one (empty here, solid
    nearby, or the reverse) that no limit form expresses."""
    hole: dict[str, Any] | None = None
    """The declared bore for `hole_diameter` only: `{"d": ..., "count": ...}`.
    The diameter band lives in `limit`; this carries what the band was derived
    from and how many bores must fall inside it."""
    source: dict[str, Any] | None = None
    """Provenance of any Referenced values among this check's bounds:
    `{field: {"standard", "subject", "field"}}` (SPEC-contract.md 10). Absent
    when every input was a bare literal."""


class Part:
    """A part and the claims it must satisfy.

    Methods return `self`, so claims may be written as statements or chained.
    Statement form is what the spec shows and reads better with many checks.
    """

    def __init__(self, part_id: str, source: Source) -> None:
        if not part_id:
            raise ContractError("a part needs an id")
        self.id = part_id
        self.source = source
        self.checks: list[CheckSpec] = []

    # -- parameter phase ---------------------------------------------------

    def requires(self, expr: str, *, id: str | None = None) -> Part:
        """A predicate over the declared parameters, evaluated before the engine
        runs. No measurement, no limit — see SPEC-contract.md 5."""
        return self._add(
            CheckSpec(id=id or _slug(expr), kind="requires", phase=PARAMETER, expr=expr)
        )

    def param(
        self,
        name: str,
        *,
        min: float | None = None,
        max: float | None = None,
        unit: str | None = None,
        id: str | None = None,
    ) -> Part:
        """A bound on one named parameter.

        `unit` defaults to `mm`, v0's only length unit. Pass `unit="count"` for a
        genuine count -- a tooth number, a hole count. It used to be inferred
        from the Python literal type, so `40` and `40.0` produced different units
        for the same dimension.

        Preferred over `requires` for a simple bound, because it produces a real
        measurement that a future `diff` can track drift on — a parameter
        creeping from 8.0 to 8.09 against a `max` of 8.1 is two passes and one
        trend worth seeing.
        """
        if name not in self.source.params:
            known = ", ".join(sorted(self.source.params)) or "none"
            raise ContractError(f"param({name!r}) is not a declared parameter (declared: {known})")
        return self._add(
            CheckSpec(
                id=id or f"param:{name}",
                kind="param_range",
                phase=PARAMETER,
                limit=Limit(min=min, max=max),
                expr=name,
                unit=unit,
                source=source_map(min=min, max=max),
            )
        )

    # -- geometry phase ----------------------------------------------------

    def envelope(
        self,
        *,
        max: tuple[float, ...] | float | None = None,
        min: tuple[float, ...] | float | None = None,
        id: str | None = None,
    ) -> Part:
        """Bounding-box extents.

        Note for curved OpenSCAD parts: the envelope moves with `$fn`. A 16-gon
        bore really is narrower than the circle it approximates, and under D15
        that is a design fact the tool reports rather than an error it hides.
        """
        return self._add(
            CheckSpec(
                id=id or "envelope",
                kind="envelope",
                phase=GEOMETRY,
                limit=Limit(min=min, max=max),
                source=source_map(min=min, max=max),
            )
        )

    def watertight(self, *, id: str | None = None) -> Part:
        return self._add(
            CheckSpec(
                id=id or "watertight", kind="watertight", phase=GEOMETRY, limit=Limit(equals=True)
            )
        )

    def solid_count(self, n: int, *, id: str | None = None) -> Part:
        return self._add(
            CheckSpec(
                id=id or "solid_count", kind="solid_count", phase=GEOMETRY, limit=Limit(equals=n)
            )
        )

    def cavities(self, n: int, *, id: str | None = None) -> Part:
        """Sealed internal voids.

        Declaring `solid_count(1)` and `cavities(1)` says "one block with one
        enclosed void" — which used to be inexpressible, because the void was
        miscounted as a second solid. A part that means to have none should say
        `cavities(0)`: a void nobody asked for is trapped powder, an unprintable
        overhang, or a boolean that did not reach the surface.
        """
        return self._add(
            CheckSpec(id=id or "cavities", kind="cavities", phase=GEOMETRY, limit=Limit(equals=n))
        )

    def genus(self, n: int, *, id: str | None = None) -> Part:
        """Through-holes. Refused by the mesh backend for multi-body parts,
        because genus is defined per body."""
        return self._add(
            CheckSpec(id=id or "genus", kind="genus", phase=GEOMETRY, limit=Limit(equals=n))
        )

    def volume(
        self, *, min: float | None = None, max: float | None = None, id: str | None = None
    ) -> Part:
        """Plain bounds, deliberately without a tessellation tolerance.

        Under D15 a mesh *is* a polyhedron and its volume is closed-form, so
        there is no tessellation error to absorb. A volume check written against
        `$fn=128` failing at `$fn=32` is the tool working: those are different
        parts.
        """
        return self._add(
            CheckSpec(
                id=id or "volume",
                kind="volume",
                phase=GEOMETRY,
                limit=Limit(min=min, max=max),
                source=source_map(min=min, max=max),
            )
        )

    def area(
        self, *, min: float | None = None, max: float | None = None, id: str | None = None
    ) -> Part:
        return self._add(
            CheckSpec(
                id=id or "area",
                kind="area",
                phase=GEOMETRY,
                limit=Limit(min=min, max=max),
                source=source_map(min=min, max=max),
            )
        )

    def topology(
        self,
        *,
        faces: int | None = None,
        edges: int | None = None,
        vertices: int | None = None,
        id: str | None = None,
    ) -> Part:
        """Modelled face, edge and vertex counts. **OCCT tier only.**

        Constrain any subset; an omitted axis is simply not claimed.

        This is the one check in v0 that a tier cannot answer, and that is the
        point of having it. On build123d or CadQuery it compares real modelled
        topology; on OpenSCAD it reports `unsupported` with `requires: "occt"`,
        because a triangle mesh has faces only in the sense that a mosaic has
        colours. Reporting a triangle count here is the PartCAD failure (D12) and
        is refused structurally, by the mesh backend not declaring the capability
        at all.

        So a contract carrying a `topology` check is portable in the sense that
        matters — it means the same thing everywhere, and says so where it cannot
        be evaluated. It is not portable in the sense of turning green
        everywhere, and a part that needs it to pass belongs on a BREP engine.
        """
        if faces is None and edges is None and vertices is None:
            raise ContractError(
                "topology() must constrain at least one of faces, edges or vertices; "
                "a check that claims nothing cannot pass"
            )
        return self._add(
            CheckSpec(
                id=id or "topology",
                kind="topology",
                phase=GEOMETRY,
                limit=Limit(equals=(faces, edges, vertices)),
            )
        )

    def hole_diameter(
        self, d: float, *, count: int = 1, tol: float | None = None, id: str | None = None
    ) -> Part:
        """Exactly `count` cylindrical bores of diameter `d` exist. **OCCT tier
        only** — a triangle mesh has no cylindrical face, and fitting one to
        the facets recovers a confident wrong number in the unsafe direction.

        There are no selectors (SPEC-contract.md 8), so this is a count claim
        over *detected* bores, not an assertion about a named hole: a bore is a
        full-circle inward cylindrical surface over one contiguous axial span.
        A counterbore counts once per diameter (each portion is a real seat), a
        concave fillet and a half-round groove do not count at all, and two
        aligned holes through two clevis lugs count twice.

        `tol` is the acceptance half-width from the drawing callout (Ø8 ±0.1 →
        `tol=0.1`). Omitted, the band is the comparison epsilon — "modelled
        exactly as drawn" — which is the right default for CAD-as-code, where
        the model is the nominal geometry, not a measured article.
        """
        if not isinstance(d, int | float) or not math.isfinite(d) or d <= 0:
            raise ContractError(f"hole_diameter needs d > 0 (got {d!r})")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ContractError(
                f"hole_diameter needs count >= 1 (got {count!r}); a claim that zero "
                f"holes exist is a keep_out, not a hole_diameter"
            )
        if tol is not None and (
            not isinstance(tol, int | float) or not math.isfinite(tol) or tol <= 0
        ):
            raise ContractError(f"hole_diameter tol must be > 0 when given (got {tol!r})")
        band = float(tol) if tol is not None else epsilon(float(d))
        return self._add(
            CheckSpec(
                id=id or f"hole_d{d:g}".replace(".", "_"),
                kind="hole_diameter",
                phase=GEOMETRY,
                limit=Limit(min=float(d) - band, max=float(d) + band),
                hole={"d": float(d), "count": count},
                source=source_map(d=d, tol=tol),
            )
        )

    def bolt_circle(
        self, d: float, *, count: int, bcd: float, tol: float | None = None, id: str | None = None
    ) -> Part:
        """The mounting-interface callout as one check: exactly `count` bores
        of diameter `d`, axes parallel, centres on one circle of diameter
        `bcd`. **OCCT tier only**, like `hole_diameter`, whose bore detection
        this builds on.

        Subset semantics, consistent with `hole_diameter`'s: the claim is that
        such a circle of holes *exists*, so an unrelated Ø`d` bore elsewhere on
        the part does not break it — but a fifth hole ON the claimed circle
        does, because "4×" is a count, not a minimum. `tol` is the positional
        acceptance band on the circle diameter; omitted, it is the comparison
        epsilon (modelled exactly as drawn). The bores' own diameters always
        match at the comparison epsilon — a toleranced diameter claim belongs
        to `hole_diameter`, and blurring the two would let a wrong-size hole
        satisfy a position claim.
        """
        if not isinstance(d, int | float) or not math.isfinite(d) or d <= 0:
            raise ContractError(f"bolt_circle needs d > 0 (got {d!r})")
        if not isinstance(count, int) or isinstance(count, bool) or count < 2:
            raise ContractError(
                f"bolt_circle needs count >= 2 (got {count!r}); one hole has no "
                f"circle — that claim is hole_diameter's"
            )
        if not isinstance(bcd, int | float) or not math.isfinite(bcd) or bcd <= d:
            raise ContractError(
                f"bolt_circle needs bcd > d (got bcd={bcd!r}, d={d!r}); holes wider "
                f"than their own circle would overlap at its centre"
            )
        if tol is not None and (
            not isinstance(tol, int | float) or not math.isfinite(tol) or tol <= 0
        ):
            raise ContractError(f"bolt_circle tol must be > 0 when given (got {tol!r})")
        if tol is not None and tol > d:
            # A band wider than the hole itself is not a position claim: it
            # makes the callout ambiguous, and an ambiguous band is one a
            # cherry-picked circle centre can satisfy on geometry the drawing
            # rejects (PR #89 review, blocker 2).
            raise ContractError(
                f"bolt_circle tol must not exceed d (got tol={tol!r}, d={d!r}); a "
                f"positional band wider than the hole is not a position claim"
            )
        band = float(tol) if tol is not None else epsilon(float(bcd))
        return self._add(
            CheckSpec(
                id=id or f"bolt_circle_{count}x_d{d:g}".replace(".", "_"),
                kind="bolt_circle",
                phase=GEOMETRY,
                limit=Limit(min=float(bcd) - band, max=float(bcd) + band),
                hole={"d": float(d), "count": count, "bcd": float(bcd)},
                source=source_map(d=d, bcd=bcd, tol=tol),
            )
        )

    def fillet_radius(
        self, *, min: float | None = None, max: float | None = None, id: str | None = None
    ) -> Part:
        """Every blend on the part is within these radius bounds. **OCCT tier
        only.** `min=` is the machinability claim — no blend tighter than the
        tool that must cut it.

        A blend is any partial-wrap cylindrical surface, either orientation:
        convex-corner rounds, concave-corner fillets — and, deliberately, slot
        ends and grooves, which nothing at the surface level distinguishes
        from fillets and which constrain the tool identically. Full-wrap
        surfaces (bores, bosses) are `hole_diameter`'s business and never
        count. A part with NO blends fails rather than passing vacuously: a
        claim about every blend needs at least one, and an author who wants no
        constraint on an unfilleted part simply does not declare the check.
        """
        if min is None and max is None:
            raise ContractError(
                "fillet_radius() must bound min, max or both; a check that "
                "claims nothing cannot pass"
            )
        for name, value in (("min", min), ("max", max)):
            if value is not None and (
                not isinstance(value, int | float) or not math.isfinite(value) or value <= 0
            ):
                raise ContractError(f"fillet_radius {name} must be > 0 (got {value!r})")
        return self._add(
            CheckSpec(
                id=id or "fillet_radius",
                kind="fillet_radius",
                phase=GEOMETRY,
                limit=Limit(min=min, max=max),
                source=source_map(min=min, max=max),
            )
        )

    def keep_out(self, region: Region, *, shell: float, id: str | None = None) -> Part:
        """The part must be empty inside `region` — a bolt hole, a slot, a
        wrench clearance — AND some material must lie within `shell` mm of it.

        The shell is mandatory because the naive claim is vacuous: "no material
        here" is satisfied perfectly by a part with the material deleted, which
        is exactly the silent green this tool exists to prevent. Requiring the
        shell to not be entirely empty makes an absent part — and a hole whose
        clearance exceeds `shell` everywhere — fail rather than pass.

        What this deliberately does not claim: shape. A hole oversize in one
        direction only (an oval through a round keep-out) passes, because
        material still lies within the shell on the tight sides. Roundness is a
        `hole_diameter` claim, not a spatial one. See SPEC-contract.md 4.4.
        """
        return self._add(self._region_spec("keep_out", region, shell, id))

    def keep_in(self, region: Region, *, shell: float, id: str | None = None) -> Part:
        """The part must be solid throughout `region` — a boss, a pin, a
        bearing seat — AND its `shell` mm surround must not be entirely solid.

        The shell is the mirror of `keep_out`'s: "material everywhere here" is
        satisfied perfectly by an unbounded solid block, so a keep-in without it
        proves a feature no better than a brick would. Requiring some emptiness
        within `shell` of the region makes the brick — and a feature oversize by
        more than `shell` in every direction — fail. See SPEC-contract.md 4.4.
        """
        return self._add(self._region_spec("keep_in", region, shell, id))

    def _region_spec(self, kind: str, region: Region, shell: float, id: str | None) -> CheckSpec:
        if not isinstance(region, BoxRegion | CylinderRegion):
            raise ContractError(
                f"{kind}() takes a region from partspec.region "
                f"(region.box(...) or region.cylinder(...)), not {type(region).__name__}"
            )
        if not isinstance(shell, int | float) or not math.isfinite(shell) or shell <= 0:
            raise ContractError(
                f"{kind}() needs shell > 0 (got {shell!r}); the shell is what makes "
                f"an absent feature fail instead of vacuously passing"
            )
        return CheckSpec(
            id=id or kind, kind=kind, phase=GEOMETRY, region=region, shell=float(shell)
        )

    # -- internals ---------------------------------------------------------

    def _add(self, spec: CheckSpec) -> Part:
        clash = next((e for e in self.checks if e.id == spec.id), None)
        if clash is not None:
            # A residual collision (e.g. a shared 60-char prefix surviving
            # truncation) names both claims, not just "two checks of the same
            # kind" -- the reader must see WHICH two aliased.
            both = (
                f" (from {clash.expr!r} and {spec.expr!r})"
                if clash.expr is not None and spec.expr is not None
                else ""
            )
            raise ContractError(
                f"duplicate check id {spec.id!r}{both}; pass id= to distinguish two checks "
                f"of the same kind (ids are the join key a report diff relies on)"
            )
        self.checks.append(spec)
        return self

    def __repr__(self) -> str:
        return f"<Part {self.id!r} {self.source.engine} checks={len(self.checks)}>"


_OPERATOR_TOKENS = (
    ("<=", "le"),
    (">=", "ge"),
    ("==", "eq"),
    ("!=", "ne"),
    ("<", "lt"),
    (">", "gt"),
)
"""Two-char operators first, or `<=` would token as `lt` + a stray `=`."""


def _slug(expr: str) -> str:
    """A stable, readable id derived from an expression.

    Comparison operators map to distinct tokens rather than collapsing to
    `_`: `x > 5` and `x < 5` are opposite claims and used to derive the same
    id, so a bracketing pair of bounds — the most ordinary contract there is —
    was refused as a duplicate, with an error blaming "two checks of the same
    kind" (#38). The id is the join key a report diff relies on, so two
    different claims must never alias.
    """
    for op, token in _OPERATOR_TOKENS:
        expr = expr.replace(op, f" {token} ")
    keep = [c if c.isalnum() else "_" for c in expr]
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:60] or "requires"
