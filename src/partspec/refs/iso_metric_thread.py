"""ISO metric screw threads: the coarse-pitch series and the basic profile.

`partspec.refs` carried bearings and steppers but not the most widely used
dimensional standard in mechanical CAD, so an author asserting anything about a
threaded feature had to supply the numbers themselves. In the fleet-01 adoption
study all three arm-C replicates independently hand-wrote an ISO thread module
before they could state a single limit, and `cli.py`'s own advisory — *"cite the
source instead: partspec.refs for a standard it carries"* — could only ever
route them to the hand-rolled path (#194).

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

They are computed rather than transcribed on purpose. Every relation is an exact
multiple of `H = (sqrt(3)/2)·P`, so computing them removes a whole class of
error the prior art demonstrates: one fleet module truncated the `5H/4`
coefficient, another carried a minor diameter 1 um off its own formula. A
constant you can derive should never be typed in.

The values are therefore the **exact** basic dimensions. ISO 724 tabulates the
same quantities rounded to three decimals; the two agree to within 0.5 um, and
`test_the_basic_dimensions_match_the_published_table` pins six of them against
figures three independent fleet sourcings agreed on.

## Citations

Each standard is cited for the thing it actually says, which the prior art got
wrong in two of three cases:

- **ISO 261** — the diameter/pitch combinations, and nothing else. Its clause 1
  says so in as many words: *"Basic dimensions are given in ISO 724. For
  tolerances see ISO 965-1."*
- **ISO 68-1** — the basic profile: the fundamental triangle height `H`, and the
  crest and root truncations that place `d2`, `D1` and `d3` on it.
- **ISO 724** — the tabulated basic dimensions these relations produce.
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

__all__ = ["Thread", "coarse", "sizes"]

_ISO_261 = "ISO 261"
_ISO_68_1 = "ISO 68-1"
_ISO_724 = "ISO 724"

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
# The choice is a dimensional fact worth carrying: ISO 261 ranks its diameters
# first, second and third preference, and an author picking a fastener should
# know that M14 exists but M16 is the one to reach for. `sizes(choice=1)` is
# how a caller asks.
#
# Range is M1.6 to M64, where the coarse series ends — above M64 the standard
# tabulates fine pitches only, and there is no coarse column to extrapolate
# into. Third-choice diameters above M12 are omitted rather than guessed.
_COARSE: dict[float, tuple[float, int]] = {
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
    7.0: (1.0, 3),
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
}


@dataclass(frozen=True, slots=True)
class Thread:
    """One coarse-series size. Every dimension is `Referenced`.

    `minor_internal` (ISO 724's `D1`) is the one most contracts want: it is the
    minor diameter of a tapped hole, and so the diameter a modelled hole is
    checked against. `minor_external` (`d3`) is the root of the bolt, which is
    a different number — the profile truncates the two differently, by `5H/8`
    against `17H/24` — and confusing them is a 0.14·P error.
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
    """
    if choice is None:
        return tuple(sorted(_COARSE))
    return tuple(sorted(d for d, (_, c) in _COARSE.items() if c == choice))


def coarse(nominal: float) -> Thread:
    """The coarse-pitch thread at a nominal diameter, e.g. `coarse(8)` for M8.

    Annotated `float` because that is what a caller should pass. The runtime is
    deliberately wider, for the reasons `iso15.bearing` sets out at length: the
    lookup accepts anything hashing equal to a key, so `8`, `8.0`,
    `numpy.float64(8)` and `Decimal(8)` all resolve. Ask the lookup, never
    pre-screen the type.
    """
    try:
        found = nominal in _COARSE
    except TypeError:
        found = False
    if not found:
        known = ", ".join(f"M{_label(d)}" for d in sorted(_COARSE))
        # A wrong TYPE and an unknown DIAMETER are different mistakes, and
        # `bool` belongs with the former: `isinstance(True, int)` is True and
        # `True` is not a diameter.
        numeric = isinstance(nominal, numbers.Number) and not isinstance(nominal, bool)
        what = (
            "no coarse pitch at this diameter"
            if numeric
            else f"a nominal diameter is a number, not {type(nominal).__name__}"
        )
        raise ContractError(
            f"iso_metric_thread.coarse({short_repr(nominal)}): {what} (this table carries: {known})"
        )
    pitch, choice = _COARSE[nominal]
    d = float(nominal)
    designation = f"M{_label(d)}"

    def ref(value: float, standard: str, field: str) -> Referenced:
        return Referenced(value, {"standard": standard, "subject": designation, "field": field})

    return Thread(
        designation=designation,
        choice=choice,
        nominal=ref(d, _ISO_261, "nominal_diameter"),
        pitch=ref(pitch, _ISO_261, "coarse_pitch"),
        height=ref(_H_PER_PITCH * pitch, _ISO_68_1, "fundamental_triangle_height"),
        pitch_diameter=ref(d - _D2_PER_PITCH * pitch, _ISO_724, "basic_pitch_diameter"),
        minor_internal=ref(d - _D1_PER_PITCH * pitch, _ISO_724, "basic_minor_diameter_internal"),
        minor_external=ref(d - _D3_PER_PITCH * pitch, _ISO_724, "basic_minor_diameter_external"),
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
