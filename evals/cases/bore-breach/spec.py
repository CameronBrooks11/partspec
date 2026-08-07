"""FROZEN. The spacer must be one solid with exactly one bore through it."""

from partspec import Part, openscad


def spacer() -> Part:
    p = Part("eval-bore-breach", openscad("model.scad"))
    p.envelope(max=(40.0, 30.0, 6.0))
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
