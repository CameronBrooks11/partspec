# PLAN — `partspec` v0

**Date:** 2026-08-02
**Reads with:** `DECISIONS.md` (D1–D15), `SPEC-report.md`, `SPEC-contract.md`,
`SPEC-backend.md`, `POST-V0.md`.
**Shape:** survey → build → dogfood, following the `scadman` precedent (D1). This working
directory is the survey and is **throwaway**; only its distilled outputs get promoted.

---

## 0. What v0 is, in one sentence

> A CLI that builds a part from an OpenSCAD, build123d or CadQuery source, checks it against
> engineering intent declared in a Python contract, and emits a JSON report whose statuses
> never let silence read as success.

**Success condition** (unchanged since the first pass): enough evidence to decide whether to
retire *"No unit tests for geometry; rely on visual / diff review"* from the CAD domain
profile in `~/.claude/skills/scaffold-new-project/domain-profiles.md`. That is the claim
this project exists to test, and it is falsifiable.

**v0 is done when** three real parts across two engines are under contract, the differential
test passes, and `results.md` exists. Not when the feature list is complete.

---

## 1. Repo shape

Three repos, mirroring `scadman-survey` → `scadman` → `scadman-dogfood`:

| repo | status | notes |
|---|---|---|
| `working-b123d-agentic` | this one | survey. Throwaway. Promote `DECISIONS.md` + the specs, archive the rest. |
| `partspec` | to create | the tool. Apache-2.0 (D9 precedent; also what cad-khana is, which matters for absorbed code). |
| `partspec-dogfood` | to create | **not a git repo** — a scratch workspace, per `scadman-dogfood`. |

Scaffold `partspec` from the `dev-toolbox` `python-uv` template: `uv`, `justfile`
(`setup`/`fmt`/`fmt-check`/`lint`/`typecheck`/`check`/`test`), `AGENTS.md` with a
**Constraints** section, pre-commit with gitleaks, and CI behind the unified `ok` gate.
Python ≥3.12, ruff, pyright.

---

## 2. Phases

Each phase ends in something runnable. No phase is "write the rest of the code."

### P0 — Skeleton and the seam ✅ *done 2026-08-02*

Scaffold; then define, in this order, **before any geometry**:

1. `partspec/report.py` — the report dataclasses and the JSON writer, straight from
   `SPEC-report.md`. Atomic write, `error` placeholder written *before* the engine runs.
2. `partspec/status.py` — the five statuses, verdict precedence, exit-code mapping,
   `ε(limit) = 1e-6 + 1e-7·|limit|`, and interval adjudication.
3. `partspec/backend.py` — the `GeometryBackend` Protocol and value types. No
   implementations.

**Exit criterion:** `partspec check` on a hand-written fake backend emits a schema-valid
report and the right exit code for each of the five statuses. **A conformance test asserts
the schema example in `SPEC-report.md` §7 parses and satisfies its own MUSTs** — that
example is the contract, so it should be executable, not decorative.

Ship the status machinery before any geometry deliberately: it is the thesis, it is where
the design risk lives, and it is testable without a CAD kernel.

### P1 — Mesh backend + OpenSCAD ✅ *done 2026-08-03*

`openscad -D … --export-format binstl` → `trimesh.load_mesh()` → measure. Never parse
`--summary` (D13). Implements: `bbox`, `volume`, `area`, `center_of_mass`, `watertight`,
`solid_count`, `genus`, `triangles`, `facets`. Returns `Unsupported` for topology counts and
self-intersection.

Mesh before OCCT because it is the cheaper install, the faster loop, and the engine with the
largest existing corpus (~30 personal libraries).

**Exit criterion:** the backend measures `bayonet_lock.scad` and returns values verified
against independently-known geometry (analytic where the shape allows, cross-checked against
a second measurement path otherwise), with every quantity correctly flagged `exact` and
topology correctly refused.

> **Corrected 2026-08-03.** This criterion originally read *"`bayonet-lock-scad` under
> contract, with its README's documented rules as `requires` checks"* — which needs the
> contract API from **P2**. A phase whose exit criterion depends on the next phase is not a
> phase. P1 is now verifiable at the backend's own API, which is where it belongs; the
> combined run moves to P2.

### P2 — Contract API ✅ *done 2026-08-03*

`Part`, the source constructors, the closed v0 `kind` vocabulary, target resolution
(`<module>[:<factory>]` with the error message as discovery mechanism), and `requires`
expression evaluation with operand capture.

**Exit criterion:** the `SPEC-contract.md` §1 example runs verbatim, and
`bayonet-lock-scad` passes `just check` with its README's documented rules as `requires`
checks (inherited from P1).

### P3 — `measure` ✅ *shipped early with P2*

The adoption path. Dumps every honestly-available quantity with `exactness`, emits nothing
that would be `unsupported`, produces no verdict.

Early, not late: it is how contracts get *written*, so every subsequent phase is easier with
it. It is also the guard against the temptation to auto-generate checks
(`SPEC-contract.md` §6).

### P4 — OCCT backend *(1 day)*

build123d, plus CadQuery via `bd.Solid(cq_shape.wrapped)` at the front door. Pin one OCP
explicitly and commit the lockfile; add the CI assertion that exactly one `OCP/` provider is
installed, because that failure is silent.

**Exit criterion:** `parametric-sensor-manifold` under contract, with the numeric constraints
already written in prose in its `docs/design_process.md` — *channel diameter ≥ 0.5 mm, print
volume ≤ 100 × 50 × 120 mm, tubing holes 0.05 mm under tubing OD* — made executable.

### P5 — The differential test *(half a day)*

The substitutability proof, and the phase that makes engine-neutrality a property rather
than an assertion. One contract, the same specified part in two engines, reports compared
field-by-field excluding `engine` and `geometry`.

Subject: **gridfinity**, which exists in all three engines under MIT
(`kennetek/gridfinity-rebuilt-openscad`, `Ruudjhuu/gridfinity_build123d`,
`michaelgale/cq-gridfinity`). Any divergence is a tool bug, not a design difference.

⚠️ Expect this to fail first time in an interesting way. Under D15 the OpenSCAD and
build123d gridfinity implementations are *different parts* — rounded corners will differ by
tessellation. **That is the test working.** The contract must be written to the properties
that should genuinely agree (envelope, solid count, genus) and not to volume.

### P6 — Dogfood *(a week of real use)*

Three or more real parts, at least two engines. Then `results.md` in the `scadman-dogfood`
house style: numbered findings, root cause, before/after regression table, and a
**validation-payoff proof** — a case where a check predicted a real failure.

**This is the deliverable.** P0–P5 are setup.

---

## 3. Ordering rationale

Two choices worth defending, since both invert the obvious:

**Report before geometry.** The report is the contract (D5); building it last means
retrofitting honesty onto a tool that already works, which is when honesty loses. It is also
the only part that can be fully tested without a CAD kernel.

**Mesh before BREP**, despite BREP being the richer tier — cheaper install, faster loop,
bigger corpus, and it forces the `unsupported` path to be exercised from day one rather than
bolted on when OpenSCAD support arrives.

---

## 4. Risks, with the honest ones first

| risk | why it matters | mitigation |
|---|---|---|
| **The `approximate` machinery is dead code in v0** | No v0 check can produce it (`SPEC-report.md` §10). Its first real exercise will be its first bug report. | Accept. Unit-test the adjudicator directly with synthetic intervals so it is at least *tested*, even if unexercised. |
| **The parts have nothing interesting to say** | If every contract passes first try, the project has proved nothing. | Deliberately contract a part **known to have a defect**, and confirm the report catches it. A green dogfood run is a failed experiment. |
| ⚠️ **This risk fired.** `bayonet-lock-scad` carries 12 of its own `assert()`s, so OpenSCAD already rejects every invalid parameterisation and partspec's `requires` checks are redundant there (dogfood F1). | The first dogfood subject was the best-defended library in the corpus — the worst choice for demonstrating the tool. | **P6 must start from a library with no asserts** (`NEMA17.scad`, `bearings.scad`, `hotends.scad`). Until then the core claim is untested on a subject that needs it. |
| Silent OCP clobbering | `cadquery-ocp` and `-novtk` both own `OCP/`; pip does not notice | Pin + lock + CI assertion (P4) |
| Contract weakening undetected | Known gap: needs `diff`, out of v0 scope | Recorded in `SPEC-report.md` §7.1. `counts.total` + `contract_digest` make it detectable on comparison |
| Scope creep into assemblies | The absorbed design's best ideas are assembly-level | `POST-V0.md` exists to hold them |

### Deferred setup

- **Branch protection is OFF, deliberately** (decided 2026-08-03) — requiring PRs and the
  `ok` check on a solo repo costs velocity during bootstrap, and the gate already reports
  correctly. Turn on before the first outside contributor, or before v0.1.0 is tagged,
  whichever comes first. Squash-only merges are already locked; what remains is requiring
  the `ok` status check and linear history.

---

## 5. Deliberately not in v0

`diff` · MCP server · renders · assemblies · `clearance`/`interference` · BREP-tier feature
checks (holes, fillets, bolt circles) · `min_wall` · `--allow-incomplete` · a benchmark
suite · PartCAD integration · a viewer.

Each has a recorded reason. None is "we ran out of time."

---

## 6. What promotes out of this directory

To `partspec/docs/`: `DECISIONS.md` (renumbered from D1), the three specs, `POST-V0.md`.
Archived here: the investigations, `SYNTHESIS.md`, `TRIAGE.md`, `DIRECTION.md` — the
reasoning trail, per D7 of the scadman precedent (*"only its stable outputs are promoted"*).
