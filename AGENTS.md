# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project

`partspec` verifies CAD-as-code parts against engineering intent declared in a Python
contract. It builds a part from an OpenSCAD, build123d or CadQuery source, checks it, and
emits a JSON report. Its one distinguishing property, from which most of the design
follows: **silence must never read as success** — a check the tool could not evaluate, or
could not evaluate precisely enough to decide, never reports as a pass.

Status: pre-alpha; **v0.3.0 released on PyPI** (2026-08-08, tag → trusted publishing via
`release.yml`). `check`, `measure` and `diff` work against all three engines, `render` on
the mesh tier, and `partspec-mcp` serves check/measure/render as stateless MCP tools.
P0–P6 of `docs/PLAN.md` are complete; epic #6 grew the vocabulary to real mechanical
intent (`keep_out`/`keep_in`, `hole_diameter`, `bolt_circle`, `fillet_radius`) and added
the `partspec diff` comparator (`SPEC-diff.md`); epic #5 added reference data with
provenance — `partspec.refs` tables and fragments (`iso15`, `nema17`), cited limits in
the report, and the unattributed-limit disclosure (SPEC-contract §6/§10/§11); epic #4
(unreleased) made the loop trustworthy unattended — bounded builds (`--timeout`),
missing-wheel/environment origin, identifiable `measure` output, multi-target `check`
with module-cache invalidation, the claims pin (`--pin`/`--expect`, SPEC-report §7.1
`expectation`), and the agent contract (`docs/AGENT-CONTRACT.md`).
What remains withheld, and why, is `docs/POST-V0.md`.

## Stack

- **Python ≥3.12**, `uv` for dependency management, `hatchling` build backend
- **ruff** (format + lint), **pyright** (`standard`), **pytest**
- **Engines are optional extras**: `mesh` (trimesh + manifold3d), `occt` (build123d),
  `cadquery`. The `openscad` binary is a system dependency.

## Layout

```
src/partspec/
  status.py       # statuses, verdicts, exit codes, epsilon, adjudication  <- the thesis
  report.py       # the report artifact, serialisation, write semantics
  backend.py      # GeometryBackend protocol + value types
  contract.py     # Part, Source, the closed check vocabulary
  region.py       # keep_out/keep_in region data + the canonical polyhedron both tiers materialize
  provenance.py   # Referenced values: numbers that carry their citation (SPEC-contract 10)
  refs/           # cited reference tables + fragments (iso15, nema17) — SPEC-contract 10/11
  expectation.py  # the claims pin: --pin/--expect, weakening caught with no baseline (#31)
  expr.py         # restricted-AST evaluation for `requires`, with operand capture
  target.py       # <module>[:<factory>] resolution
  runner.py       # phase orchestration: parameters -> build -> geometry -> report
  cli.py          # argparse entry point
  diff.py         # semantic comparison of two reports (SPEC-diff.md)
  mcp.py          # MCP adapter: stateless tools over check/measure/render, subprocess per call (D18)
  backends/
    mesh.py       # OpenSCAD tier — trimesh, measured as exported (D15, D17)
    occt.py       # build123d AND CadQuery, one implementation (D3)
  engines/
    openscad.py   # render to binstl; never parses --summary (D13)
    pycad.py      # import + call a Python model; the `.wrapped` adopt shim
tests/            # mirrors src; also asserts docs/SPEC-report.md's example conforms
scripts/          # helper scripts invoked by just recipes
docs/             # the specs and decision log — normative, not background reading
```

## Commands

```sh
just setup           # uv sync --all-extras (ALL engines — matches CI exactly)
just fmt             # ruff format + ruff check --fix
just check           # fmt-check + lint + typecheck (CI-equivalent)
just test            # pytest
just run -- --version
just setup-mesh      # light path: mesh tier only. NOT what CI runs
just test-mesh-only  # mesh tests against a throwaway scipy-free [mesh] install (CI runs this)
just test-mcp-only   # MCP tests against a throwaway engine-free [mcp] install (CI runs this)
just ocp-guard       # assert exactly one OCP provider is installed
```

`PARTSPEC_OPENSCAD` pins the engine; `PARTSPEC_REQUIRE_ENGINES=1` turns a missing one from
a skip into a hard failure. CI sets both, across a **two-version matrix** — apt 2021.01 and
a pinned 2026.08.01 snapshot — because F13 is the finding that the same source builds a
different part on a different engine, and because `--backend` does not exist on 2021.01.
Run the suite under both before touching `engines/openscad.py`.

## Conventions

- **The specs in `docs/` are normative.** `SPEC-report.md`, `SPEC-contract.md` and
  `SPEC-backend.md` define behaviour; the code implements them. If code and spec disagree,
  that is a bug in one of them — say which, do not silently pick.
- **Decisions live in `docs/DECISIONS.md`** (D1–D19), each with the reasoning that produced
  it. Do not relitigate a numbered decision; if it is wrong, add a superseding entry.
- **Status claims are part of the gate.** The "Status:" line here and in `README.md` say
  what does and does not work. Both were left asserting the backends were unimplemented for
  three phases after they shipped — in a project whose whole point is that a tool must not
  claim more than it has established. Treat them as code: if a change makes one false, the
  change is not finished.
- Comments explain *why*, and cite a spec section or a measured number where one exists.
  Do not add comments restating what the line does.
- Tests mirror source structure. Test names state the claim being made.
- `uv.lock` **is committed** — see Constraints.

## Constraints

- **Importing `partspec` must not import a CAD engine.** build123d, CadQuery, trimesh,
  manifold3d and OCP load lazily inside their backends. This keeps the parameter phase fast
  and is enforced structurally by the core having zero required dependencies.
- **A backend must never return a plausible-looking number in place of an answer.** If the
  representation lacks the entity, return `Unsupported`. Do not fit, reconstruct, or
  approximate your way to a result — a mesh has no cylindrical face, and inventing one
  produces confident wrong numbers in the unsafe direction.
- **Check the precondition before measuring, and make it narrow** (D17). Volume and centre
  of mass need a closed, consistently-wound surface; genus needs a closed single body; a
  body count needs no edge shared by more than two faces. `bbox`, `area` and `watertight`
  need nothing. This is not paranoia — every one of those returned a confident wrong number
  on an open mesh until 2026-08-05. Equally, do **not** refuse more than the mathematics
  requires: an unnecessary `unsupported` pushes a part to `incomplete`, which is also a way
  of failing to answer an answerable question.
- **Never read an absolute measurement out of a library that rebuilds its input** (D17).
  manifold3d retriangulated 55 of 10,688 triangles on a *clean* part and moved its volume by
  0.078%; measurements taken from it describe its reconstruction, not the exported artifact,
  which D15 forbids. And when such a library reports an error status, believe it —
  manifold3d's rejected objects still answer `.decompose()` and `.genus()`.
- **Do not make the mesh tier depend on scipy.** It reaches a dev machine only through
  build123d/cadquery, so such a dependency passes locally *and* in CI while breaking every
  `pip install partspec[mesh]` user. `just test-mesh-only` is the guard, and CI runs it as
  its own job — it was local-only for a while, which meant the detector for a
  "passes-in-CI" failure was itself absent from CI.
- **A skipped test is not a passing test.** The suite once reported 195 passed / 23 skipped
  in CI because no runner had OpenSCAD, and those 23 were the entire end-to-end path. If you
  add a `skipif` for a missing tool, add the tool to `PARTSPEC_REQUIRE_ENGINES` handling in
  `tests/conftest.py` so CI cannot lose it silently.
- **Never let an unevaluated check exit 0.** `Verdict.INCOMPLETE` maps to exit 2 on purpose.
- **Do not add a `--allow-incomplete` flag** without a recorded case where `incomplete` is a
  part's genuine long-term state. Shipping the escape hatch alongside the discipline means
  the discipline is never tested.
- **Pin exactly one OCP provider.** `cadquery-ocp` and `cadquery-ocp-novtk` both own the
  top-level `OCP/` package (326 vs 322 files) and pip does not detect the conflict — one
  silently clobbers the other, and when novtk wins **CadQuery cannot import at all**. A
  `[tool.uv] override-dependencies` marker drops novtk from resolution; `just ocp-guard`
  asserts the outcome in CI. This is also why `uv.lock` is committed rather than ignored.
- **`just setup` installs ALL extras, and CI runs the same recipe.** The lighter mesh-only
  sync produced real CI drift: pyright resolved build123d locally and not in CI, so
  `just check` gave two different answers. If you use `just setup-mesh`, expect `just check`
  to differ from the gate.
- Do not add a dependency without justification; the core is stdlib-only by design.
- Do not commit secrets or credentials.
