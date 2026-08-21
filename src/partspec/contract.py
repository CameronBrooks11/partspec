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
from .status import ContractError, Limit, epsilon, short_repr

__all__ = [
    "DIMENSIONAL_KINDS",
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

BUILD_PHASE_KINDS: frozenset[str] = frozenset({"builds", "empty"})
"""Kinds decided from the BUILD itself, before any backend primitive is asked.

Neither has an entry in `GEOMETRY_KINDS`, because neither has a primitive that
answers it: `builds` is whether the engine produced anything, and `empty` is the
contract declaring that nothing was the intended result (SPEC-contract 4.12).
Both run on either tier, since both are answered from `BuildError` rather than
from geometry.

Held here rather than in `scripts/gen_docs.py` so the table cannot go stale
against the code: the generator reads this set, and its completeness assertion
fails the gate on a kind that appears in neither map. `builds` was hardcoded in
the generator alone, which is the shape #194 caught elsewhere -- one place
knowing a list the code also knows."""


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
    "draft_angle": "draft_angle",
    "self_intersection_free": "self_intersection_free",
    "step_roundtrip": "step_roundtrip",
    "min_wall": "min_wall",
}
"""The closed geometry vocabulary, mapped to the backend primitive that answers
it. `builds` is absent because it is implicit and has no primitive — it is
whether the engine produced anything at all.

These entries have primitives that are **not** on both tiers — the checks that
make the tier difference visible to a contract author rather than merely
documented: `topology`, `hole_diameter`, `bolt_circle`, `fillet_radius`,
`draft_angle`, `self_intersection_free`, `step_roundtrip` and `min_wall`.
`topology` was v0's single deliberate member of that class, and `hole_diameter`
the first of the BREP dimensions it existed to pave the way for; the depth epic
(#136) added the rest.

Deliberately no count in that sentence. It read "topology and hole_diameter are
the entries" long after there were eight, and a test holds the LIST against the
capability sets — a numeral beside the list it counts is a second thing to
forget, which is how the first version rotted.

`keep_out` / `keep_in` map to the primitive that gates them; their evaluation is
composed in the runner from `region_solid` and `intersect_volume` rather than
being one primitive call (SPEC-contract.md 4.4)."""


EXTRA_PRIMITIVES: dict[str, tuple[str, ...]] = {
    "keep_out": ("intersect_volume",),
    "keep_in": ("intersect_volume",),
}
"""Primitives a kind needs BEYOND the one `GEOMETRY_KINDS` records.

The region checks are composed in the runner from `region_solid` AND
`intersect_volume` (SPEC-contract.md 4.4), and only the first is in that map, so
anything deriving a tier from `GEOMETRY_KINDS` alone answers for half the work.
Both are on both tiers today, so nothing reads differently — this exists so the
answer stays right if that stops being true, in the direction that matters: a
table promising `both` for a check the mesh runner refuses tells an author to
write a check that cannot pass.

Held against the runner by `test_the_extra_primitives_match_what_the_runner_calls`
rather than maintained by hand. It was a hand-maintained third copy of a fact
already stated in `runner.py` and in §4.4 when PR #156's review found it, which
is the same shape as the `MEASURANDS` unit column one entry down — and that one
is pinned, so this one is too."""


@dataclass(frozen=True, slots=True)
class Measurand:
    """How a kind's measurement is shaped: scalar or vector, in what unit, and
    whether the answer is exact.

    This is the one part of SPEC-contract §4.2's table that no other code knows.
    The method signature comes from `inspect.signature`, the `kind` from calling
    the method, the tier from `GEOMETRY_KINDS` against the backends' capability
    sets — all derived, so all generated. Shape and unit were derivable from
    nothing, and lived only as prose in the spec, where a test compared two
    hand-maintained copies of the same fact and called that enforcement.

    `unit` is held against reality by
    `test_every_declared_unit_is_the_unit_the_code_emits`: the value here must
    equal the unit the function answering that kind actually attaches. That is
    code against code. Nothing reads the markdown.
    """

    shape: str
    unit: str | None = None
    exact: bool = True
    interval: bool = False
    note: str = ""


MEASURANDS: dict[str, Measurand] = {
    # Parameter phase (§4.1). Neither is a geometry primitive; `requires` carries
    # no measurement at all, which is why `unit` is None rather than empty.
    "requires": Measurand("predicate", note="see §5"),
    "param_range": Measurand("measurement + limit"),
    # Geometry phase (§4.2).
    "builds": Measurand("none"),
    "empty": Measurand("none"),
    "envelope": Measurand("vector", "mm"),
    "watertight": Measurand("bool-valued", "bool"),
    "solid_count": Measurand("scalar", "count"),
    "genus": Measurand("scalar", "count"),
    "cavities": Measurand("scalar", "count"),
    "volume": Measurand("scalar", "mm3", exact=False),
    "area": Measurand("scalar", "mm2", exact=False),
    "topology": Measurand("vector", "count"),
    "keep_out": Measurand("vector", "mm3"),
    "keep_in": Measurand("vector", "mm3"),
    "hole_diameter": Measurand("vector", "mm"),
    "bolt_circle": Measurand("scalar", "mm"),
    "fillet_radius": Measurand("vector", "mm"),
    "draft_angle": Measurand("vector", "deg"),
    "self_intersection_free": Measurand("bool-valued", "bool"),
    "step_roundtrip": Measurand("vector", "rel"),
    "min_wall": Measurand("scalar", "mm", interval=True, note="exact when it collapses"),
}
"""Every kind's measurement shape, keyed by `kind` — not by method, because
`keep_out` and `keep_in` are two methods and `builds` is no method at all.

Held complete in both directions by `scripts/gen_docs.py`'s
`_assert_vocabulary_is_complete`, which `just check` runs: a kind with no entry
here, or an entry naming no kind, fails the gate rather than quietly generating
a table with a hole in it."""


def _region_source(region: Region, shell: float) -> dict[str, dict[str, Any]] | None:
    """The citations a region declaration carries, keyed by the field they came in on.

    A region's numbers reach `checks[].source` like every other bound's
    (SPEC-contract 10). They did not until #250: `Referenced` is a float
    subclass and the geometric validation in `region.py` returned `float(value)`,
    so the citation was flattened one call before this could record it — in a
    tree whose worked example takes a keep-out's diameter straight from
    `refs.nema17`, and whose own docstring calls it the citation exemplar.

    Which fields are offered differs by kind because only the DIMENSIONS are
    citable: a standard vouches for how big a feature is, never for where this
    design puts it, so `at` is deliberately absent — a position is the author's
    even when every number in it came from a table. `shell` is the author's
    tolerance for the same reason, and is included because it is a dimension a
    standard can genuinely vouch for.
    """
    if isinstance(region, BoxRegion):
        return source_map(min=region.min, max=region.max, shell=shell)
    return source_map(d=region.d, h=region.h, shell=shell)


DIMENSIONAL_KINDS = frozenset(
    {
        "param_range",
        "envelope",
        "volume",
        "area",
        "hole_diameter",
        "bolt_circle",
        "fillet_radius",
        "draft_angle",
        "min_wall",
        "keep_out",
        "keep_in",
    }
)
"""The kinds whose limits are numbers an author chose — and so the kinds that
are trivially circularizable: a bound recomputed from the model's own constants
cannot fail however the design moves (#50). Topological kinds (genus,
solid_count, watertight, topology, cavities) are absolute claims, non-circular
by construction, and excluded. The attribution warning (SPEC-contract.md 6)
reads this set."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where the geometry comes from, and what to build it with.

    The engine is declared, never inferred from the file extension: a `.py` could
    be either Python engine, and guessing is the kind of implicitness this
    project exists to remove.
    """

    engine: str  # "openscad" | "build123d" | "cadquery"
    path: Path
    """The model file. A relative path is resolved against the **contract's**
    directory, not the working directory, so a contract means the same thing
    from wherever it is run; an absolute path is left alone."""
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
    """A build123d source: a module partspec imports and calls for its part.

    `method` names the callable to call; without it, partspec looks for
    `make_part`. It is invoked as `method(**params)` and whatever it returns
    is the part — a build123d object, or anything exposing the same `.wrapped`
    OCCT shape.

    A *callable* rather than a module-level `result`, because `params` is the
    whole point: a part built as an import side effect cannot be
    parameterised, so a contract could declare a family and get one part.
    """
    return Source(engine="build123d", path=Path(path), params=params, method=method)


def cadquery(path: str | Path, /, method: str | None = None, **params: Any) -> Source:
    """A CadQuery source: a module partspec imports and calls for its part.

    Identical in shape to `build123d` — `method` names the callable, default
    `make_part`, invoked as `method(**params)`. A returned `Workplane` is
    reduced over its **whole** stack (several values become a Compound), so a
    `combine=False` build is measured entire rather than by its first solid.

    Note this is not CQGI: CadQuery's own script convention assigns a
    module-level `result` and takes parameters by injection, and neither
    applies here. Export a function.
    """
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
    direction: tuple[float, float, float] | None = None
    """The pull axis for `draft_angle` only, normalised at declaration. Not a
    `Limit`: it is what the claim is measured AGAINST, not a bound on it."""


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
        # The type before the membership test, for `region.cylinder`'s reason
        # (#199): `name not in <dict>` HASHES `name`, so an unhashable value
        # died inside the guard with `cannot use 'list' as a dict key` — and
        # lost #188's traceback trimming on the way out, so the reader got
        # partspec's internal frames as well as its internal data structure.
        # `p.param(["plate_x", "plate_y"], min=1.0)`, bounding two parameters in
        # one call, is at least as plausible a mistake as the `axis=(0, 0, 1)`
        # that motivated the issue. Found by the adversarial review of #240,
        # which swept the public API after the first two sites were fixed.
        if not isinstance(name, str) or name not in self.source.params:
            known = ", ".join(sorted(self.source.params)) or "none"
            what = (
                "is not a declared parameter"
                if isinstance(name, str)
                else f"takes a parameter name, not {type(name).__name__}"
            )
            raise ContractError(f"param({short_repr(name)}) {what} (declared: {known})")
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

    def empty(self, *, id: str | None = None) -> Part:
        """The part is expected to build to NOTHING, and that is the passing result.

        For a **clearance probe** — `intersection() { A; B; }` declared as its
        own part — emptiness is the claim: the two parts share no space. Without
        this, a null result is a build failure and the claim can only be written
        as a bound on a measurement that was never taken, so the good answer was
        the one outcome the tool could not grade (#237).

        Declaring it changes nothing for any other contract. A part that does not
        declare `empty` and builds to nothing still fails, exactly as before —
        for a part contract that IS a real fault, and this does not relax it.

        **A broken probe cannot satisfy it.** An empty result means two different
        things, and on OpenSCAD 2021.01 they are identical downstream: both exit
        1 with `Current top level object is empty.` and write no STL. A misspelt
        module, or an include that did not open, produces geometry that never
        existed to intersect — so the check refuses to be satisfied when the
        engine also reported an unresolved name, and says which one. That is the
        difference between asserting a clearance and laundering a typo into a
        green run.

        The claim is exclusive by nature rather than by rule: there is no mesh to
        measure, so every other geometry check on the part is skipped and the run
        reports `incomplete`. Declare `empty` alone on a probe.
        """
        return self._add(CheckSpec(id=id or "empty", kind="empty", phase=GEOMETRY))

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
        """Total surface area, ungated where `volume` is precondition-gated.

        A sum over the exported triangles is well defined whatever they enclose,
        so this answers on meshes `volume` must refuse — and refusing it too
        would be its own dishonesty (`SPEC-backend.md` §7). That makes it the
        measure for a part that is legitimately not a solid.

        The case worth naming is a **clearance probe**: `intersection() { A; B; }`
        built as its own part. Its three outcomes separate on area and volume
        together — interpenetrating gives a volume, resting-on gives area with no
        volume, and not-touching does not build at all (#237). Measured on
        2021.01: two boxes meeting on a face export four triangles that are
        watertight, so `volume` reads exactly `0.0`; an annular contact exports a
        mesh with 94 non-manifold edges, so `volume` refuses and `area` still
        answers (#238).

        **On such a part the number is TWICE the contact patch.** The sheet has
        two sides and both are exported: a 10 x 10 mm face reads `200.0`. Nothing
        is wrong with it — that is the surface area of a closed zero-thickness
        solid — but a bound written against a hand-computed patch is out by
        exactly 2x, and silently, because both numbers look plausible.
        """
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

    def self_intersection_free(self, *, id: str | None = None) -> Part:
        """The shape does not intersect itself — no sub-shape pair crossing
        where the boundary says it must not. **OCCT tier only** (D14 accepted
        the mesh-side gap rather than a GPL dependency).

        A self-intersecting BREP measures volume and topology plausibly and
        fails downstream — booleans, STEP consumers, slicers — the classic
        silently wrong part. Exact: the kernel analyses, nothing samples.
        The recorded limit: a self-intersection lying within a single
        ANALYTIC surface (a spindle torus) goes undetected and passes; a
        self-overlapping swept face IS caught, as a pair-less fault
        (SPEC-contract.md 4.9).
        """
        return self._add(
            CheckSpec(
                id=id or "self_intersection_free",
                kind="self_intersection_free",
                phase=GEOMETRY,
                limit=Limit(equals=True),
            )
        )

    def min_wall(self, *, min: float, id: str | None = None) -> Part:
        """Every wall of the part is at least `min` mm thick. **OCCT tier
        only** (POST-V0 section 5's condition — a different method on the
        BREP tier — is met; the mesh tier's refusal stands, with the
        executed evidence recorded in SPEC-contract.md 4.11).

        The measurement is a guaranteed interval WITHIN A DECLARED
        MEASURAND (SPEC-contract.md 4.11): the minimum span between
        non-adjacent boundary faces through material, plus certified
        diametric spans of closed analytic faces. Inside it, the kernel's
        exact face-pair minima bound the wall from below, a witnessed
        crossing bounds it from above, a crossing thinner than the bound
        refuses the check as self-contradictory, and a straddling limit
        adjudicates APPROXIMATE — the tool says "I do not know" rather than
        guessing. Outside it — the web beside a drilled hole, a single-face
        fold — is recorded as unmeasured, not silently green. Faces meeting
        at an edge are a modeling feature (a wedge, a corner), never a
        wall; a truncated tip is measured.
        """
        if (
            not isinstance(min, int | float)
            or isinstance(min, bool)
            or not math.isfinite(min)
            or min <= 0
        ):
            raise ContractError(f"min_wall min must be a positive thickness in mm (got {min!r})")
        return self._add(
            CheckSpec(
                id=id or "min_wall",
                kind="min_wall",
                phase=GEOMETRY,
                limit=Limit(min=float(min)),
                source=source_map(min=min),
            )
        )

    def step_roundtrip(self, *, tol: float = 1e-6, id: str | None = None) -> Part:
        """The part survives its own exchange format: written to STEP, read
        back, volume and area within `tol` (relative) and topology counts
        unchanged. **OCCT tier only.**

        STEP is how a part leaves for manufacturing; a shape that degrades
        through its own exchange ships a different part than the one
        verified. `tol` defaults to 1e-6 relative — ~50x above the worst
        delta measured across healthy construction families (a fused
        threaded rod at 1.9e-8; most families sit below 4e-13) and six
        orders below real degradation (an ill-formed solid loses its whole
        volume). The comparison is plain membership — the tol IS the
        tolerance, never epsilon-widened. Topology drift fails regardless
        of `tol`: a count that changed is a different part at any tolerance
        (SPEC-contract.md 4.10).
        """
        if (
            not isinstance(tol, int | float)
            or isinstance(tol, bool)
            or not math.isfinite(tol)
            or tol <= 0
            or tol > 1
        ):
            raise ContractError(
                f"step_roundtrip tol must be a relative delta in (0, 1] (got {tol!r})"
            )
        return self._add(
            CheckSpec(
                id=id or "step_roundtrip",
                kind="step_roundtrip",
                phase=GEOMETRY,
                limit=Limit(max=float(tol)),
            )
        )

    def draft_angle(
        self,
        *,
        min: float,
        direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
        id: str | None = None,
    ) -> Part:
        """Every face's draft is within these bounds, for a mold pulled along
        `direction`. **OCCT tier only.** `min=` is the release claim — no wall
        closer to vertical than the tool can eject (SPEC-contract.md 4.8).

        Draft is measured per face against a two-half parting axis: the angle
        between the face and the pull line, `asin(|n . d|)` — 0 deg for a
        vertical wall, 90 deg for a face square to the pull. The two-half
        convention makes it orientation-independent: a face releases with
        whichever mold half it faces, so tops and bottoms measure 90 and pass
        a min naturally, with no exclusion rule to game. What per-face normals
        cannot see — a feature-level undercut, material blocking release — is
        a recorded gap, not a claim (SPEC-contract.md 4.8).

        Exact on planes, cylinders and cones at any orientation (the extreme
        over a face's wrap is closed-form). A face outside those families
        refuses the whole check rather than passing the subset: a claim about
        every face that skipped one would be silence reading as success.

        There is deliberately no `max=`: under the two-half convention every
        closed solid has a face square to the pull (a cap, at 90 degrees), so
        an every-face maximum is unsatisfiable by construction — and a bound
        adjudicated against anything less than every face would be a silent
        subset pass (PR #141 review, F1).
        """
        if (
            not isinstance(min, int | float)
            or isinstance(min, bool)
            or not math.isfinite(min)
            or min <= 0
            or min > 90
        ):
            raise ContractError(
                f"draft_angle min must be in (0, 90] degrees (got {min!r}); "
                "a min of 0 would pass every face vacuously — the measure is "
                "non-negative by construction"
            )
        try:
            dx, dy, dz = (float(c) for c in direction)
        except (TypeError, ValueError):
            raise ContractError(
                f"draft_angle direction must be a 3-vector of numbers (got {direction!r})"
            ) from None
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if not math.isfinite(norm) or norm == 0.0:
            raise ContractError(
                f"draft_angle direction must be a nonzero finite 3-vector (got {direction!r})"
            )
        return self._add(
            CheckSpec(
                id=id or "draft_angle",
                kind="draft_angle",
                phase=GEOMETRY,
                limit=Limit(min=min),
                source=source_map(min=min),
                direction=(dx / norm, dy / norm, dz / norm),
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
            id=id or kind,
            kind=kind,
            phase=GEOMETRY,
            region=region,
            shell=float(shell),
            source=_region_source(region, shell),
        )

    # -- internals ---------------------------------------------------------

    def _add(self, spec: CheckSpec) -> Part:
        if not isinstance(spec.id, str):
            # `CheckResult.id: str` is an annotation, not an enforcement, and
            # nothing checked it: `p.param("wall", min=2.0, id=3)` was accepted,
            # `check` wrote `"id": 3`, and #148's guard in `diff` then refused
            # that report at exit 64 — blaming the artifact for a mistake made
            # in a contract two commands earlier. The refusal belongs here,
            # beside the other two, so `diff`'s type check is the belt to these
            # braces rather than the only strap (PR #157 review).
            raise ContractError(
                f"check id {spec.id!r} is not a string; ids are the join key a report "
                f"diff relies on (SPEC-report.md 7.1)"
            )
        if spec.id == "builds":
            # The runner emits its own `builds` check for every run; a
            # contract shadowing the id would put two same-id checks in one
            # report (ambiguous for any consumer keying by id) and once let
            # a passing parameter check impersonate a failed build to the
            # render gate (#134).
            raise ContractError(
                "the check id 'builds' is reserved for the runner's own build "
                "check; pass a different id="
            )
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
