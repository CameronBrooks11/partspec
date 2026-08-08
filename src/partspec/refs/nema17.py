"""NEMA 17 stepper-motor mounting interface (NEMA ICS 16).

The dogfood kept these four numbers as hand-maintained constants in a bracket
model; they are the mounting facts every NEMA 17 bracket on earth shares. The
`mount` fragment declares the interface onto a part in one call:

    from partspec.refs import nema17

    def bracket() -> Part:
        p = Part("stepper-bracket", build123d("bracket.py"))
        nema17.mount(p)
        ...

The split of authority is deliberate: the *pattern* — where the holes are — is
the standard's, and its checks carry the citation. The *clearance diameters* —
how big the designer drilled them — are design choices, taken as arguments and
left unattributed: a fragment must never launder the designer's numbers into a
standard's.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..provenance import Referenced

if TYPE_CHECKING:
    from ..contract import Part

__all__ = ["BOLT_CIRCLE_DIAMETER", "FACEPLATE", "HOLE_SQUARE", "PILOT_BOSS", "SHAFT", "mount"]

_STANDARD = "NEMA ICS 16"


def _ref(value: float, field: str, note: str | None = None) -> Referenced:
    source = {"standard": _STANDARD, "subject": "NEMA 17", "field": field}
    if note:
        source["note"] = note
    return Referenced(value, source)


HOLE_SQUARE = _ref(31.0, "mounting_hole_square_side")
"""The four mounting holes sit on the corners of a 31.0 mm square."""

BOLT_CIRCLE_DIAMETER = _ref(
    31.0 * math.sqrt(2),
    "bolt_circle_diameter",
    note="circumscribed diameter of the 31.0 mm square hole pattern (31.0 x sqrt 2); "
    "the derivation is this table's, the square is the standard's",
)
"""The square's corners as a bolt circle — what `bolt_circle` adjudicates.

The derivation is stated in the citation rather than silently performed at the
call site, where arithmetic would (correctly) shed the attribution: a table may
derive and say so; a call site deriving silently owns the result.
"""

PILOT_BOSS = _ref(22.0, "pilot_boss_diameter")
"""The locating boss a bracket's pilot bore must clear."""

FACEPLATE = _ref(42.3, "faceplate_width")

SHAFT = _ref(5.0, "shaft_diameter")


def mount(part: Part, *, bolt_holes: float = 3.4, pilot: float = 22.3, tol: float = 0.1) -> Part:
    """Declare the NEMA 17 mounting interface on a bracket.

    A fragment declares checks and nothing else (SPEC-contract.md 11): no
    geometry, no measuring, no checks invented from the part. Ids are
    namespaced `nema17:*`, so two fragments never collide and `diff` joins
    stably across runs.

    `bolt_holes` and `pilot` are the *bracket's* clearance diameters — the
    designer's numbers, deliberately unattributed. The pattern they must sit
    on is the standard's, and carries it.
    """
    part.hole_diameter(pilot, count=1, tol=tol, id="nema17:pilot")
    part.bolt_circle(
        bolt_holes, count=4, bcd=BOLT_CIRCLE_DIAMETER, tol=tol, id="nema17:bolt_circle"
    )
    return part
