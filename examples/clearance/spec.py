"""Part-versus-part interference, declared with the unit of verification
partspec has: the single part.

Run them:

    partspec check examples/clearance/spec.py:interference
    partspec check examples/clearance/spec.py:clearance

An assembly verb that takes N parts at their poses and reports pairwise shared
volume is a post-1.0 question (D19, `SPEC-contract.md` §9). What is here now is
the pattern that does the same work today: model `intersection() { A; B; }` at
assembly pose as a part of its own, and claim the outcome the design intends.

Every pair of parts in an assembly is in exactly one of three states, and each
one grades on a different measurand:

    they interpenetrate   the probe is a solid   `volume`
    they share no space   the probe is nothing   `empty`
    they touch on a face  the probe is a sheet   NOT PORTABLE -- see the README

The two declared below are the two that answer the same way on every engine,
against one assembly whose poses live in `assembly.scad`. Face contact is a
zero-thickness result and the kernels disagree about it; the README measures
the disagreement and #314 is what would let a report state which behaviour was
in force.

**The clearance probe intersects against a GROWN part.** `lid() n post()` is
empty for any gap at all, including a gap of nothing, so `empty` over it states
only that the two do not interpenetrate. Grown by the standoff the fit
requires, the same `empty` states the standoff -- and a violation of it with any
margin is a solid with positive volume on every kernel rather than the
zero-thickness result the kernels disagree about. This is the remedy `partspec
lint`'s own `csg-two-part-intersection` finding names.

The degeneracy moves rather than vanishing: at a gap of EXACTLY the clearance
the probe is a sheet again and the pinned engines disagree, so a design gap must
clear the requirement strictly. The assembly leaves 2.0 mm against a required
1.5 mm for that reason. See the README for the sweep and for why a per-axis grow
measures Chebyshev distance rather than Euclidean.
"""

from partspec import Part, openscad

# The probes read these from `assembly.scad`; they are restated here because a
# claim's number has to come from the design, not from a measurement of it.
CRUSH_MIN, CRUSH_MAX = 0.1, 0.3  # what the fit is allowed to be, mm
FOOT_X, FOOT_Z = 20.0, 6.0  # the flank the fit acts over


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


def clearance() -> Part:
    """They share no space: the lid stands off the tallest component.

    This is the outcome that had no grade at all before `empty` (#237). An
    empty build is otherwise a hard failure before any claim is evaluated, so
    `volume(max=0)` was skipped rather than satisfied and the *good* answer
    was the one that could not be stated.

    The probe intersects the lid against the post grown by CLEAR, so a passing
    `empty` says the standoff is **at least CLEAR** and not merely that the two
    do not interpenetrate. `empty` carries no bound, so unlike the volume band
    above, that number lives in `assembly.scad` and not here — the cost of
    grading a clearance with the check that has nothing to grade.

    Declared alone, as `SPEC-contract.md` §4.12 requires: an empty part has no
    mesh, so any other geometry check on it would be skipped.
    """
    p = Part("clearance-lid-over-post", openscad("clearance.scad"))
    p.empty()
    return p
