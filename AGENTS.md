# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project

`partspec` verifies CAD-as-code parts against engineering intent declared in a Python
contract. It builds a part from an OpenSCAD, build123d or CadQuery source, checks it, and
emits a JSON report. Its one distinguishing property, from which most of the design
follows: **silence must never read as success** — a check the tool could not evaluate, or
could not evaluate precisely enough to decide, never reports as a pass.

Status: pre-alpha; **v0.7.5 released on PyPI** (2026-08-14, tag → trusted publishing via
`release.yml`). 0.7.5 closes the comparator's engine-shaped hole, measured by a nine-agent
adoption fleet: `diff` went indeterminate on 3/3 CadQuery replicates and 0/3 OpenSCAD ones,
same command and same version, because an OpenSCAD library is source on disk while a Python
one is an installed distribution and `source_closure.partial` was therefore unconditional.
`source_closure` now carries `imports` (which distributions the model loaded, and whether
their bytes were read or their installer taken at its word) and `unseen` (the gaps, from a
closed vocabulary), and `diff` keys on whether a gap is *bounded* or *irreducible* rather
than on a boolean — so a library that moved under unmoved claims is `identical` and names
the library, while a gap a run could have closed still blocks the claim. `imports` is
process-wide where `check` runs several targets in one process, and `preloaded` names what
a report cannot claim as its own rather than letting `diff` assert it (#216 carries the
real attribution). Also: `measure --out` no longer unlinks a destination that is a build
input, and `diff` compares `environment.packages`, which `SPEC-report.md` said in bold it
must. Its pre-tag audit found the batch-position defect above and four wording defects,
and two rounds of adversarial review then found that each fix for an overclaim had
introduced a quieter one. 0.7.4 before it corrects 0.7.3: the remedy `check` had just started
printing named `pip`, which a `uv venv` does not have — and on a distro that packages one
the word still resolves, to the *system* interpreter, so the fix ran clean and changed
nothing the failing interpreter could see. Hints are now phrased for the interpreter
reading them (`install.py`, `find_spec` and deliberately not `shutil.which`). Both
0.7.3-era findings and this one came from the same place: installing the published artifact
as a stranger would and following its instructions literally. 0.7.3 before it is the first
release cut from an *adoption* measurement rather than
from review: a fresh agent, given a cold install, a community CadQuery library and an
external standard to check it against, spent roughly 40% of its effort discovering the
contract API. `check` now prints `report.hint` — the remedy — instead of leaving it in the
artifact while `measure` and `render` printed theirs; a run-level fault is stated once
rather than once per skipped check; both Python engine factories have docstrings; and
`--help` says where the specs every diagnostic cites actually live. 0.7.2 before it
retracts #109: `uv pip install 'partspec[occt]'` was never broken, and the strand three
releases of documentation blamed on uv was this repo's own
`[tool.uv] override-dependencies`, applied to whatever `uv pip` installs from a directory
under this one. The one code change is the error that names the state. 0.7.1 before it
carried no code change at all, and exists to repair the sdist — the shipped suite passes
in a base install, and the shipped docs no longer cite files the tarball omits. `check`,
`measure` and `render` work
against all three engines (`render`
with `--section` cuts on both tiers), `diff` compares reports and `vdiff` compares renders,
`lint` reads the geometry (tier 2), and `partspec-mcp` serves check/measure/render/vdiff as
stateless MCP tools. **v0.7.0 shipped the depth epic (#136)**: the OCCT tier gained
`draft_angle`, `self_intersection_free`, `step_roundtrip` and `min_wall`, and `min_wall`
made the `approximate` verdict live — a guaranteed interval that straddles a limit now
exits 2 rather than guessing.

v0.7.0 also **narrowed the public surface** — `BBox` deleted, `run` out of `__all__`,
`CheckResult.part_refs` gone, `csg.read_csg`/`contains_strings` gone, and the mesh tier no
longer declares a `raycast` capability it could not keep — **ships `py.typed`** (before it,
a consumer got no type checking at all, silently), and **changed the sdist**, which no
longer carries `notes/` or `evals/`. The mechanical enumerations in the specs are generated
(see Conventions); do not hand-edit a block between `<!-- BEGIN GENERATED -->` markers.
P0–P6 of `docs/PLAN.md` are complete; epic #6 grew the vocabulary to real mechanical
intent (`keep_out`/`keep_in`, `hole_diameter`, `bolt_circle`, `fillet_radius`) and added
the `partspec diff` comparator (`SPEC-diff.md`); epic #5 added reference data with
provenance — `partspec.refs` tables and fragments (`iso15`, `nema17`), cited limits in
the report, and the unattributed-limit disclosure (SPEC-contract §6/§10/§11); epic #4
made the loop trustworthy unattended — bounded builds (`--timeout`),
missing-wheel/environment origin, identifiable `measure` output, multi-target `check`
with module-cache invalidation, the claims pin (`--pin`/`--expect`, SPEC-report §7.1
`expectation`), and the agent contract (`docs/AGENT-CONTRACT.md`); epic #3 shipped the craft — three tested skills, three worked exemplars, the failure catalogue
(`docs/FAILURE-MODES.md`), `partspec lint` tier 1 (`docs/LINT.md`), and the recorded
guidance before/after ([`evals/AUTHORING.md`][authoring-evals]).
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
  lint.py         # tier-1 advisory source lint, engine-free (docs/LINT.md, #26)
  target.py       # <module>[:<factory>] resolution
  install.py      # phrases install hints for the interpreter reading them (uv venvs have no pip)
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
skills/           # teaching material for partspec USERS (contract-authoring, ...)
examples/         # worked exemplars, each README stating what to imitate
evals/            # agent-in-the-loop evidence: convergence (#30), authoring arms (#53)
notes/            # frozen analysis the tracker cites (see notes/README.md; #51)
scripts/          # helper scripts invoked by just recipes
docs/             # the specs and decision log — normative, not background reading
```

## Commands

```sh
just setup           # uv sync --all-extras (ALL engines — matches CI exactly)
just fmt             # ruff format + ruff check --fix + regenerate doc blocks
just gen-docs        # regenerate the generated doc blocks alone
just check           # fmt-check + gen-docs --check + lint + typecheck (CI-equivalent)
just hooks           # every pre-commit hook over the whole tree (CI runs this too)
just test            # pytest
just test-reverse    # the suite in reverse file order — catches cross-test state leaks
just run -- --version
just setup-mesh      # light path: mesh tier only. NOT what CI runs
just test-mesh-only  # the WHOLE suite against a throwaway scipy-free [mesh] install (CI runs this)
just test-mcp-only   # MCP tests against a throwaway engine-free [mcp] install (CI runs this)
just test-no-extras  # the WHOLE suite against a no-extras install (CI runs this)
just ocp-guard       # assert exactly one OCP provider is installed
```

The two OCCT-tier environments take minutes, because OCCT is ~1.5GB. They went
unrun until 2026-08-11 because `uv pip install .[occt]` appeared to strand OCP
(#109) and the shape every other recipe used seemed unable to build them. It
was this repo's own `[tool.uv] override-dependencies`: **`uv pip` reads
`[tool.uv]` from the nearest pyproject.toml above the CWD and applies it to
whatever it is installing**, so any `uv pip install` run from this checkout
resolves against our overrides, published wheels included. Every recipe that
installs into a throwaway environment therefore passes `--no-config`, and
`tests/test_packaging.py` refuses one that does not. CI runs both, gated on the
`changes` path filter so a docs-only PR does not pay for them:

```sh
just test-occt-only      # the WHOLE suite against a throwaway [occt] install
just test-cadquery-only  # ditto [cadquery] — which lands TWO OCP providers, by design
```

The same trap applies to the release cold-verify: install the published wheel
from a directory outside the repo, or the thing you verify is not the thing
users get.

Those two CI jobs set `PARTSPEC_REQUIRE_ENGINES` to the engine the extra
promises, which is the only place in the gate that can tell *the extra
installed* from *the extra works*: `conftest.py` resolves it by importing,
while every `needs_*` marker keys on `find_spec` — and #109 is exactly the
state where the distribution is present and the import fails.

`PARTSPEC_OPENSCAD` pins the engine; `PARTSPEC_REQUIRE_ENGINES=1` turns a missing one from
a skip into a hard failure. CI sets both, across a **two-version matrix** — apt 2021.01 and
a pinned 2026.08.01 snapshot — because F13 is the finding that the same source builds a
different part on a different engine, and because `--backend` does not exist on 2021.01.
Run the suite under both before touching `engines/openscad.py`.

## Conventions

- **The specs in `docs/` are normative.** `SPEC-report.md`, `SPEC-contract.md` and
  `SPEC-backend.md` define behaviour; the code implements them. If code and spec disagree,
  that is a bug in one of them — say which, do not silently pick.
- **Mechanical enumerations inside the specs are GENERATED**, between
  `<!-- BEGIN GENERATED: name -->` markers: the vocabulary tables, the unit table,
  `DIMENSIONAL_KINDS`, the backend protocol block, the README's exit codes. Edit the code
  and run `just fmt`; editing the block by hand is reverted on the next run and `just check`
  fails meanwhile. The prose around them is hand-written and stays normative — only the
  parts that are a projection of the code by definition are generated, because a generated
  spec could never say the code is wrong.
- **Do not write a test that reads a doc and reads the code and diffs them.** That is two
  copies of one fact with a failure report attached; generate the doc instead. Equally, do
  not assert that a phrase appears in prose — `assert "five defect classes in" in README`
  passes when the README says "five defect classes in 2019, all of which failed". A
  substring search reports that a string is present, which is not a claim anyone wanted to
  make. Seven such tests were deleted in #150. What belongs in `tests/test_docs.py` is a
  claim that can be **executed**: the skills' examples build, the README's example runs.
- **Decisions live in `docs/DECISIONS.md`** (D1–D19), each with the reasoning that produced
  it. Do not relitigate a numbered decision; if it is wrong, add a superseding entry.
- **Released `CHANGELOG.md` sections take form-only edits.** Rewriting a citation as a
  link, or fixing a reference that no longer resolves, is allowed and expected: the
  rendered claim is unchanged and a broken reference in a released section is a lie to
  every reader who arrives later. Changing what an entry *claims* is not — that goes in a
  new `[Unreleased]` entry correcting the old one, so "released sections are editable"
  never becomes the reading.
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
  `tests/conftest.py` so CI cannot lose it silently. And **never gate a test module at
  import**: `pytest.importorskip` at module scope raises during collection, so the file
  reports as ONE skipped line and every test in it — including the ones needing nothing —
  leaves the count. Use a per-test `needs_*` marker from `tests/support.py`;
  `test_packaging.py` enforces this and names the three modules that genuinely cannot
  import without their extra.
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

[authoring-evals]: https://github.com/CameronBrooks11/partspec/blob/main/evals/AUTHORING.md
