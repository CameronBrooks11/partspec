"""Session-level guards.

The tool's own thesis, turned on its test suite: a skipped test reports the
same colour as a passing one, so an absent engine has to be a decision
somebody made rather than a property of whatever image the job happened to
run on.
"""

from __future__ import annotations

import os
import sys

import pytest

REQUIRE_ENGINES = "PARTSPEC_REQUIRE_ENGINES"

# `mcp` is not an engine, but it is the same hazard this file exists for: an
# optional dependency whose absence silently skips the tests that prove it.
ALL_ENGINES = ("openscad", "trimesh", "manifold3d", "build123d", "cadquery", "mcp")


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


@pytest.fixture(autouse=True)
def _evict_model_modules_between_tests():
    """Undo, after every test, the `sys.modules` residue a model build leaves.

    The CLI evicts after each run (`cli._invalidate_after`) because a stale
    helper served to the next build is a fresh-looking wrong answer. A test
    that calls `run()` or `target.resolve()` directly gets no such eviction,
    and the residue is registered under a BARE name — `claims`, `model` — so
    it answers for the next test that writes a file of the same name into its
    own tmp dir.

    That is not hypothetical. `test_differential`'s exemplar parity test left
    `examples/bearing-block/claims.py` cached as `claims`, and under reverse
    file order it broke five tests in `test_batch.py` — precisely the five
    that exist to prove model modules do NOT cross directories. The suite's
    guard against process-global module leakage was defeated by a
    process-global module leak, and stayed green only because `test_batch`
    happens to sort before `test_differential`.

    Eviction uses the build registry rather than a directory sweep, for the
    reason `pycad._LOADED_MODEL_MODULES` records: sweeping by path once
    evicted the editable-installed partspec itself.
    """
    yield
    from partspec.engines import pycad

    for root, names in list(pycad._LOADED_MODEL_MODULES.items()):
        for name in names:
            sys.modules.pop(name, None)
        pycad._LOADED_MODEL_MODULES.pop(root, None)
