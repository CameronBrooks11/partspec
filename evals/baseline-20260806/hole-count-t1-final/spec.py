"""FROZEN. A four-hole mounting plate on a 40 mm bolt square."""

from partspec import Part, openscad


def bolt_plate() -> Part:
    p = Part("eval-hole-count", openscad("model.scad"))
    p.envelope(max=(60.0, 60.0, 5.0))
    p.watertight()
    p.solid_count(1)
    p.genus(4)  # four bolt holes straight through
    return p
