# POST-V0 — the backlog, recorded now so v0 carries it

**Date:** 2026-08-02
**Why this exists:** D11 scopes v0 to parts only, but requires the v0 model to *carry*
assemblies rather than be retrofitted. Writing the backlog now is what makes that possible —
and it is also where the best ideas being absorbed from cad-khana live, so leaving them
unrecorded would quietly lose them.

Nothing here is scheduled. This is a holding pen, not a roadmap.

---

## 1. Assemblies — the largest item

Everything below is from `investigations/03-cad-khana-absorption.md` and is deferred whole.
**Scheduling decision, 2026-08-07:** D19 places assemblies after v1.0 — the v1.0 budget
goes to part-level depth of intent. This section is the design basis for when they begin.

**The design constraints v0 must honour to keep this cheap** (all adopted at no cost, per
`SPEC-contract.md` §9): `checks[].id` is a free-form string so dotted paths fit; every check
records `part_refs` even though v0 always has one part; and `skipped` already means
*"absence is a legitimate run state, not an input error"*, which is exactly what a
standalone sub-assembly run needs.

**What lands with assemblies:**

- **`qualified()` propagation** — a sub-assembly declares a claim once, at the level that
  owns the knowledge; composing it into a parent re-frames it automatically. The best single
  idea in cad-khana, and the one most worth getting right.
- **Anchors as cross-unit interface contracts** — each unit exports where it *believes* a
  shared datum is, in its own frame; the parent asserts the beliefs coincide after
  placement. Replaces mirror-constant + drift-assert pairs.
- **Relational checks** — `clearance`, `interference`, `tangent_contact`, `allowed_contact`,
  `expected_interference`. These were briefly listed as v0 in `DIRECTION.md` §5 because they
  are capability-portable; that was a category error (they take two bodies). The portability
  finding stands: `manifold3d.min_gap` returned exactly 7.5, and intersection volume was
  exact on both tiers.
- **`JointWindow` phase gating** — an allowed contact valid only during a joint-angle
  window, gated on **joint angle rather than animation `t`**, so re-timing cannot invalidate
  a claim. Outside its window it collapses to no-interference rather than going blind.
- **`drop_contact_shadowed`** — order-free contradiction resolution: a group-expanded
  `NoInterference` yields to a hand-declared `AllowedContact` on the same pair, but a
  hand-written one never does — *"that contradiction is yours to see."*
- **`sweep`** — `factory(t) -> Assembly` as the motion primitive, with bracket-then-bisect
  onset detection and the `angles_at_contact` (inner) vs `angles_bracketing` (outer) bound
  distinction.

**Known ceiling to design around:** cad-khana's interference is unconditional all-pairs OCCT
booleans, documented good to **~20 parts**. Fine for real assemblies; worth knowing before
someone points it at a machine.

**Also needs `Transform` and `Plane`** in the backend value types (`SPEC-backend.md` §2),
deliberately omitted from v0.

---

## 2. `diff` — and the gap it closes

**Shipped 2026-08-07 (#83): `partspec diff`, spec'd in `SPEC-diff.md`.** The section
below is the design basis it was built from.

The semantic report differ. Consumes two reports, emits its own artifact. Reports
`regressed` / `fixed` / `added` / `removed` per check, **plus value drift on checks whose
pass/fail state did not change** — "drift the boolean can't see." A wall thinning from
2.9 mm to 2.1 mm against a 2.0 mm minimum is two passes and one important trend.

This is why `SPEC-report.md` §7.2 mandates recording measurements on pass. The field exists
in v0; the consumer does not.

**It closes the one known undetected gap in v0:** silent contract weakening. An agent that
deletes a check produces an internally consistent green report; `counts.total` and
`contract_digest` make that *detectable on comparison*, not visible on inspection. `diff` is
the comparison. *(Since #31 the gap is also closed with no baseline in hand: the claims pin
— `check --pin` / `--expect` — fails a single run whose declared claim set drifted from its
committed lock, naming what moved.)*

Needs a numeric tolerance (`1e-6`), not exact float equality — rebuilding identical geometry
through a different transform-composition order perturbs coordinates at ~1e-13, and exact
comparison would report noise and bury signal.

**It must also honour `part.source_closure.partial`** (`SPEC-report.md` §8.3). Matching
digests on a partial closure mean "nothing we looked at changed", not "nothing changed", and
a differ that reports the two as identical inputs would be making the same
silence-as-success mistake at the provenance layer. Treat it as `unsupported` is treated for
a check.

---

## 3. MCP server

**Shipped 2026-08-07 (#63, #66): `partspec-mcp`,** stateless `check` / `measure` / `render`
tools, each a fresh subprocess returning the artifact the CLI writes (D18). The paragraph
below was the design basis; D5's "~100 lines" estimate held.

The other half **shipped 2026-08-08 (#28): `docs/AGENT-CONTRACT.md`** — cad-khana's
`SKILL.md` agent contract, the strongest artifact in that repo, rebuilt against this
tool's real surfaces: a bounded **5-attempt** repair loop, machine-greppable escalation
(`HUMAN_REVIEW: <why> — last failure: <check id>: <detail>`), feeding failure forward
rather than restarting, the **vacuous green** checklist (counts, attribution, closure,
expectation), and the out-of-bounds section naming the guards (#31's claims pin, `diff`,
`attribution`) that watch the weakening moves it forbids.

---

## 4. BREP-tier checks

~~`hole_diameter`~~ (shipped 2026-08-07, #80 — `SPEC-contract.md` §4.5), ~~`hole_pattern` /
bolt circle~~ (shipped 2026-08-07, #81 — §4.6), ~~`fillet_radius`~~ (shipped 2026-08-07,
#82 — §4.7), ~~`draft_angle`~~ (shipped 2026-08-08, #137 — §4.8),
~~`self_intersection`~~ (shipped 2026-08-08, #138 — §4.9), ~~`step_roundtrip`~~
(shipped 2026-08-08, #139 — §4.10). All
`unsupported` on mesh, irreducibly — no conversion recovers them (`investigations/04` §4).

**These were predicted to be the first checks to exercise the `approximate` machinery.**
The prediction failed on its first member: `hole_diameter` landed exact, because a BREP
cylinder's radius is a surface parameter, not an estimate. §3.1's real test is still
outstanding, and whichever check first carries a genuine error interval inherits the
obligation.

`self_intersection` additionally needs a mesh-side answer that is neither GPL (libigl/CGAL)
nor heavyweight (pymeshlab) — currently an open dependency question (D14).

---

## 5. `min_wall` — SHIPPED on the BREP tier (2026-08-09, #140 — SPEC-contract §4.11)

The deferral reason held for the mesh tier and is now recorded with executed evidence
(§4.11): sampling is one-sided by construction — more samples can only ever find a
*thinner* wall — so no principled `lo` exists there, and every erosion-style candidate
was executed and refused. The ship condition ("the BREP tier makes a different method
available") was met by the face-pair minimum-distance method: kernel-exact `lo`,
witnessed-span `hi`, a guaranteed interval that finally exercises the `approximate`
machinery. cad-khana's `min_wall_alignment` was reconstructed and falsified by execution
(a shallow taper measures alignment 0.995); the shared-edge exclusion replaces it
structurally.

---

## 6. Printability

`overhang` is mesh-native and *better* on mesh than on BREP (per-triangle normals vs point
sampling), so it is cheap. Deferred only because printability is a different concern from
dimensional intent and would widen v0's story.

Also: trapped-volume detection by voxel flood-fill, and the commercial DFM advisories worth
reimplementing (*part too big*, *small gap <0.75 mm*, *thin wall*, *material left behind*).

**There is no open-source DFM check library to adopt** — slicers do no DFM at all, and
`dfm-checker`/`AMDFM` do not exist. PySLM (trimesh-based) is the closest reusable component.
That gap is a genuine opportunity if this project ever wants one.

---

## 7. Smaller items

- **`geometry.facets` on the OCCT tier** — currently mesh-only. Would need a deliberate
  tessellation, which is a design choice rather than a measurement.
- ~~**Per-component vector statuses** (`SPEC-report.md` Q8)~~ — shipped 2026-08-07 as
  `checks[].components` (#84).
- **`skipped` vs `unsupported` exit codes** (Q1) — currently share `2`; they differ in kind.
- **`--allow-incomplete`** — withheld deliberately, not forgotten. Add only if the dogfood
  run shows a case where `incomplete` is genuinely a part's right long-term state rather
  than a gap to close.
- **A benchmark suite** — the `journal-decision-engine` idiom (`gold-set.json`, `scorecard`,
  `just scorecard-diff baseline candidate`) is ready to reuse. Deliberately after dogfooding,
  which gives the same failure-mode information far more cheaply.
- **PartCAD as a parts source** — out of scope for v0 (D12), but its `interfaces:`/mating
  model remains the best existing prior art for declaring mechanical interfaces as data, and
  is the natural reference when assemblies land.

---

## 8. In-process batching invalidates a stale Python model cache

**Shipped 2026-08-08 (#29):** multi-target `check` landed with the invalidation this
section demanded — the model's directory subtree is evicted from `sys.modules` after
every Python-engine build, in `run()` itself rather than only between batch targets,
because PR #101's review demonstrated the staleness live in a plain two-build process.
The paragraph below is the design basis.

Found while adding the Python source closure (2026-08-05). D5 answers OCP's multi-second
import cost with **batching** — one process evaluating many contracts — rather than a daemon.
That is still right, but it has a consequence nothing previously handled: `sys.modules` caches
a model's helper modules, so a second contract in the same process that imports an edited
helper gets the *previous* version of it — a stale build reported as fresh, with a closure
digest computed from the edited file on disk that never reached the interpreter.
