# Python (uv) task runner
# See https://github.com/CameronBrooks11/dev-toolbox/blob/main/docs/just-conventions.md

set dotenv-load := false

# Default: show available recipes
default:
    @just --list

# Install dependencies and set up environment.
#
# ALL extras, deliberately. The lighter `uv sync --extra mesh` was tempting —
# OCCT is ~1.8GB — but it produced exactly the CI drift dev-toolbox warns about:
# pyright resolved build123d locally and not in CI, so `just check` gave two
# different answers. One environment, one answer.
#
# It also means the OCP resolution is exercised everywhere rather than only on
# the machine that happens to have both engines. See `just ocp-guard`.
setup:
    uv sync --all-extras

# The light path: mesh tier only, no OCCT. For quick OpenSCAD-only iteration.
# NOT what CI runs — if you use this, `just check` may differ from the gate.
setup-mesh:
    uv sync --extra mesh

# Format code (mutates working tree — use locally)
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Verify formatting (non-mutating — use in CI)
fmt-check:
    uv run ruff format --check .

# Run linters
lint:
    uv run ruff check .

# Type-check
typecheck:
    uv run pyright

# Format + lint + type-check (non-mutating — safe for CI)
check: fmt-check lint typecheck

# Run tests
test:
    uv run pytest

# Run the suite in reverse file order.
#
# Deterministic rather than randomised: the failure this catches is one test
# leaving process-global state (a cached sys.modules entry, an OCCT printer)
# that a later test depends on or is broken by. A reversal exposes every
# such pair with one run and the same result every time, where a shuffle
# finds them eventually and reproduces them never.
#
# `find`, not `ls tests/test_*.py`: the glob is non-recursive while pytest
# collects `tests/` recursively, so a test file in a subdirectory would be
# silently skipped here — fewer tests, still green, which is the failure this
# repo refuses. It caught a real one:
# an exemplar's `claims.py` outliving its test and breaking the five tests
# that exist to prove that cannot happen.
test-reverse:
    uv run pytest $(find tests -name 'test_*.py' | sort -r)

# Run the mesh tests against a mesh-ONLY install, in a throwaway environment.
#
# Because `setup` installs all extras, the mesh-only install is exercised
# nowhere else — and scipy reaches this machine only via build123d/cadquery, so
# a mesh-tier code path that quietly depends on it passes locally and in CI and
# breaks for anyone who installed just `partspec[mesh]`. trimesh's `body_count`
# is exactly such a path, which is why the backend counts bodies itself.
test-mesh-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet "$env"
    uv pip install --quiet --python "$env/bin/python" -e '.[mesh]' pytest
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("scipy") is None, "scipy leaked in — this recipe no longer proves anything"'
    "$env/bin/python" -m pytest tests/test_mesh_backend.py -q

# Run the MCP tests against an mcp-ONLY install, in a throwaway environment.
#
# Proves `pip install partspec[mcp]` alone can start the server and answer:
# the adapter is core + a subprocess per call by design (D18), so no CAD
# engine may be required just to stand it up. The engine-dependent test
# skips here legitimately — the absence of engines is the thing being proved.
test-mcp-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet "$env"
    uv pip install --quiet --python "$env/bin/python" -e '.[mcp]' pytest
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("trimesh") is None and u.find_spec("build123d") is None, "a CAD engine leaked in — this recipe no longer proves anything"'
    PARTSPEC_REQUIRE_ENGINES=mcp "$env/bin/python" -m pytest tests/test_mcp.py -q

# Run main entrypoint
run *ARGS:
    uv run partspec {{ARGS}}

# Assert exactly one OCP provider is installed (SPEC-backend.md 4.1).
# cadquery-ocp and cadquery-ocp-novtk both own the top-level OCP/ package and
# pip does NOT detect the conflict — one silently clobbers the other.
ocp-guard:
    uv run python scripts/check_ocp.py

# Remove build artifacts
clean:
    rm -rf .venv dist outputs .pytest_cache .ruff_cache .pyright .mypy_cache .coverage
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Run the agent-convergence evals (see evals/README.md). Costs real agent calls.
eval *ARGS:
    python3 evals/run.py {{ARGS}}
