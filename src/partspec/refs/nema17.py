"""NEMA 17 stepper-motor mounting interface (NEMA ICS 16, Table 4, flange 17).

The dogfood kept these numbers as hand-maintained constants in a bracket
model. The `mount` fragment declares the interface onto a part in one call:

    from partspec.refs import nema17

    def bracket() -> Part:
        p = Part("stepper-bracket", build123d("bracket.py"))
        nema17.mount(p)
        ...

**The standard speaks in inches and states the bolt circle directly.** NEMA
ICS 16's flange-17 row gives AJ — the mounting-hole pitch circle — as
1.725 in, the pilot (AK) as 0.8661 in, and BD (flange width) as 1.7 in marked
reference-only. The metric figures every catalogue prints (31 mm hole square,
42.3 mm body) are roundings and conventions derived FROM those, not the
standard's own numbers — this table's first version had that exactly
backwards, cited the catalogue square to the standard, and failed a bracket
built on the standard's own circle (PR #96 review). Values here are exact
conversions of what the document states, with the inch figure in every note.

The split of authority is deliberate: the *pattern* is the standard's and its
checks carry the citation; the *clearance diameters* are design choices, taken
as arguments and left unattributed — a fragment must never launder the
designer's numbers into a standard's.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..provenance import Referenced

if TYPE_CHECKING:
    from ..contract import Part

__all__ = ["BOLT_CIRCLE_DIAMETER", "FACEPLATE", "HOLE_SQUARE", "PILOT_BOSS", "SHAFT", "mount"]

_STANDARD = "NEMA ICS 16"
_SUBJECT = "flange 17 (Table 4)"


def _ref(value: float, field: str, note: str) -> Referenced:
    return Referenced(
        value, {"standard": _STANDARD, "subject": _SUBJECT, "field": field, "note": note}
    )


BOLT_CIRCLE_DIAMETER = _ref(
    1.725 * 25.4,  # 43.815 mm
    "AJ (mounting hole pitch circle)",
    "1.725 in, converted to mm; the standard states the pitch circle directly",
)
"""The mounting-hole pitch circle — the standard's own dimension, undived."""

HOLE_SQUARE = _ref(
    1.725 * 25.4 / math.sqrt(2),  # 30.982 mm
    "mounting_hole_square_side",
    "derived: AJ / sqrt 2 = 30.982 mm; the derivation is this table's — the "
    "standard states the circle, and the 31.0 mm square in catalogues is a "
    "rounding of this figure, not the standard's number",
)
"""The square the holes sit on, as a stated derivation from AJ."""

PILOT_BOSS = _ref(
    0.8661 * 25.4,  # 21.999 mm
    "AK (pilot diameter)",
    "0.8661 in +0/-0.0020, converted to mm",
)
"""The locating boss a bracket's pilot bore must clear."""

FACEPLATE = _ref(
    1.7 * 25.4,  # 43.18 mm
    "BD (square flange width, reference only)",
    "1.7 in; the standard marks BD as an approximate reference value and "
    "leaves the actual width to the manufacturer — catalogue bodies are "
    "commonly 42.3 mm",
)
"""Flange width — reference-only in the standard, and cited as such."""

SHAFT = _ref(0.1969 * 25.4, "U (shaft diameter)", "0.1969 in, converted to mm")


def mount(
    part: Part,
    *,
    bolt_holes: float = 3.4,
    pilot: float = 22.3,
    tol: float = 0.1,
    instance: str | None = None,
    pilot_count: int = 1,
) -> Part:
    """Declare the NEMA 17 mounting interface on a bracket.

    A fragment declares checks and nothing else (SPEC-contract.md 11): no
    geometry, no measuring, no checks invented from the part. Ids are
    namespaced `nema17:*` — `nema17:left:*` with `instance="left"` — so
    fragments never collide silently and `diff` joins stably across runs.

    `bolt_holes` and `pilot` are the *bracket's* clearance diameters — the
    designer's numbers, deliberately unattributed. The pattern they must sit
    on is the standard's, and carries it. One `tol` serves both the pilot
    diameter band and the bolt-circle position band; a design needing them
    split should declare the checks directly.

    Multi-mount brackets: pass a distinct `instance` per mount, and set
    `pilot_count` to the TOTAL number of pilot-diameter bores on the part —
    `hole_diameter` counts the whole part (there are no selectors), so a
    two-motor bracket passes `pilot_count=2` on both calls. The bolt-circle
    claims need no such help: each asserts that its own circle of four
    exists, which stays true with eight holes on two circles.

    The declaration is atomic: an invalid argument raises before any check
    lands, so a corrected retry never trips a collision with the failed
    attempt's leavings.
    """
    from ..contract import Part as _Part

    prefix = f"nema17:{instance}:" if instance else "nema17:"
    staged = _Part(part.id, part.source)
    staged.hole_diameter(pilot, count=pilot_count, tol=tol, id=f"{prefix}pilot")
    staged.bolt_circle(
        bolt_holes, count=4, bcd=BOLT_CIRCLE_DIAMETER, tol=tol, id=f"{prefix}bolt_circle"
    )
    existing = {c.id for c in part.checks}
    for spec in staged.checks:
        if spec.id in existing:
            # Pre-checked so the transfer below cannot half-land: _add would
            # catch this too, but only after the first spec was already in.
            part._add(spec)  # raises the canonical duplicate-id error
    for spec in staged.checks:
        part._add(spec)
    return part
