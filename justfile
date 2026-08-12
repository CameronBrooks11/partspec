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
[doc("Install all extras and set up the environment (what CI runs)")]
setup:
    uv sync --all-extras

# The light path: mesh tier only, no OCCT. For quick OpenSCAD-only iteration.
# NOT what CI runs — if you use this, `just check` may differ from the gate.
[doc("Light path: mesh tier only — NOT what CI runs")]
setup-mesh:
    uv sync --extra mesh

# Format code (mutates working tree — use locally)
fmt:
    uv run ruff format .
    uv run ruff check --fix .
    uv run python scripts/gen_docs.py

# Verify formatting (non-mutating — use in CI)
fmt-check:
    uv run ruff format --check .
    uv run python scripts/gen_docs.py --check

# Regenerate the mechanical blocks in the docs from the code they describe.
#
# The vocabulary table, the unit table, `DIMENSIONAL_KINDS`, the backend
# protocol block and the README's exit codes are projections of the code, and
# used to be second copies of it held in step by tests that reported drift
# after the fact. Same mutating/non-mutating split as `fmt` — `just fmt`
# rewrites, `just check` refuses a stale block. Run by `fmt` and `fmt-check`,
# so this recipe is for running it alone.
[doc("Regenerate the generated blocks in the docs from the code")]
gen-docs:
    uv run python scripts/gen_docs.py

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
[doc("Run the suite in reverse file order (cross-test state leaks)")]
test-reverse:
    uv run pytest $(find tests -name 'test_*.py' | sort -r)

# Run the WHOLE suite against a mesh-ONLY install, in a throwaway environment.
#
# Because `setup` installs all extras, the mesh-only install is exercised
# nowhere else — and scipy reaches this machine only via build123d/cadquery, so
# a mesh-tier code path that quietly depends on it passes locally and in CI and
# breaks for anyone who installed just `partspec[mesh]`. trimesh's `body_count`
# is exactly such a path, which is why the backend counts bodies itself.
#
# It ran only `tests/test_mesh_backend.py` until this change, which left the
# gap between "no extras" and "all extras" uncovered: a module gated on a
# PROXY dependency (`numpy` standing in for build123d — numpy arrives with
# trimesh) collects here and nowhere else. That is not hypothetical. The
# commit that added `test-no-extras` broke `test_vdiff.py` in exactly this
# way — 1 failed, 11 errors on `pip install partspec[mesh]` — and every gate
# in this repo stayed green, because the only recipe running the whole suite
# sat in the one environment where the proxy was absent too.
#
# So it runs everything now. Tests needing build123d skip, which is correct:
# their absence is what this environment exists to prove.
[doc("Run the WHOLE suite against a throwaway mesh-only install")]
test-mesh-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet "$env"
    uv pip install --quiet --python "$env/bin/python" -e '.[mesh]' pytest
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("scipy") is None, "scipy leaked in — this recipe no longer proves anything"'
    "$env/bin/python" -m pytest tests/ -q

# Run the MCP tests against an mcp-ONLY install, in a throwaway environment.
#
# Proves `pip install partspec[mcp]` alone can start the server and answer:
# the adapter is core + a subprocess per call by design (D18), so no CAD
# engine may be required just to stand it up. The engine-dependent test
# skips here legitimately — the absence of engines is the thing being proved.
[doc("Run the MCP tests against a throwaway mcp-only install")]
test-mcp-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet "$env"
    uv pip install --quiet --python "$env/bin/python" -e '.[mcp]' pytest
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("trimesh") is None and u.find_spec("build123d") is None, "a CAD engine leaked in — this recipe no longer proves anything"'
    PARTSPEC_REQUIRE_ENGINES=mcp "$env/bin/python" -m pytest tests/test_mcp.py -q

# Run the WHOLE suite against a no-extras install, in a throwaway environment.
#
# The claim is ZERO FAILURES: without any extra, every test that needs an
# engine must SKIP, and the rest must pass. That is the tool's own thesis
# applied to its suite — an absent engine is a decision, not a failure, and a
# failure must mean the code is wrong.
#
# It was false. On a base install this reported 23 failed / 317 passed, and
# 392 tests did not collect at all: modules gated by a top-level
# `importorskip` collapsed to a single skip line, so `test_diff.py` — 32 of
# whose 34 tests need no engine whatsoever — reported literally "1 skipped".
#
# No CI job could catch it: `check` and `test` install every extra, and
# `mesh-only`/`mcp-only` ran a single module each — so no job ran the WHOLE
# suite anywhere an extra was missing, and the environment that shows the
# defect is the one nothing ran in. That is also why the sdist claim in
# `pyproject.toml` — that a downstream packager can run the shipped suite —
# held only in a full dev environment.
#
# `PARTSPEC_REQUIRE_ENGINES` is deliberately NOT set: here the absence of every
# engine is the thing being proved, so skips are the correct outcome.
[doc("Run the WHOLE suite against a throwaway no-extras install")]
test-no-extras:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet "$env"
    uv pip install --quiet --python "$env/bin/python" -e '.' pytest
    "$env/bin/python" -c 'import importlib.util as u; assert all(u.find_spec(n) is None for n in ("trimesh", "build123d", "cadquery", "mcp")), "an extra leaked in — this recipe no longer proves anything"'
    "$env/bin/python" -m pytest tests/ -q

# Run the WHOLE suite against an occt-ONLY install, in a throwaway environment.
#
# Plain `pip`, not `uv pip` — which is why this recipe did not exist until
# 2026-08-11 and the environment had never been run. build123d's
# `cadquery-ocp-proxy` picks the real OCP wheel with an install-time hook that
# uv's installer does not run, so `uv pip install .[occt]` lands the proxy and
# no `OCP` module at all (#109). The shape every other recipe here uses cannot
# build this environment.
#
# Heavy — OCCT is ~1.5GB — so CI gates it on the `changes` path filter rather
# than running it on a docs-only PR. It IS a CI job, with
# `PARTSPEC_REQUIRE_ENGINES=openscad,build123d`, which is the sharper form of
# the import check below: `conftest.py` resolves that by importing.
# Measured when added: 664 passed, 117 skipped, 0 failed.
[doc("Run the WHOLE suite against a throwaway occt-only install (slow, ~1.5GB)")]
test-occt-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet --seed "$env"
    "$env/bin/python" -m pip install --quiet -e '.[occt]' pytest
    # `import`, not `find_spec`. #109 is precisely the state where the
    # DISTRIBUTION is installed and the engine does not work: find_spec
    # ("build123d") is true in a uv-pip install that delivered no OCP, and
    # `import build123d` is what says so. The suite's own `needs_*` markers key
    # on find_spec, so a broken engine there produces failures rather than
    # skips — correct, but this is the sharper statement and it comes first.
    "$env/bin/python" -c 'import build123d' || { echo "build123d installed but not importable — the #109 shape; this recipe proves nothing"; exit 1; }
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("trimesh") is None and u.find_spec("cadquery") is None, "another engine leaked in — this recipe no longer proves anything"'
    # -rs: the skip PROFILE is what this environment is for. A bare count
    # cannot be compared between two machines, and the whole reason this job
    # exists is that nobody could see what an engine-only install does not run.
    "$env/bin/python" -m pytest tests/ -q -rs

# Run the WHOLE suite against a cadquery-ONLY install, in a throwaway environment.
#
# Same plain-pip reason as `test-occt-only`, plus one of its own: this install
# lands TWO OCP providers and cannot be made not to. The extra names
# `cadquery-ocp`; build123d brings `cadquery-ocp-proxy`, which brings
# `cadquery-ocp-novtk`; pip installs both because they are different
# distributions, and they own the same top-level `OCP/`. The repo's
# `[tool.uv] override-dependencies` drops novtk, but that is a workspace
# setting and is not carried in wheel metadata, so no consumer gets it.
#
# So this recipe deliberately does NOT assert one provider — `just ocp-guard`
# is for the dev environment. It runs the suite in the environment a user
# actually gets, which is how the two-provider branch of
# `_engine_import_error` was found to be the one branch with no test.
# Measured when added: 670 passed, 111 skipped, 0 failed.
[doc("Run the WHOLE suite against a throwaway cadquery-only install (slow, ~1.5GB)")]
test-cadquery-only:
    #!/usr/bin/env bash
    set -euo pipefail
    env="$(mktemp -d)/venv"
    trap 'rm -rf "$(dirname "$env")"' EXIT
    uv venv --quiet --seed "$env"
    "$env/bin/python" -m pip install --quiet -e '.[cadquery]' pytest
    "$env/bin/python" -c 'import cadquery' || { echo "cadquery did not import — the OCP clobber landed novtk-side; see README"; exit 1; }
    "$env/bin/python" -c 'import importlib.util as u; assert u.find_spec("trimesh") is None, "the mesh extra leaked in — this recipe no longer proves anything"'
    "$env/bin/python" -m pytest tests/ -q -rs

# Run main entrypoint
run *ARGS:
    uv run partspec {{ARGS}}

# Assert exactly one OCP provider is installed (SPEC-backend.md 4.1).
# cadquery-ocp and cadquery-ocp-novtk both own the top-level OCP/ package and
# pip does NOT detect the conflict — one silently clobbers the other.
[doc("Assert exactly one OCP provider is installed")]
ocp-guard:
    uv run python scripts/check_ocp.py

# Remove build artifacts
clean:
    rm -rf .venv dist outputs .pytest_cache .ruff_cache .pyright .mypy_cache .coverage
    # `outputs/` above is only the repo root's. Every exemplar writes its own
    # `examples/<name>/outputs/` on a `check` or `render` and `just clean` left
    # all four behind. Matched by name rather than listed one by one, so a fifth
    # exemplar is covered the day it exists — but NOT derived from
    # `.gitignore`'s `outputs/` line, which it merely happens to agree with:
    # changing that line would not change this recipe.
    find examples -type d -name outputs -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Run the agent-convergence evals (see evals/README.md). Costs real agent calls.
eval *ARGS:
    python3 evals/run.py {{ARGS}}
