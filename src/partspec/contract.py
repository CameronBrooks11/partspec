"""The contract: what an author declares about a part.

An ordinary Python module, not a config file and not a DSL (D6). That buys
expressiveness, costs no schema, and — because the contract references the source
rather than being written in the source's language — works identically for an
OpenSCAD `.scad` and a build123d module.

Spec: SPEC-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .status import ContractError, Limit

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
    "genus": "genus",
    "volume": "volume",
    "area": "area",
}
"""v0's closed geometry vocabulary, mapped to the backend primitive that answers
it. `builds` is absent because it is implicit and has no primitive — it is
whether the engine produced anything at all."""


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


def openscad(path: str | Path, /, method: str | None = None, **params: Any) -> Source:
    """An OpenSCAD source. Parameters become `-D name=value` overrides.

    With `method`, they instead become arguments to a call appended to a
    throwaway copy of the source; the file itself is never modified.
    """
    return Source(engine="openscad", path=Path(path), params=params, method=method)


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
        id: str | None = None,
    ) -> Part:
        """A bound on one named parameter.

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
                id=id or "envelope", kind="envelope", phase=GEOMETRY, limit=Limit(min=min, max=max)
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
                id=id or "volume", kind="volume", phase=GEOMETRY, limit=Limit(min=min, max=max)
            )
        )

    def area(
        self, *, min: float | None = None, max: float | None = None, id: str | None = None
    ) -> Part:
        return self._add(
            CheckSpec(id=id or "area", kind="area", phase=GEOMETRY, limit=Limit(min=min, max=max))
        )

    # -- internals ---------------------------------------------------------

    def _add(self, spec: CheckSpec) -> Part:
        if any(existing.id == spec.id for existing in self.checks):
            raise ContractError(
                f"duplicate check id {spec.id!r}; pass id= to distinguish two checks of the "
                f"same kind (ids are the join key a report diff relies on)"
            )
        self.checks.append(spec)
        return self

    def __repr__(self) -> str:
        return f"<Part {self.id!r} {self.source.engine} checks={len(self.checks)}>"


def _slug(expr: str) -> str:
    """A stable, readable id derived from an expression."""
    keep = [c if c.isalnum() else "_" for c in expr]
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:60] or "requires"
