"""FROZEN. A 40x30x6 plate with an 8 mm bore through the middle."""

import math

from partspec import Part, openscad

PLATE = (40.0, 30.0, 6.0)
BORE_D = 8.0
VOLUME = PLATE[0] * PLATE[1] * PLATE[2] - math.pi * (BORE_D / 2) ** 2 * PLATE[2]


def bored_plate() -> Part:
    p = Part("eval-boolean-order", openscad("model.scad"))
    p.envelope(
        min=(PLATE[0] - 0.1, PLATE[1] - 0.1, PLATE[2] - 0.1),
        max=(PLATE[0] + 0.1, PLATE[1] + 0.1, PLATE[2] + 0.1),
    )
    p.volume(min=VOLUME * 0.98, max=VOLUME * 1.02)
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
