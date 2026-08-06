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

The semantic report differ. Consumes two reports, emits its own artifact. Reports
`regressed` / `fixed` / `added` / `removed` per check, **plus value drift on checks whose
pass/fail state did not change** — "drift the boolean can't see." A wall thinning from
2.9 mm to 2.1 mm against a 2.0 mm minimum is two passes and one important trend.

This is why `SPEC-report.md` §7.2 mandates recording measurements on pass. The field exists
in v0; the consumer does not.

**It closes the one known undetected gap in v0:** silent contract weakening. An agent that
deletes a check produces an internally consistent green report; `counts.total` and
`contract_digest` make that *detectable on comparison*, not visible on inspection. `diff` is
the comparison.

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

~100 lines over `check` / `measure`, once the report is machine-readable (D5). Deliberately
after real CLI use, so the tool surface is shaped by what an agent actually needed rather
than by what seemed useful in advance.

Worth designing against cad-khana's `SKILL.md` agent contract, which is the strongest
artifact in that repo: a bounded **3–5 attempt** repair loop, machine-greppable escalation
(`HUMAN_REVIEW: <why> — last failure: <assertion>`), feeding failure forward rather than
restarting, and the **vacuous green** warning ("check `assertions` is non-empty before
believing a green run on an unfamiliar file").

---

## 4. BREP-tier checks

`hole_diameter`, `hole_pattern` / bolt circle, `fillet_radius`, `draft_angle`,
`self_intersection`, `step_roundtrip`. All `unsupported` on mesh, irreducibly — no
conversion recovers them (`investigations/04` §4).

**These are the first checks that will exercise the `approximate` machinery**, so whichever
lands first should be treated as the real test of `SPEC-report.md` §3.1 rather than as a
routine feature.

`self_intersection` additionally needs a mesh-side answer that is neither GPL (libigl/CGAL)
nor heavyweight (pymeshlab) — currently an open dependency question (D14).

---

## 5. `min_wall`

Deferred with a specific reason worth preserving: it is **`unsupported`, not
`approximate`**, because sampling is one-sided by construction — more samples can only ever
find a *thinner* wall — so a measurement is an upper bound on the true minimum and no
principled `lo` exists.

It ships when either a defensible lower bound is derived, or the BREP tier makes a different
method available. Absorb cad-khana's **`min_wall_alignment`** scalar when it does: it
distinguishes a wedge tip from a real sliver, and is what makes the number actionable rather
than a false-alarm generator.

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
- **Per-component vector statuses** (`SPEC-report.md` Q8) — vector adjudication takes the
  worst component, losing which one failed.
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

Found while adding the Python source closure (2026-08-05). D5 answers OCP's multi-second
import cost with **batching** — one process evaluating many contracts — rather than a daemon.
That is still right, but it has a consequence nothing currently handles: `sys.modules` caches
a model's helper modules, so a second contract in the same process that imports an edited
helper gets the *previous* version of it.

No live bug in v0: the CLI is one process per target and `run-batch.sh` invokes it per target.
It becomes real the moment either the MCP server (§3) or a multi-target `check` lands, and it
fails in the worst available way — a stale build reported as a fresh one, with a closure
digest computed from the edited file on disk that never reached the interpreter. Whichever
lands first owns invalidating the model's directory subtree from `sys.modules` between runs.
