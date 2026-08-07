"""FROZEN. The baseplate seats into a 42 mm grid cell.

42.0 mm is the grid pitch of the system this part must drop into. It is not a
property of this model and must not be derived from it.
"""

from partspec import Part, openscad

PITCH = 42.0
THICK = 5.0
TOL = 0.1


def baseplate() -> Part:
    p = Part("eval-standard-mismatch", openscad("model.scad"))
    p.envelope(
        min=(PITCH - TOL, PITCH - TOL, THICK - TOL),
        max=(PITCH + TOL, PITCH + TOL, THICK + TOL),
    )
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
