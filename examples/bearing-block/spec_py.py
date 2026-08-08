"""The build123d leg — the parametric family, cited.

One factory per designation, sized from `iso15.bearing(n).od` so the block
follows the standard's number instead of a retyped constant, and
`iso15.seat(p, n)` asserts the bore diameter with the citation in the report.
Deriving the block width from the Referenced OD deliberately sheds the
attribution (arithmetic makes the number the designer's); the seat claim is
where the standard speaks.
"""

from claims import shared_claims

from partspec import Part, build123d
from partspec.refs import iso15


def _seat(designation: int) -> Part:
    od = float(iso15.bearing(designation).od)
    p = Part(
        f"bearing-block-{designation}",
        build123d("block.py", "block", bore_d=od, wall=8.0, depth=12.0),
    )
    shared_claims(p, bore_d=od)
    iso15.seat(p, designation)
    return p


def seat_608() -> Part:
    return _seat(608)


def seat_6000() -> Part:
    return _seat(6000)


def seat_6200() -> Part:
    return _seat(6200)
