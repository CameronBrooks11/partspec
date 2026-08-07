"""FROZEN. A 20 mm block with a concentric cubic core removed.

The volume states the intent precisely: 20^3 less the core, which fixes the core
at 10 mm. Nothing else in the contract pins it.
"""

from partspec import Part, openscad

BODY = 20.0
CORE = 10.0
VOLUME = BODY**3 - CORE**3


def cored_block() -> Part:
    p = Part("eval-consumed-cut", openscad("model.scad"))
    p.envelope(min=(BODY - 0.1,) * 3, max=(BODY + 0.1,) * 3)
    p.volume(min=VOLUME * 0.99, max=VOLUME * 1.01)
    p.watertight()
    p.solid_count(1)
    return p
