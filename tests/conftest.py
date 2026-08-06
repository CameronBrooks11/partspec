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

ALL_ENGINES = ("openscad", "trimesh", "manifold3d", "build123d", "cadquery")


def _available(name: str) -> bool:
    if name == "openscad":
        from partspec.engines import openscad

        return openscad.find_executable() is not None
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run at all when a declared engine is missing.

    Set `PARTSPEC_REQUIRE_ENGINES=1` in CI for the full environment. Without
    it, this suite reported 195 passed / 23 skipped on a runner with no
    OpenSCAD, and the 23 were the entire end-to-end path — the vacuous-green
    guard, the capability refusal, the on-disk schema shape. The gate was
    green because the tests were absent, which is the first of the three
    failure modes `SPEC-report.md` §1.1 names, committed by the project
    against itself.

    A comma-separated subset is accepted (`openscad,trimesh,manifold3d`)
    because `just test-mesh-only` runs in an environment where the absence of
    build123d **is** the thing being proved. Requiring everything everywhere
    would make the honest job the failing one.

    A hard failure rather than a warning: a warning is what the previous
    arrangement already amounted to.
    """
    declared = os.environ.get(REQUIRE_ENGINES)
    if not declared:
        return
    required = ALL_ENGINES if declared == "1" else tuple(n.strip() for n in declared.split(","))

    unknown = [n for n in required if n not in ALL_ENGINES]
    if unknown:
        raise pytest.UsageError(
            f"{REQUIRE_ENGINES} names something unrecognised: {', '.join(unknown)}. "
            f"Known: {', '.join(ALL_ENGINES)}."
        )

    missing = [n for n in required if not _available(n)]
    if missing:
        hint = " (set PARTSPEC_OPENSCAD, or put it on PATH)" if "openscad" in missing else ""
        raise pytest.UsageError(
            f"{REQUIRE_ENGINES}={declared} but these are unavailable: "
            f"{', '.join(missing)}{hint}. Every test that needs them would skip, "
            f"and a skip reads as success."
        )
