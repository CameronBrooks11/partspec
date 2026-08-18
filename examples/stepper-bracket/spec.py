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
- **The two region checks are the worked example for `keep_out` / `keep_in`**
  (#200). They state a requirement about SPACE rather than about a feature,
  which is a different kind of claim from everything above and the one with
  no example anywhere until now. Note `axis="y"`: the axis is one of the
  strings `"x"`, `"y"`, `"z"`, never a vector — `(0, 0, 1)` is refused, and
  two fleet agents on different engines guessed it anyway (#193, #199).
"""

from partspec import Part, build123d, region
from partspec.refs import nema17

WIDTH, HEIGHT, DEPTH, THICKNESS = 56.0, 62.0, 40.0, 5.0
MOTOR_CENTRE_Z = HEIGHT - 28.0  # the bracket's datum, as `bracket.py` computes it


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

    # The interface as SPACE, not as a feature. `nema17.mount` above declares
    # the pilot BORE — `hole_diameter`, a cylinder-precision claim the mesh
    # tier refuses outright because a faceted bore has no diameter. The same
    # requirement stated as a keep-out is a claim about volume, which both
    # tiers answer: the motor's locating boss must find nothing in its way.
    #
    # `at` is the datum the model itself uses (x=0, the plate's front face,
    # the motor centre height), `axis="y"` because the plate's thickness runs
    # in y and the boss projects through it. The boss is NEMA ICS 16's AK,
    # cited; its 2 mm projection is the designer's reading of the motor and
    # stays a bare number.
    #
    # `shell=0.6` is what stops this passing vacuously. An absent part has an
    # empty region too, so the check pairs "no material here" with "material
    # near here" — 0.6 mm sits inside the 0.15 mm radial clearance plus the
    # plate around it, so a bracket whose pilot bore went missing fails on the
    # region and one that lost its plate fails on the shell.
    p.keep_out(
        region.cylinder(d=nema17.PILOT_BOSS, h=2.0, at=(0.0, 0.0, MOTOR_CENTRE_Z), axis="y"),
        shell=0.6,
        id="pilot-boss-clearance",
    )

    # The other direction: this region must be ENTIRELY material. The L's
    # inside corner is where the plate and the base become one part, and
    # `solid_count(1)` does not prove it — two plates meeting at an edge can
    # still count as one solid. A relief cut, a base narrower than the plate,
    # or a fillet that ate the joint all fail here and nowhere else.
    # It must STRADDLE the joint to be about the joint. A box inside the
    # plate's own thickness (y < 5) is satisfied by the plate alone and proves
    # nothing — the first draft of this example did exactly that and passed
    # with the base cut to a third of its width. Reaching to y = 12 puts most
    # of the region where only the base can supply material.
    p.keep_in(
        region.box(min=(-20.0, 0.5, 0.5), max=(20.0, 12.0, THICKNESS - 0.5)),
        shell=1.0,
        id="plate-base-joint",
    )

    # Design-envelope change detector; the part is the reference for nothing.
    p.envelope(max=(WIDTH, DEPTH, HEIGHT))
    p.solid_count(1)
    return p
