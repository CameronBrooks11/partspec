# Gap inventory — partspec as an agent CAD harness

Stock-take 2026-08-06. Status: ✅ built · ⚠️ partial · ❌ absent · 📋 recorded in POST-V0

Framing: what does an AI agent doing mechanical design in CAD-as-code need, end to end?

---

## A. Authoring — the agent writes good CAD code

The user's actual complaint: "way too much LoC or the model is broken."

| | gap | status | missed or deferred? |
|---|---|---|---|
| A1 | No skill shipped by the project for OpenSCAD authoring | ❌ | **MISSED** |
| A2 | No skill for build123d / CadQuery authoring | ❌ | **MISSED** |
| A3 | No idiom guide: parameterise, datums, module decomposition, when hull/minkowski costs more than it saves | ❌ | **MISSED** |
| A4 | The empirical failure catalogue (Manifold non-manifold edges, `assign()` removal, allowance-in-nominal-constant) lives in `results.md` in a **non-git scratch workspace** and ships nowhere | ❌ | **MISSED** |
| A5 | One trivial exemplar (`examples/spacer`). No worked examples at real complexity | ⚠️ | **MISSED** |
| A6 | No complexity discipline — nothing addresses LoC bloat, the single loudest symptom | ❌ | **MISSED** |
| A7 | No lint of the CAD source itself (magic numbers, missing `$fn` policy, boolean epsilon, difference-order traps) | ❌ | **MISSED** |

## B. Perception — the agent sees what it made

| | gap | status | |
|---|---|---|---|
| B1 | No renders. `grep -rn 'png\|camera' src/` returns nothing | ❌ | **MISSED** — and `PLAN.md` §5 lists renders as *deliberately* excluded, a call made for a human-facing checker |
| B2 | No canonical multi-view (iso / front / top / right) | ❌ | **MISSED** |
| B3 | No section cuts — internal features are invisible without them | ❌ | **MISSED** |
| B4 | No visual diff between revisions | ❌ | **MISSED** |
| B5 | No way to visually locate a failing feature | ❌ | **MISSED** |
| B6 | `geometry.triangles` / `distinct_normals` exist, but stats are not perception | ⚠️ | |

**PLAN.md line 278 already says F13 was "visible on re-render, if anyone re-renders that part."**
The need was written down and the capability was excluded anyway.

## C. Verification — this is what got built

| | item | status | |
|---|---|---|---|
| C1 | `check` / `measure`, five statuses, exit codes | ✅ | |
| C2 | D17 per-quantity preconditions, refusal names the defect | ✅ | |
| C3 | Two tiers, capability refusal with `requires` | ✅ | |
| C4 | **Silent contract weakening undetected** | ❌ 📋 | the #1 agent threat; "delete the check" and "fix the part" are the same action to a model |
| C5 | `diff` | ❌ 📋 | |
| C6 | `approximate` machinery unexercised by any v0 check | ⚠️ 📋 | |
| C7 | BREP feature checks — `hole_diameter`, bolt circle, `fillet_radius`, `draft_angle` | ❌ 📋 | **these are what mechanical design actually asserts** |
| C8 | `min_wall` | ❌ 📋 | |
| C9 | `clearance` / `interference` (needs two bodies) | ❌ 📋 | |
| C10 | Printability / DFM | ❌ 📋 | |
| C11 | Vector limits lose which component failed | ⚠️ 📋 | an agent needs the axis to act |

## D. Reference knowledge — the agent knows what "correct" is

**The deepest gap.** Every dogfood payoff came from a human supplying the external reference
(ISO 15, Gridfinity `42n−0.5`, the NEMA 17 pattern, involute gear theory). An agent that does
not already know what a correct part looks like cannot write the contract that would catch it
being wrong. As built, the tool helps a knowledgeable author; it does not make an ignorant
agent competent.

| | gap | status | |
|---|---|---|---|
| D1 | No standards/reference data (fasteners, bearings, NEMA frames, gridfinity, extrusion profiles) | ❌ | **MISSED** |
| D2 | No reusable contract fragments — "conforms to ISO 15 608" should be one import | ❌ | **MISSED** |
| D3 | No shared contract library at all | ❌ | **MISSED** |

## E. Iteration — the repair loop

| | gap | status | |
|---|---|---|---|
| E1 | No harness | ❌ | **MISSED** |
| E2 | No agent contract (bounded attempts, escalation token, feed-failure-forward) | ❌ 📋 | recorded as a note inside POST-V0 §3, never built |
| E3 | **No evidence any agent loop converges using this** | ❌ | **MISSED** — the product was never tested at its stated purpose |
| E4 | No multi-target `check`; OCP import costs seconds per invocation | ❌ | |
| E5 | In-process batching would reuse stale `sys.modules` | ⚠️ 📋 | POST-V0 §8 |
| E6 | Report deliberately carries no remediation (`SPEC-report.md` §9 non-goal) | ⚠️ | a correct call for a human artifact; needs re-examining for an agent consumer |

## F. Interface

| | gap | status | |
|---|---|---|---|
| F1 | No MCP server | ❌ 📋 | D5's "MCP is ~100 lines" is **load-bearing and untested** |
| F2 | CLI is single-target only | ❌ | |
| F3 | Programmatic API (`run()`) exists but is undocumented as a supported surface | ⚠️ | |
| F4 | README never says "agent" or "MCP" — the public face omits the purpose | ❌ | **MISSED** |

## G. Agent-specific guardrails

| | item | status | |
|---|---|---|---|
| G1 | Vacuous green → `EMPTY`, exit 3 | ✅ | |
| G2 | `unsupported` ≠ pass | ✅ | |
| G3 | `measure` refuses to auto-generate checks | ✅ | matters far more for an agent than a human |
| G4 | Contract weakening | ❌ | = C4 |
| G5 | Nothing binds a report to an actual run — a report is a file an agent could simply write | ❌ | **MISSED**, low priority, but it is a hole in "the report is the contract" |

## H. Assemblies — 📋 whole section deferred, correctly (D11)

## I. Distribution

| | gap | status | |
|---|---|---|---|
| I1 | Not on PyPI | ❌ | |
| I2 | No tagged release | ❌ | gated, deliberately |
| I3 | Wheel never built or install-tested | ❌ | workflow's release lens is checking this |

---

## Honest split

**Mis-prioritised (recorded, deferred, defensible individually):** C4–C11, E2, E5, F1, H.
Each has a written reason. The error was cumulative, not individual: every deferral was
justified against "a verification tool for a careful human author", and that was never the
brief.

**Genuinely missed (never written down anywhere):** all of A, all of B, all of D, E1, E3, F4,
G5. These are the layers that make an agent *competent* rather than merely *audited*, and
nothing in the repo acknowledges they exist.

**Root cause.** The brief was "a tool for AI agents doing CAD-as-code." I converted it into "a
verification tool" in the first design pass and then optimised that reading for days — CI
matrices, closure digests, exit-code semantics — all real work on the wrong axis. `AGENTS.md`
in this repo is instructions for agents editing *partspec*, not for agents *using* it, and
that ambiguity let the gap sit in plain sight.
