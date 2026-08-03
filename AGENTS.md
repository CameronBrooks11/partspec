# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project

`partspec` verifies CAD-as-code parts against engineering intent declared in a Python
contract. It builds a part from an OpenSCAD, build123d or CadQuery source, checks it, and
emits a JSON report. Its one distinguishing property, from which most of the design
follows: **silence must never read as success** — a check the tool could not evaluate, or
could not evaluate precisely enough to decide, never reports as a pass.

Status: pre-alpha. The report/status seam is implemented; the contract API and backends are
not. See `docs/PLAN.md`.

## Stack

- **Python ≥3.12**, `uv` for dependency management, `hatchling` build backend
- **ruff** (format + lint), **pyright** (`standard`), **pytest**
- **Engines are optional extras**: `mesh` (trimesh + manifold3d), `occt` (build123d),
  `cadquery`. The `openscad` binary is a system dependency.

## Layout

```
src/partspec/
  status.py     # statuses, verdicts, exit codes, epsilon, adjudication  <- the thesis
  report.py     # the report artifact, serialisation, write semantics
  backend.py    # GeometryBackend protocol + value types (no implementations yet)
  cli.py        # argparse entry point
tests/          # mirrors src; also asserts docs/SPEC-report.md's example conforms
scripts/        # helper scripts invoked by just recipes
docs/           # the specs and decision log — normative, not background reading
```

## Commands

```sh
just setup        # uv sync
just fmt          # ruff format + ruff check --fix
just check        # fmt-check + lint + typecheck (CI-equivalent)
just test         # pytest
just run -- --version
just ocp-guard    # assert exactly one OCP provider is installed
```

## Conventions

- **The specs in `docs/` are normative.** `SPEC-report.md`, `SPEC-contract.md` and
  `SPEC-backend.md` define behaviour; the code implements them. If code and spec disagree,
  that is a bug in one of them — say which, do not silently pick.
- **Decisions live in `docs/DECISIONS.md`** (D1–D15), each with the reasoning that produced
  it. Do not relitigate a numbered decision; if it is wrong, add a superseding entry.
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
- **Never let an unevaluated check exit 0.** `Verdict.INCOMPLETE` maps to exit 2 on purpose.
- **Do not add a `--allow-incomplete` flag** without a recorded case where `incomplete` is a
  part's genuine long-term state. Shipping the escape hatch alongside the discipline means
  the discipline is never tested.
- **Pin exactly one OCP provider.** `cadquery-ocp` and `cadquery-ocp-novtk` both own the
  top-level `OCP/` package and pip does not detect the conflict — one silently clobbers the
  other. This is why `uv.lock` is committed rather than ignored.
- Do not add a dependency without justification; the core is stdlib-only by design.
- Do not commit secrets or credentials.
