"""Contract for the example spacer.

Run it:

    partspec check examples/spacer/spec.py:spacer

The claims below are the kind that usually live in a README and go unchecked:
the bore has to leave enough wall, the part has to fit an envelope, and it has
to come out as one watertight solid with exactly one hole through it.
"""

from partspec import Part, openscad

PLATE = (40.0, 30.0, 6.0)
BORE_D = 8.0
WALL_MIN = 2.0


def spacer() -> Part:
    """The spacer. Its defaults are the master design."""
    p = Part(
        "example-spacer",
        openscad(
            "spacer.scad",
            plate_x=PLATE[0],
            plate_y=PLATE[1],
            plate_z=PLATE[2],
            bore_d=BORE_D,
            wall=WALL_MIN,
        ),
    )

    # Parameter phase — arithmetic over the inputs, no engine needed.
    p.requires("bore_d + 2 * wall <= plate_y")
    p.requires("bore_d > 0")
    p.param("plate_z", min=1.0)

    # Geometry phase.
    p.envelope(max=PLATE)
    p.watertight()
    p.solid_count(1)
    p.genus(1)  # one bore straight through

    return p
