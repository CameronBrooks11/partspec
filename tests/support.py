"""Shared test helpers."""

from __future__ import annotations

import subprocess

import pytest

from partspec.backend import Unsupported
from partspec.engines import openscad
from partspec.status import Measurement

__all__ = ["measured", "needs_openscad", "openscad_supports_backend_flag", "refused"]

OPENSCAD = openscad.find_executable()

needs_openscad = pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not installed")
"""Skip when there is no engine — but see `conftest.py`, which turns that skip
into a hard failure under `PARTSPEC_REQUIRE_ENGINES=1`. A skip is the right
local behaviour and the wrong CI behaviour, and the difference is worth a
switch rather than a habit."""


def openscad_supports_backend_flag() -> bool:
    """Whether the installed engine has `--backend` at all.

    2021.01 does not: render backends arrived later. This is a real portability
    boundary rather than a quirk — 2021.01 is what Debian and Ubuntu ship — so
    tests branch on it and assert both sides.
    """
    if OPENSCAD is None:
        return False
    proc = subprocess.run([OPENSCAD, "--help"], capture_output=True, text=True, check=False)
    return "--backend" in proc.stdout + proc.stderr


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
