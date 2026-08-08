"""Contract for the stepper bracket — the citation exemplar.

What to imitate here:

- The mounting interface is ONE call: `nema17.mount(p)` declares the pilot
  bore and the bolt circle with NEMA ICS 16's own numbers, so the report
  carries the citation and `attribution` shows a limit that came from
  somewhere. The clearance diameters stay the designer's (see the fragment's
  docstring — a fragment must never launder your numbers into a standard's).
- The envelope bound repeats the design parameters deliberately AND says so:
  it is a change-detector, not proof of correctness — the external footing
  lives in the mount claims. See `docs/FAILURE-MODES.md` entry 4 for what
  happens when that distinction is lost.
- `requires` runs before any geometry: a bracket too short to carry the motor
  face fails in milliseconds, not after a build.
"""

from partspec import Part, build123d
from partspec.refs import nema17

WIDTH, HEIGHT, DEPTH, THICKNESS = 56.0, 62.0, 40.0, 5.0


def stepper_bracket() -> Part:
    p = Part(
        "stepper-bracket",
        build123d(
            "bracket.py",
            "bracket",
            width=WIDTH,
            height=HEIGHT,
            depth=DEPTH,
            thickness=THICKNESS,
        ),
    )

    # Parameter phase — the motor face (Ø43.8 circle around the datum) must
    # fit on the plate with wall left over, provable from arithmetic alone.
    p.requires("height - 28.0 >= 43.815 / 2 + 3.0")
    p.requires("width >= 43.815 + 6.0")

    # The interface, cited: nema17:pilot (hole_diameter) + nema17:bolt_circle.
    nema17.mount(p)

    # Design-envelope change detector; the part is the reference for nothing.
    p.envelope(max=(WIDTH, DEPTH, HEIGHT))
    p.solid_count(1)
    return p
