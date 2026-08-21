"""Part-versus-part interference, declared with the unit of verification
partspec has: the single part.

Run them:

    partspec check examples/clearance/spec.py:interference
    partspec check examples/clearance/spec.py:seat
    partspec check examples/clearance/spec.py:clearance

An assembly verb that takes N parts at their poses and reports pairwise shared
volume is a post-1.0 question (D19, `SPEC-contract.md` §9). What is here now is
the pattern that does the same work today: model `intersection() { A; B; }` at
assembly pose as a part of its own, and claim the outcome the design intends.

Every pair of parts in an assembly is in exactly one of three states, and each
one grades on a different measurand:

    they interpenetrate   the probe is a solid   `volume`
    they touch on a face  the probe is a sheet   `area`
    they share no space   the probe is nothing   `empty`

All three are declared below, against one assembly whose poses live in
`assembly.scad`.
"""

from partspec import Part, openscad

# The probes read these from `assembly.scad`; they are restated here because a
# claim's number has to come from the design, not from a measurement of it.
CRUSH_MIN, CRUSH_MAX = 0.1, 0.3  # what the fit is allowed to be, mm
FOOT_X, FOOT_Z = 20.0, 6.0  # the flank the fit acts over
SEAT_BEARING_MIN = 150.0  # the cover must land on at least this much rail, mm2


def interference() -> Part:
    """They interpenetrate: the crush ribbon the press fit consumes.

    The overlap is the design. An **empty** result here would be the loose
    joint, not a pass — which is why this probe does not declare `empty` and
    would fail its build if the flanks ever stopped touching.
    """
    p = Part("clearance-interference", openscad("interference.scad"))

    # Straight from the fit's limits: the ribbon is the flank area times the
    # crush, and the crush is allowed 0.1 to 0.3. Limits rather than nominal
    # and a tolerance, so the number in the report is the number on the
    # drawing and not a float sum of two of them.
    p.volume(min=FOOT_X * FOOT_Z * CRUSH_MIN, max=FOOT_X * FOOT_Z * CRUSH_MAX)
    # One continuous ribbon, not a scatter of slivers along the flank.
    p.solid_count(1)
    return p


def seat() -> Part:
    """They touch on a face: the cover lands flat on the rail.

    A probe of two parts that touch is a zero-thickness sheet, so `volume` is
    0 and `area` is the measurand (`SPEC-contract.md` §4.2). **The sheet has
    two sides and `area` counts both**, so the bearing area wanted is doubled
    into the claim rather than written as if the sheet were a face.
    """
    p = Part("clearance-seat", openscad("seat.scad"))
    p.area(min=2 * SEAT_BEARING_MIN)
    return p


def clearance() -> Part:
    """They share no space: the lid passes over the tallest component.

    This is the outcome that had no grade at all before `empty` (#237). An
    empty build is otherwise a hard failure before any claim is evaluated, so
    `volume(max=0)` was skipped rather than satisfied and the *good* answer
    was the one that could not be stated.

    Declared alone, as `SPEC-contract.md` §4.12 requires: an empty part has no
    mesh, so any other geometry check on it would be skipped.
    """
    p = Part("clearance-lid-over-post", openscad("clearance.scad"))
    p.empty()
    return p
