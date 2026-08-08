"""The OpenSCAD leg: shared claims only.

The seat-diameter claim is absent here on purpose — a 96-gon bore has no
cylinder diameter, and the mesh tier would refuse `hole_diameter` rather than
fit a circle to facets (the PartCAD failure). What this leg proves is that the
same shared requirements hold on the engine an author may actually be using.
"""

from claims import shared_claims

from partspec import Part, openscad

OD_608 = 22.0  # ISO 15's number; the OCCT leg asserts it WITH the citation


def seat_608() -> Part:
    p = Part("bearing-block-608", openscad("block.scad", bore_d=OD_608, wall=8.0, depth=12.0))
    return shared_claims(p, bore_d=OD_608)
