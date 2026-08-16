"""ISO metric screw threads: the coarse-pitch series and the basic profile.

`partspec.refs` carried bearings and steppers but not the most widely used
dimensional standard in mechanical CAD, so an author asserting anything about a
threaded feature had to supply the numbers themselves. In the fleet-01 adoption
study all three arm-C replicates independently hand-wrote an ISO thread module
before they could state a single limit, and `cli.py`'s own advisory — *"cite the
source instead: partspec.refs for a standard it carries"* — could only ever
route them to the hand-rolled path (#194).

Every value here is checked against the primary documents. The free iTeh
previews of ISO 261:1998 and ISO 724:2023 carry the complete Table 2 and
Table 1, so this table is transcribed from the standards rather than
triangulated from secondary publishers — which is what an earlier draft did,
and it cost three wrong rows.

    from partspec.refs import iso_metric_thread as iso_thread

    m8 = iso_thread.coarse(8)
    p.hole_diameter(m8.minor_internal, tol=0.05)   # the drilled hole before tapping
    p.param("pitch", equals=m8.pitch)

## What this carries, and what it deliberately does not

**The size, not the fit.** `SPEC-contract.md` §10.1 puts a standard's
tolerancing tables out of scope, so ISO 965's 6g/6H classes are not here — see
#246, which argues that policy question on its own merits rather than settling
it inside a data module. What is here is the diameter/pitch series and the basic
profile geometry, which are dimensional interface facts in exactly the sense
§10.1 means: a bolt's nominal size is what a hole, a nut and a tap all interface
with.

The fit is the designer's, the same way `iso15` carries a bearing's boundary
envelope and leaves `tol=` to the author.

## Why the derived diameters still carry a citation

§10 rule 2 says arithmetic sheds attribution, because "a number the standard
never printed is the author's". The basic pitch and minor diameters are the
exception that proves it: ISO 68-1 defines the profile these relations come
from, ISO 724 tabulates the results, and nothing of the author's enters the
computation — both inputs are the standard's and so is the operation. That is
not laundering authority, it is quoting it. `m8.minor_internal + 0.1` is a plain
float, as it should be.

They are computed rather than transcribed on purpose, and the argument is
simply that the standard prints six significant figures where a double holds
seventeen. ISO 724 clause 5 gives `0,649 519`, `1,082 532` and `1,226 869`;
carrying those costs 4e-7 mm at M8 and rather more at M64, for no benefit,
when `sqrt(3)/2` is exact and in the stdlib.

(An earlier draft argued this from the prior art instead, and the review
falsified both examples. The "1 um" error attributed to one fleet module is
that module's own disclosed tolerance BAND, chosen and documented; the largest
actual discrepancy anywhere in the three is 0.435 um. And the other did not
truncate a coefficient — it doubled ISO 68-1's own printed `H1 = 0,541 265 877`
and said so in a comment. Neither is a mistake. Attacking the standard's
printed figures as sloppy transcription was the mistake.)

The values are therefore the **exact** dimensions. ISO 724 tabulates the same
quantities rounded to three decimals; the two agree to within 0.48 um, and
`test_every_row_matches_iso_724_table_1` pins all 120 of them against the
standard's printed table.

## Citations

Each standard is cited for the thing it actually says, which the prior art got
wrong in two of three cases:

- **ISO 261** — the diameter/pitch combinations, and nothing else. Its clause 1
  says so in as many words: *"Basic dimensions are given in ISO 724. For
  tolerances see ISO 965-1."*
- **ISO 68-1** — the profile itself: the fundamental triangle height `H`.
- **ISO 724** — the three relations, verbatim from clause 5, and the table of
  values they produce.

`d2`, `D1` and `d3` are ISO 724's **basic dimensions** — that is the title of
its clause 5 and of Table 1 — but they are not all on ISO 68-1's *basic
profile*, and an earlier draft of this docstring said they were. ISO 724:2023's
Scope is explicit: *"The values refer to the design profiles according to ISO
68-1."* Its clause 4 defines `d3` (and `H1`, and `h3`) as quantities **on the
design profile**; the basic profile has one minor diameter, not two. Getting
that wrong is the same mis-attribution this module criticises in the prior art,
so it is worth being exact: **basic dimension, design profile.**
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..provenance import Referenced
from ..status import ContractError, short_repr

if TYPE_CHECKING:
    from ..contract import Part

__all__ = ["Thread", "coarse", "sizes", "tapped_hole"]

# Dated, because the edition is load-bearing. `d3` exists only from ISO
# 724:2023 — its foreword records "the values and formula for the minor
# diameter of external thread, d3, have been added in Table 1" — and ISO
# 261:1998 normatively references ISO 724:1993, which has no d3 at all. A bare
# "ISO 724" would send a reader following this module's own citation chain to
# an edition that does not contain the number (round 1 of #194's review).
_ISO_261 = "ISO 261:1998"
_ISO_68_1 = "ISO 68-1:2023"
_ISO_724 = "ISO 724:2023"

# Height of the fundamental triangle, per pitch. Derived, never transcribed:
# `sqrt(3)/2` to the last bit a double holds, against the 9- and 10-digit
# truncations the fleet modules carry.
_H_PER_PITCH = math.sqrt(3) / 2

# The profile places each diameter a fixed fraction of H off the nominal
# (ISO 68-1). Written as the fractions the standard states rather than as
# decimal coefficients, so the arithmetic is checkable against the figure.
_D2_PER_PITCH = 2 * (3 * _H_PER_PITCH / 8)  # pitch diameter: 3H/8 off each flank
_D1_PER_PITCH = 2 * (5 * _H_PER_PITCH / 8)  # internal minor: 5H/8
_D3_PER_PITCH = 2 * (17 * _H_PER_PITCH / 24)  # external minor: 17H/24

# nominal diameter -> (coarse pitch, ISO 261 choice)
#
# Transcribed from ISO 261:1998 Table 2, column "coarse", and cross-checked
# row by row against ISO 724:2023 Table 1. Every one of the 40 rows and all
# 120 derived diameters were verified against the primary documents; the first
# draft of this table came from memory and had three defects, all of which the
# standard settles (round 1 of #194's review):
#
#   - M7 is SECOND choice (Table 2 Col. 2), not third.
#   - The coarse series ends at M68, not M64. M68x6 is Col. 2; M72 is the
#     first diameter Table 2 gives no coarse pitch at all.
#   - M1, M1.1, M1.2 and M1.4 have coarse pitches (0.25, 0.25, 0.25, 0.3) and
#     two of them are first choice. They were simply missing.
#
# The rule for what is here is exactly "the diameters ISO 261 gives a coarse
# pitch for" — no more, and no less. That is not the same as "every diameter
# ISO 261 lists": M5.5, M15, M17, M25, M26, M28, M32, M35, M38, M40, M50,
# M55, M58, M62, M65 and M70 are all in Table 2 with fine pitches only, and
# `coarse()` refusing them is correct rather than an omission.
#
# The choice rank is itself a dimensional fact: ISO 261 ranks its diameters
# first, second and third preference, and an author picking a fastener should
# know that M14 exists but M16 is the one to reach for. `sizes(choice=1)` is
# how a caller asks.
_COARSE: dict[float, tuple[float, int]] = {
    1.0: (0.25, 1),
    1.1: (0.25, 2),
    1.2: (0.25, 1),
    1.4: (0.3, 2),
    1.6: (0.35, 1),
    1.8: (0.35, 2),
    2.0: (0.4, 1),
    2.2: (0.45, 2),
    2.5: (0.45, 1),
    3.0: (0.5, 1),
    3.5: (0.6, 2),
    4.0: (0.7, 1),
    4.5: (0.75, 2),
    5.0: (0.8, 1),
    6.0: (1.0, 1),
    7.0: (1.0, 2),
    8.0: (1.25, 1),
    9.0: (1.25, 3),
    10.0: (1.5, 1),
    11.0: (1.5, 3),
    12.0: (1.75, 1),
    14.0: (2.0, 2),
    16.0: (2.0, 1),
    18.0: (2.5, 2),
    20.0: (2.5, 1),
    22.0: (2.5, 2),
    24.0: (3.0, 1),
    27.0: (3.0, 2),
    30.0: (3.5, 1),
    33.0: (3.5, 2),
    36.0: (4.0, 1),
    39.0: (4.0, 2),
    42.0: (4.5, 1),
    45.0: (4.5, 2),
    48.0: (5.0, 1),
    52.0: (5.0, 2),
    56.0: (5.5, 1),
    60.0: (5.5, 2),
    64.0: (6.0, 1),
    68.0: (6.0, 2),
}


@dataclass(frozen=True, slots=True)
class Thread:
    """One coarse-series size. Every dimension is `Referenced`.

    `minor_internal` (ISO 724's `D1`, tabulated under "flat crest") is the one
    most contracts want: it is the minor diameter of a tapped hole, and so the
    diameter a modelled hole is checked against. `minor_external` (`d3`, "rounded
    root") is the root of the bolt, which is a different number — the design
    profile truncates the two by `5H/8` against `17H/24` — and confusing them is
    an `H/6 = 0.1443·P` error, 0.180 mm at M8.
    """

    designation: str
    choice: int
    nominal: Referenced
    pitch: Referenced
    height: Referenced
    pitch_diameter: Referenced
    minor_internal: Referenced
    minor_external: Referenced


def sizes(*, choice: int | None = None) -> tuple[float, ...]:
    """The nominal diameters this table carries, ascending.

    `choice` filters to one ISO 261 preference rank; omitted, all of them.

    An unknown rank REFUSES rather than returning nothing. §10.1's "a table
    must not guess" cuts both ways: an empty tuple for `choice=4` reads as
    "ISO 261 ranks no diameters fourth", which is a statement, and a silently
    wrong one. `choice=True` was worse — `True == 1`, so it returned the entire
    first-choice list.
    """
    if choice is None:
        return tuple(sorted(_COARSE))
    if isinstance(choice, bool) or choice not in (1, 2, 3):
        raise ContractError(
            f"iso_metric_thread.sizes(choice={short_repr(choice)}): ISO 261 ranks "
            f"diameters first, second or third choice — pass 1, 2 or 3, or omit "
            f"it for all of them"
        )
    return tuple(sorted(d for d, (_, c) in _COARSE.items() if c == choice))


def coarse(nominal: float) -> Thread:
    """The coarse-pitch thread at a nominal diameter, e.g. `coarse(8)` for M8.

    Annotated `float` because that is what a caller should pass. The runtime is
    deliberately wider, for the reasons `iso15.bearing` sets out at length: the
    lookup accepts anything hashing equal to a key, so `8`, `8.0`,
    `numpy.float64(8)` and `Decimal(8)` all resolve. Ask the lookup, never
    pre-screen the type.
    """
    # `bool` BEFORE the lookup, not after. `isinstance(True, int)` is True and
    # `hash(True) == hash(1)`, so once M1 joined the table `coarse(True)`
    # returned a whole M1 thread — an answer, silently, to a question nobody
    # asked. The first draft put this test on the failure path, where it could
    # only pick the wording of an error already being raised, and the table had
    # no 1.0 key to expose it (round 1 of #194's review). The missing-sizes fix
    # and this one are coupled: either alone ships a wrong answer.
    d = 0.0
    if isinstance(nominal, bool):
        found = False
    else:
        try:
            found = nominal in _COARSE
            if found:
                # Inside the guard, because the CONVERSION can refuse what the
                # lookup accepted: `complex(8)` hashes and compares equal to
                # `8`, passes the membership test, and then died in `float()`
                # with a raw `TypeError` — the exact defect #240 spent three
                # rounds removing from `iso15.bearing`, reintroduced here by
                # adding a conversion the guard did not cover.
                d = float(nominal)
        except TypeError:
            found = False
    if not found:
        known = ", ".join(f"M{_label(d)}" for d in sorted(_COARSE))
        # A wrong TYPE and an unknown DIAMETER are different mistakes, and
        # `bool` belongs with the former: `isinstance(True, int)` is True and
        # `True` is not a diameter.
        # `Number` rather than `Real`, so `Decimal` and `Fraction` — which the
        # lookup resolves — are told the diameter is unknown rather than that
        # their type is wrong. `complex` is excluded despite being a Number:
        # it is not a diameter, and #240's round 3 is the precedent for keeping
        # the wording and the acceptance path saying the same thing.
        numeric = isinstance(nominal, numbers.Number) and not isinstance(nominal, bool | complex)
        what = (
            "no coarse pitch at this diameter"
            if numeric
            else f"a nominal diameter is a number, not {type(nominal).__name__}"
        )
        raise ContractError(
            f"iso_metric_thread.coarse({short_repr(nominal)}): {what} (this table carries: {known})"
        )
    pitch, choice = _COARSE[nominal]
    designation = f"M{_label(d)}"

    def ref(value: float, standard: str, field: str, note: str | None = None) -> Referenced:
        source = {"standard": standard, "subject": designation, "field": field}
        if note is not None:
            source["note"] = note
        return Referenced(value, source)

    # ISO 724 clause 5: the table's values "have been calculated from the
    # following formulae and rounded to the third decimal place". This keeps
    # the unrounded value — up to 0.48 um from the printed one — so the
    # citation has to say that rather than imply the digits were transcribed.
    _EXACT = "exact value of the clause 5 formula; the table rounds to 3 decimals"

    return Thread(
        designation=designation,
        choice=choice,
        nominal=ref(d, _ISO_261, "nominal_diameter"),
        pitch=ref(pitch, _ISO_261, "coarse_pitch"),
        height=ref(_H_PER_PITCH * pitch, _ISO_68_1, "fundamental_triangle_height"),
        pitch_diameter=ref(d - _D2_PER_PITCH * pitch, _ISO_724, "pitch_diameter", _EXACT),
        minor_internal=ref(d - _D1_PER_PITCH * pitch, _ISO_724, "minor_diameter_internal", _EXACT),
        minor_external=ref(d - _D3_PER_PITCH * pitch, _ISO_724, "minor_diameter_external", _EXACT),
    )


def tapped_hole(
    part: Part,
    nominal: float,
    *,
    tol: float = 0.05,
    instance: str | None = None,
    count: int = 1,
) -> Part:
    """Declare a tapped hole at a coarse-series size.

    A fragment (SPEC-contract.md §11): declares checks only, ids namespaced
    `iso_metric_thread:*`. The bound is the basic minor diameter `D1`, which is
    what a modelled tapped hole is drawn at — a thread's crests are almost never
    modelled, and a model that does cut them fails this by design rather than
    silently.

    `tol` is the author's fit allowance and stays theirs; `count` is the TOTAL
    number of bores at this diameter on the part, since `hole_diameter` counts
    the whole part.
    """
    thread = coarse(nominal)
    suffix = f"{instance}:tapped" if instance else "tapped"
    part.hole_diameter(
        thread.minor_internal,
        count=count,
        tol=tol,
        id=f"iso_metric_thread:{thread.designation}:{suffix}",
    )
    return part


def _label(d: float) -> str:
    """`8.0` -> `8`, `2.5` -> `2.5`, so a designation reads as it is written."""
    return f"{d:g}"
