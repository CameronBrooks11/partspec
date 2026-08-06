"""Shared test helpers."""

from __future__ import annotations

from partspec.backend import Unsupported
from partspec.status import Measurement

__all__ = ["measured", "refused"]


def measured(result: Measurement | Unsupported) -> Measurement:
    """Assert a primitive answered, and narrow the type for the type checker.

    Worth an assertion rather than a cast. Several primitives now refuse when
    their precondition fails, so "this returned a number" is a real claim about
    the fixture — and a test that silently type-ignored a refusal would pass
    while measuring nothing.
    """
    assert not isinstance(result, Unsupported), f"unexpectedly refused: {result.reason}"
    return result


def refused(result: Measurement | Unsupported) -> Unsupported:
    """Assert a primitive refused, and narrow the type."""
    assert isinstance(result, Unsupported), f"expected a refusal, got {result!r}"
    return result
