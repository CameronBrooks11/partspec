"""ISO 15 boundary dimensions for radial deep-groove ball bearings.

The worked example this table exists for is F16: the dogfood `bearing(608)`
measured 22.5 mm across the outer race where ISO 15 places a 608 at 22.0 —
and finding that required a human who knew the standard. With the table, the
contract is an import:

    from partspec.refs import iso15

    seat = iso15.bearing(608)
    p.hole_diameter(seat.od, tol=0.05)   # the bearing seat bore

Values are the (bore d, outside D, width B) boundary dimensions in mm — the
envelope every conforming bearing of that designation fits, which is exactly
what a seat or a shaft interfaces with. They are dimensional facts, published
in every manufacturer catalogue; per the scope policy this module cites the
standard and reproduces nothing else from it.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..provenance import Referenced
from ..status import ContractError, short_repr

if TYPE_CHECKING:
    from ..contract import Part

__all__ = ["Bearing", "bearing", "seat"]

_STANDARD = "ISO 15"

# designation -> (bore d, outside D, width B), mm
_TABLE: dict[int, tuple[float, float, float]] = {
    # 62x miniature series
    623: (3.0, 10.0, 4.0),
    624: (4.0, 13.0, 5.0),
    625: (5.0, 16.0, 5.0),
    626: (6.0, 19.0, 6.0),
    627: (7.0, 22.0, 7.0),
    628: (8.0, 24.0, 8.0),
    629: (9.0, 26.0, 8.0),
    # 60x
    608: (8.0, 22.0, 7.0),
    609: (9.0, 24.0, 7.0),
    # 60xx (dimension series 10)
    6000: (10.0, 26.0, 8.0),
    6001: (12.0, 28.0, 8.0),
    6002: (15.0, 32.0, 9.0),
    6003: (17.0, 35.0, 10.0),
    6004: (20.0, 42.0, 12.0),
    6005: (25.0, 47.0, 12.0),
    6006: (30.0, 55.0, 13.0),
    # 62xx (dimension series 02)
    6200: (10.0, 30.0, 9.0),
    6201: (12.0, 32.0, 10.0),
    6202: (15.0, 35.0, 11.0),
    6203: (17.0, 40.0, 12.0),
    6204: (20.0, 47.0, 14.0),
    6205: (25.0, 52.0, 15.0),
}


@dataclass(frozen=True, slots=True)
class Bearing:
    """One designation's boundary envelope. Every field is `Referenced`."""

    designation: int
    bore: Referenced
    od: Referenced
    width: Referenced


def bearing(designation: int) -> Bearing:
    """The boundary dimensions of a deep-groove ball bearing designation.

    Annotated `int` because that is what a caller should pass and what a type
    checker should hold them to. The RUNTIME is deliberately wider: the lookup
    accepts anything that hashes equal to a table key, so `numpy.int64`,
    `Decimal(608)` and the `numpy.float64` a pandas column with one missing
    value produces all resolve. Narrowing the runtime to the annotation broke
    each of those in turn (rounds 1 and 2 of #240's review); narrowing the
    annotation to the runtime would give up type checking for the case that
    matters. The tests that exercise the wider set carry a narrow ignore.
    """
    # Ask the LOOKUP first, guarded — do not pre-screen the type.
    #
    # The membership test hashes its operand, so an unhashable designation died
    # with `cannot use 'list' as a dict key`: the implementation detail that
    # `_TABLE` is a dict, offered as the diagnosis (#199). Two attempts at a
    # type pre-screen each traded that crash for a narrowing, because a dict
    # lookup does not require the type a pre-screen names — it requires
    # hashability and equality. `isinstance(x, int)` rejected `numpy.int64`;
    # `numbers.Integral` then rejected `Decimal`, `Fraction`, `float` and
    # `numpy.float64`, all of which hash equal to an int key and all of which
    # worked before (rounds 1 and 2 of #240's review — the second is the
    # `pd.read_csv` column with one missing value, dtype float64).
    #
    # Catching TypeError around the lookup is the only test that asks the
    # question the lookup actually asks. Everything that worked still works,
    # and nothing reaches a raw TypeError.
    try:
        found = designation in _TABLE
    except TypeError:
        found = False
    if not found:
        known = ", ".join(str(d) for d in sorted(_TABLE))
        # A wrong TYPE and an unknown NUMBER are different mistakes: a dict is
        # not an unknown designation, it is not a designation. `bool` is
        # excluded from the number branch because `isinstance(True, int)` is
        # True in Python and `True` is not a designation — the trap
        # `scad_literal` and `runner._number` each carry a note about.
        # `Number`, not `Integral`. The acceptance path stopped pre-screening
        # the type and the WORDING kept doing it, so a designation this
        # function will happily look up — `numpy.float64`, `Decimal` — was told
        # its type was wrong when the number simply was not in the table. That
        # is a worse diagnosis than main gave for the pandas-column case the
        # whole fix argues from (round-3 review of #240): a typo'd designation
        # in a float64 column needs "unknown", not "not an integer".
        numeric = isinstance(designation, numbers.Number) and not isinstance(designation, bool)
        what = (
            "unknown designation"
            if numeric
            else f"a designation is an integer, not {type(designation).__name__}"
        )
        raise ContractError(
            f"iso15.bearing({short_repr(designation)}): {what} (this table carries: {known})"
        )
    bore, od, width = _TABLE[designation]

    def ref(value: float, field: str) -> Referenced:
        return Referenced(
            value, {"standard": _STANDARD, "subject": str(designation), "field": field}
        )

    return Bearing(
        designation=designation,
        bore=ref(bore, "bore"),
        od=ref(od, "outside_diameter"),
        width=ref(width, "width"),
    )


def seat(
    part: Part, designation: int, *, tol: float = 0.05, instance: str | None = None, count: int = 1
) -> Part:
    """Declare a bearing seat: a bore at the designation's outside diameter.

    A fragment (SPEC-contract.md 11): declares checks only, ids namespaced
    `iso15:*` (`iso15:608:left:seat` with `instance="left"`). The nominal is
    the standard's and carries its citation; `tol` is the designer's fit
    allowance and stays theirs. `count` is the TOTAL number of seat-diameter
    bores on the part — `hole_diameter` counts the whole part, so two 608
    seats pass `count=2` on both calls.
    """
    b = bearing(designation)
    suffix = f"{instance}:seat" if instance else "seat"
    part.hole_diameter(b.od, count=count, tol=tol, id=f"iso15:{designation}:{suffix}")
    return part
