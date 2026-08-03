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
    rm -rf .venv dist .pytest_cache .ruff_cache .pyright
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
