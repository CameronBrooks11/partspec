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
- **The three region checks are the worked example for `keep_out` / `keep_in`**
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
    # in y and the boss projects through it. The diameter is NEMA ICS 16's AK,
    # taken from `refs.nema17` rather than retyped; its 2 mm projection is the
    # designer's reading of the motor and stays a bare number.
    #
    # It does NOT reach the report as a citation, unlike the `nema17.mount`
    # claims above: `checks[].source` is populated for the nine bound-carrying
    # methods (SPEC-contract §10) and a region is not one of them, so this
    # check's `source` is null. Filed as #250 — worth knowing here, because
    # this file is the citation exemplar and the gap is invisible until you
    # look at the JSON.
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

    # The other direction: these regions must be ENTIRELY material. Together
    # they say the L's corner carries a web of material in both members, which
    # nothing else here proves — the envelope is a change-detector and
    # `solid_count(1)` counts bodies, not section area.
    #
    # TWO boxes, because one cannot express this. The members occupy
    # perpendicular slabs — the plate is y in [0, 5], the base is z in [0, 5] —
    # so a single box big enough to need material from both would also span
    # the concave quarter outside the L (y > 5 AND z > 5), which is air, and
    # fail on the shipped part. Each box therefore reaches out of the shared
    # corner into ONE member's own territory.
    #
    # Getting this wrong is easy and quiet, and both ways round have now been
    # shipped in drafts of this very example. The first draft's box lay inside
    # the plate's 5 mm thickness, so the PLATE alone satisfied it and it passed
    # with the base cut to a third of its width. The second reached to y = 12
    # — further into base-only material, AWAY from the plate — so the BASE
    # alone satisfied it and it passed on a bracket with no plate at all
    # (round 1 of #200's review). A region proves nothing about a member it
    # never enters.
    # Two more things a reader should not have to rediscover.
    #
    # A region covers exactly what it spans: +/-26 of a 56 mm joint is 93% of
    # it, and a sever confined to the last 2 mm at each end passes. That is a
    # region's nature rather than a defect, but the number is a choice and it
    # should be a stated one.
    #
    # And `shell` is INERT on both of these, though the API requires it. A
    # keep-in's shell exists to fail a solid brick — "material everywhere here"
    # being satisfied perfectly by unbounded material — and it does that by
    # demanding some emptiness within `shell` of the region. These regions are
    # rooted 0.5 mm from the bracket's own outer faces, so their shells escape
    # into free space on those sides and are never entirely solid, for the L
    # and for a brick alike: a solid 56x40x62 block passes both. The shell does
    # real work on the keep-out above, and on the shape `keep_in`'s docstring
    # describes — a boss or a pin standing proud, where the surround is air on
    # the real part and material on the brick. Here the envelope and
    # `solid_count` are what exclude the brick.
    p.keep_in(
        # Up the plate, through z = 5 where the base stops.
        region.box(min=(-26.0, 0.5, 0.5), max=(26.0, THICKNESS - 0.5, 12.0)),
        shell=1.0,
        id="joint-web-plate",
    )
    p.keep_in(
        # Along the base, past y = 5 where the plate stops.
        region.box(min=(-26.0, 0.5, 0.5), max=(26.0, 12.0, THICKNESS - 0.5)),
        shell=1.0,
        id="joint-web-base",
    )

    # Design-envelope change detector; the part is the reference for nothing.
    p.envelope(max=(WIDTH, DEPTH, HEIGHT))
    p.solid_count(1)
    return p
