"""Check statuses, verdicts, exit codes, and the adjudication rule.

This module is the thesis of the whole tool, so it is deliberately the first thing
implemented and it has no dependency on any CAD engine.

The property everything here serves (SPEC-report.md 1.1):

    Silence must never read as success.

Three failure modes collapse into that sentence, all observed in shipping tools:
a contract that asserts nothing exits green; a check the backend could not evaluate
returns a plausible number anyway; a measurement too coarse to decide the question
is rounded into a pass. Only `Status.PASS` is green here, and `Verdict` /
`exit_code` are what stop the other four from being mistaken for it.

Spec: SPEC-report.md sections 3, 3.1, 3.3, 3.4, 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "BOUND_EPSILON_ABS",
    "BOUND_EPSILON_REL",
    "ContractError",
    "Limit",
    "Measurement",
    "Status",
    "Verdict",
    "adjudicate",
    "epsilon",
    "exit_code",
    "verdict_of",
]


class Status(StrEnum):
    """The outcome of one check. Only PASS is green."""

    PASS = "pass"
    """Evaluated and satisfied, conclusively."""

    FAIL = "fail"
    """Evaluated and violated, conclusively."""

    APPROXIMATE = "approximate"
    """Evaluated, but the error interval straddles the threshold: indeterminate.

    Not a general "this was a mesh" marker — that is `Measurement.exact`. This
    means specifically that the answer lies inside the error band, so the tool
    does not know.
    """

    UNSUPPORTED = "unsupported"
    """The backend cannot evaluate this check on this geometry at all.

    Used when the representation *lacks the entity* (a triangle mesh has no
    cylindrical face, so no hole diameter), or when no honest error bound exists
    for a quantity (sampled wall thickness is one-sided: more samples can only
    find a thinner wall, so there is no principled lower bound).
    """

    SKIPPED = "skipped"
    """Not evaluated: a referenced part is absent, or a parameter check
    short-circuited the run before the engine was invoked."""


# Worst-first ordering, used to collapse per-component vector results and to
# pick a batch's overall verdict.
_SEVERITY: dict[Status, int] = {
    Status.FAIL: 4,
    Status.UNSUPPORTED: 3,
    Status.APPROXIMATE: 2,
    Status.SKIPPED: 1,
    Status.PASS: 0,
}


def worst(statuses: list[Status]) -> Status:
    """Return the most severe status, or PASS for an empty list."""
    return max(statuses, key=lambda s: _SEVERITY[s], default=Status.PASS)


class Verdict(StrEnum):
    """The outcome of one part. Computed from its check statuses."""

    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"
    EMPTY = "empty"
    ERROR = "error"


_EXIT: dict[Verdict, int] = {
    Verdict.PASS: 0,
    Verdict.FAIL: 1,
    Verdict.INCOMPLETE: 2,
    Verdict.EMPTY: 3,
    Verdict.ERROR: 4,
}

EXIT_USAGE = 64
"""Unresolvable target or bad arguments (EX_USAGE). Writes no report, and so never
participates in batch aggregation."""


def exit_code(verdict: Verdict) -> int:
    """Process exit code for a verdict (SPEC-report.md 6.2).

    Exit 2 (INCOMPLETE) is the load-bearing one. A tool that exits 0 on a part
    whose checks were mostly unavailable has told the operator the part is fine,
    which it has not established.
    """
    return _EXIT[verdict]


def verdict_of(statuses: list[Status], *, errored: bool = False) -> Verdict:
    """Collapse check statuses into a verdict, in precedence order.

    `EMPTY` is distinct from a degenerate `PASS` on purpose: a contract with no
    checks is the single most likely output when an author — human or agent —
    does not know what to assert, and it must not be mistaken for a proven part.
    """
    if errored:
        return Verdict.ERROR
    if not statuses:
        return Verdict.EMPTY
    if Status.FAIL in statuses:
        return Verdict.FAIL
    if any(s is not Status.PASS for s in statuses):
        return Verdict.INCOMPLETE
    return Verdict.PASS


# --------------------------------------------------------------------------
# Comparison tolerance
# --------------------------------------------------------------------------

BOUND_EPSILON_ABS = 1e-6
BOUND_EPSILON_REL = 1e-7


def epsilon(limit: float) -> float:
    """Comparison tolerance for a threshold (SPEC-report.md 3.3).

        eps(limit) = 1e-6 + 1e-7 * |limit|

    The relative term is not decoration. Binary STL stores coordinates as
    float32, whose half-ulp is |v| * 2**-24 ~= 5.96e-8 * |v| and therefore
    exceeds a flat 1e-6 above roughly 16.8 mm. Measured: cube([120.3, 80.7,
    40.1]) round-trips as 120.30000305 / 80.69999695 / 40.09999847 — deltas of
    +/-3.05e-6. Against `max=120.3` a purely absolute epsilon yields a
    conclusive FAIL on a geometrically perfect part, and `envelope` is one of
    only a handful of v0 geometry checks, so that is the main path.

    (cad-khana uses a flat 1e-6, which is safe there because it only ever
    compares in-memory OCCT doubles and never round-trips through binary STL.)
    """
    return BOUND_EPSILON_ABS + BOUND_EPSILON_REL * abs(limit)


class ContractError(Exception):
    """The contract itself is wrong — not a failing check.

    Raised for a limit that cannot be adjudicated as written (equality against
    an interval), a vector length mismatch, or a duplicate check id. Produces
    `Verdict.ERROR`, never `Status.FAIL`: a malformed question has no answer.
    """


@dataclass(frozen=True, slots=True)
class Measurement:
    """A measured quantity, never a bare float (SPEC-report.md 2).

    `exact` is a property of *(check, backend, geometry)* and MUST be determined
    per evaluation, never looked up in a static table.

    `bounds` is required iff not `exact`, and is a closed interval guaranteed to
    contain the true value — where "true value" means the artifact as authored
    and exported (D15), not an idealised smooth solid. Asymmetric bounds are
    expected: a backend derives the interval from what it actually did, never
    from an assumed sign.

    For vector quantities `value` is a tuple, `bounds` is a tuple of intervals
    positionally aligned with it, and `axes` names each component so a consumer
    never infers meaning from position alone.
    """

    value: Any
    unit: str
    exact: bool = True
    bounds: Any = None
    axes: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.exact and self.bounds is None:
            raise ContractError(
                "an approximate measurement must carry bounds; a backend that "
                "cannot honestly produce them must report the check unsupported"
            )
        if self.is_vector and self.axes is None:
            raise ContractError("a vector measurement must name its axes")

    @property
    def is_vector(self) -> bool:
        return isinstance(self.value, tuple | list)


@dataclass(frozen=True, slots=True)
class Limit:
    """A bound a measurement must satisfy (SPEC-report.md 3.4).

    A closed set of forms, so a consumer can render and compare limits without
    knowing the check kind. Numeric forms may carry an array value, positionally
    aligned with the measurement, compared elementwise.
    """

    min: Any = None
    max: Any = None
    equals: Any = None
    choices: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if all(f is None for f in (self.min, self.max, self.equals, self.choices)):
            raise ContractError("a limit must constrain something")

    @property
    def is_discrete(self) -> bool:
        """True for forms that cannot be adjudicated against an interval."""
        return self.equals is not None or self.choices is not None


def _satisfies_scalar(value: float, lo: float | None, hi: float | None) -> bool:
    if lo is not None and value < lo - epsilon(lo):
        return False
    return not (hi is not None and value > hi + epsilon(hi))


def _adjudicate_scalar(value: Any, bounds: tuple[float, float] | None, limit: Limit) -> Status:
    if limit.is_discrete:
        if bounds is not None:
            raise ContractError(
                "equality and membership limits are not decidable against an "
                "interval; express the claim as a range instead"
            )
        if limit.choices is not None:
            return Status.PASS if value in limit.choices else Status.FAIL
        return Status.PASS if value == limit.equals else Status.FAIL

    lo, hi = limit.min, limit.max
    if bounds is None:
        return Status.PASS if _satisfies_scalar(value, lo, hi) else Status.FAIL

    # Interval adjudication: an approximate measurement still decides
    # conclusively whenever its whole error band falls on one side of the limit.
    blo, bhi = bounds
    if blo > bhi:
        raise ContractError(f"malformed bounds: [{blo}, {bhi}]")
    entirely_satisfies = _satisfies_scalar(blo, lo, hi) and _satisfies_scalar(bhi, lo, hi)
    if entirely_satisfies:
        return Status.PASS
    entirely_violates = (lo is not None and bhi < lo - epsilon(lo)) or (
        hi is not None and blo > hi + epsilon(hi)
    )
    if entirely_violates:
        return Status.FAIL
    return Status.APPROXIMATE


def adjudicate(measurement: Measurement, limit: Limit) -> Status:
    """Decide one check from its measurement and limit (SPEC-report.md 3.1).

    Exact measurements compare directly. Approximate ones compare their whole
    interval: entirely inside the satisfying region is a real PASS, entirely
    outside is a real FAIL, and only a straddling interval is APPROXIMATE. So a
    wall at 2.4mm +/-0.01 against a 2.0mm minimum genuinely passes; the same
    wall at 2.01mm +/-0.05 does not, because the tool does not know.

    Vector measurements adjudicate per component and take the worst.
    """
    if not measurement.is_vector:
        return _adjudicate_scalar(measurement.value, measurement.bounds, limit)

    values = tuple(measurement.value)
    bounds = tuple(measurement.bounds) if measurement.bounds is not None else (None,) * len(values)
    if len(bounds) != len(values):
        raise ContractError("bounds length does not match value length")

    per_component: list[Status] = []
    for i, v in enumerate(values):
        component_limit = Limit(
            min=_component(limit.min, i, len(values)),
            max=_component(limit.max, i, len(values)),
            equals=_component(limit.equals, i, len(values)),
            choices=limit.choices,
        )
        per_component.append(_adjudicate_scalar(v, bounds[i], component_limit))
    return worst(per_component)


def _component(limit_value: Any, index: int, expected_len: int) -> Any:
    """Select component `index` of a limit, broadcasting scalars."""
    if limit_value is None:
        return None
    if isinstance(limit_value, tuple | list):
        if len(limit_value) != expected_len:
            raise ContractError(
                f"vector limit has {len(limit_value)} components, measurement has {expected_len}"
            )
        return limit_value[index]
    return limit_value
