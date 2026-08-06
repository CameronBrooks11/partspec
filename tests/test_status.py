"""The adjudication rule, tested directly.

Worth doing thoroughly and early for a specific reason: as v0 is scoped, *no v0
check can produce APPROXIMATE*. Everything in the v0 set is exact on a polyhedron
under D15, and the one candidate (min_wall) turns out to be UNSUPPORTED for want
of an honest lower bound. So the interval machinery ships dormant, and its first
real exercise would otherwise be its first bug report. These tests are the
substitute for that exercise.
"""

from __future__ import annotations

import pytest

from partspec.status import (
    ContractError,
    Limit,
    Measurement,
    Status,
    Verdict,
    adjudicate,
    epsilon,
    exit_code,
    verdict_of,
)

# --------------------------------------------------------------------------
# epsilon
# --------------------------------------------------------------------------


def test_epsilon_has_a_relative_term():
    """A flat 1e-6 breaks the envelope check on binary STL; see status.epsilon."""
    assert epsilon(0.0) == pytest.approx(1e-6)
    assert epsilon(120.3) > 1.2e-5


def test_epsilon_covers_float32_quantisation():
    """The measured failure this exists to prevent.

    cube([120.3, 80.7, 40.1]) round-trips through binary STL as
    120.30000305 / 80.69999695 / 40.09999847. Against a flat 1e-6 that is a
    conclusive FAIL on a geometrically perfect part.
    """
    for nominal, measured in (
        (120.3, 120.30000305175781),
        (80.7, 80.69999694824219),
        (40.1, 40.099998474121094),
    ):
        assert abs(measured - nominal) > 1e-6, "premise: a flat epsilon would fail"
        assert adjudicate(Measurement(measured, "mm"), Limit(max=nominal)) is Status.PASS
        assert adjudicate(Measurement(measured, "mm"), Limit(min=nominal)) is Status.PASS


# --------------------------------------------------------------------------
# exact adjudication
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        (2.5, Limit(min=2.0), Status.PASS),
        (1.5, Limit(min=2.0), Status.FAIL),
        (1.5, Limit(max=2.0), Status.PASS),
        (2.5, Limit(max=2.0), Status.FAIL),
        (8.0, Limit(min=7.9, max=8.1), Status.PASS),
        (8.2, Limit(min=7.9, max=8.1), Status.FAIL),
        (1, Limit(equals=1), Status.PASS),
        (2, Limit(equals=1), Status.FAIL),
        (True, Limit(equals=True), Status.PASS),
        (False, Limit(equals=True), Status.FAIL),
        ("inner", Limit(choices=("inner", "outer")), Status.PASS),
        ("middle", Limit(choices=("inner", "outer")), Status.FAIL),
    ],
)
def test_exact_scalar(value, limit, expected):
    assert adjudicate(Measurement(value, "mm"), limit) is expected


def test_exactly_on_the_limit_passes():
    """Boundary equality resolves in favour of the part, via the epsilon.

    Contracts routinely derive geometry from the same constant they bound
    against, so exact float equality at a boundary would be a coin flip.
    """
    assert adjudicate(Measurement(2.0, "mm"), Limit(min=2.0)) is Status.PASS
    assert adjudicate(Measurement(2.0, "mm"), Limit(max=2.0)) is Status.PASS


# --------------------------------------------------------------------------
# interval adjudication — the core algorithm
# --------------------------------------------------------------------------


def test_interval_entirely_satisfying_is_a_real_pass():
    m = Measurement(2.4, "mm", exact=False, bounds=(2.39, 2.41))
    assert adjudicate(m, Limit(min=2.0)) is Status.PASS


def test_interval_entirely_violating_is_a_real_fail():
    m = Measurement(1.6, "mm", exact=False, bounds=(1.59, 1.61))
    assert adjudicate(m, Limit(min=2.0)) is Status.FAIL


def test_straddling_interval_is_approximate():
    """The whole reason `approximate` is a status and not a flag."""
    m = Measurement(2.01, "mm", exact=False, bounds=(1.96, 2.06))
    assert adjudicate(m, Limit(min=2.0)) is Status.APPROXIMATE


def test_approximate_still_decides_most_of_the_time():
    """An error bar does not mean the tool has to shrug."""
    wide = Measurement(10.0, "mm", exact=False, bounds=(9.0, 11.0))
    assert adjudicate(wide, Limit(min=2.0)) is Status.PASS
    assert adjudicate(wide, Limit(max=2.0)) is Status.FAIL


def test_asymmetric_bounds_are_honoured():
    """Tessellation error is one-sided; the interval is not centred on `value`."""
    m = Measurement(100.0, "mm3", exact=False, bounds=(97.5, 100.0))
    assert adjudicate(m, Limit(min=98.0)) is Status.APPROXIMATE
    assert adjudicate(m, Limit(min=97.0)) is Status.PASS


def test_equality_against_an_interval_is_a_contract_error():
    """Not a failing check — a malformed question has no answer."""
    m = Measurement(1.0, "count", exact=False, bounds=(0.9, 1.1))
    with pytest.raises(ContractError):
        adjudicate(m, Limit(equals=1))


def test_approximate_without_bounds_is_refused_at_construction():
    """A backend that cannot honestly bound a quantity must report it
    unsupported. Guessing an error bar is the same lie in a smaller font."""
    with pytest.raises(ContractError):
        Measurement(1.0, "mm", exact=False)


# --------------------------------------------------------------------------
# vectors
# --------------------------------------------------------------------------


def test_vector_all_components_pass():
    m = Measurement((15.8, 15.8, 8.0), "mm", axes=("x", "y", "z"))
    assert adjudicate(m, Limit(max=(40, 40, 15))) is Status.PASS


def test_vector_takes_the_worst_component():
    m = Measurement((15.8, 15.8, 20.0), "mm", axes=("x", "y", "z"))
    assert adjudicate(m, Limit(max=(40, 40, 15))) is Status.FAIL


def test_vector_scalar_limit_broadcasts():
    m = Measurement((10.0, 20.0, 30.0), "mm", axes=("x", "y", "z"))
    assert adjudicate(m, Limit(max=40)) is Status.PASS
    assert adjudicate(m, Limit(max=25)) is Status.FAIL


def test_vector_length_mismatch_is_a_contract_error():
    m = Measurement((10.0, 20.0, 30.0), "mm", axes=("x", "y", "z"))
    with pytest.raises(ContractError):
        adjudicate(m, Limit(max=(40, 40)))


def test_vector_requires_axes():
    with pytest.raises(ContractError):
        Measurement((1.0, 2.0, 3.0), "mm")


def test_an_unconstrained_component_is_not_a_claim():
    """`equals=(6, None, None)` means "six faces, no claim about the rest".

    The unclaimed axes are skipped rather than adjudicated. Before this they
    raised, because building a per-component `Limit` out of three Nones trips
    `Limit.__post_init__` — which made partial vector claims impossible to
    express at all.
    """
    m = Measurement((6, 12, 8), "count", axes=("faces", "edges", "vertices"))
    assert adjudicate(m, Limit(equals=(6, None, None))) is Status.PASS
    assert adjudicate(m, Limit(equals=(7, None, None))) is Status.FAIL
    assert adjudicate(m, Limit(equals=(None, 12, 8))) is Status.PASS
    assert adjudicate(m, Limit(equals=(None, 12, 9))) is Status.FAIL


def test_a_limit_constraining_nothing_is_a_contract_error():
    """The vacuous-green guard, reached through a limit rather than an empty
    contract. `Limit.__post_init__` cannot catch this — `(None, None, None)` is
    not None — and folding zero components would return PASS."""
    m = Measurement((6, 12, 8), "count", axes=("faces", "edges", "vertices"))
    with pytest.raises(ContractError, match="claims nothing"):
        adjudicate(m, Limit(equals=(None, None, None)))


# --------------------------------------------------------------------------
# verdicts and exit codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], Verdict.EMPTY),
        ([Status.PASS], Verdict.PASS),
        ([Status.PASS, Status.PASS], Verdict.PASS),
        ([Status.PASS, Status.FAIL], Verdict.FAIL),
        ([Status.PASS, Status.UNSUPPORTED], Verdict.INCOMPLETE),
        ([Status.PASS, Status.APPROXIMATE], Verdict.INCOMPLETE),
        ([Status.PASS, Status.SKIPPED], Verdict.INCOMPLETE),
        # a hard failure outranks an unproven one
        ([Status.FAIL, Status.UNSUPPORTED], Verdict.FAIL),
    ],
)
def test_verdict_precedence(statuses, expected):
    assert verdict_of(statuses) is expected


def test_error_outranks_everything():
    assert verdict_of([Status.PASS], errored=True) is Verdict.ERROR


def test_empty_is_not_a_degenerate_pass():
    """Vacuous green: a contract asserting nothing must not exit 0.

    It is the single most likely output when an author does not know what to
    assert, and an agent will read a green run as success.
    """
    assert verdict_of([]) is Verdict.EMPTY
    assert exit_code(Verdict.EMPTY) != 0


def test_unproven_is_not_green():
    """The load-bearing exit code. A part whose checks were mostly unavailable
    has not been established to be fine."""
    assert exit_code(Verdict.INCOMPLETE) == 2
    assert exit_code(Verdict.INCOMPLETE) != 0


def test_only_pass_exits_zero():
    for verdict in Verdict:
        assert (exit_code(verdict) == 0) is (verdict is Verdict.PASS)
