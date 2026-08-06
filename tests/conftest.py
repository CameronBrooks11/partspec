"""Session-level guards.

The tool's own thesis, turned on its test suite: a skipped test reports the
same colour as a passing one, so an absent engine has to be a decision
somebody made rather than a property of whatever image the job happened to
run on.
"""

from __future__ import annotations

import os

import pytest

REQUIRE_ENGINES = "PARTSPEC_REQUIRE_ENGINES"


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run at all when a required engine is missing.

    Set `PARTSPEC_REQUIRE_ENGINES=1` in CI. Without it, this suite reported
    195 passed / 23 skipped on a runner with no OpenSCAD, and the 23 were the
    entire end-to-end path — the vacuous-green guard, the capability refusal,
    the on-disk schema shape. The gate was green because the tests were
    absent, which is the first of the three failure modes `SPEC-report.md`
    §1.1 names, committed by the project against itself.

    A hard failure rather than a warning: a warning is what the previous
    arrangement already amounted to.
    """
    if os.environ.get(REQUIRE_ENGINES) != "1":
        return

    from partspec.engines import openscad

    missing = []
    if openscad.find_executable() is None:
        missing.append("openscad (set PARTSPEC_OPENSCAD, or put it on PATH)")
    for module in ("trimesh", "manifold3d", "build123d", "cadquery"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        raise pytest.UsageError(
            f"{REQUIRE_ENGINES}=1 but these are unavailable: {', '.join(missing)}. "
            f"Every test that needs them would skip, and a skip reads as success."
        )
