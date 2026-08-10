<!-- Vendored 2026-08-09 from the survey workspace (working-b123d-agentic),
     unmodified below this header. Cited under **Backing:** by the specs in
     docs/, which pointed at a path no reader of this repository could open —
     the loss class notes/README.md exists to prevent. -->

# Investigation 3 — What "absorbing cad-khana" actually means

**Date:** 2026-08-02. Based on a full source read of `cyberchitta/cad-khana` @ v0.2.0.

---

## 1. Maturity — absorb the design, do not depend on the package

| signal | value |
|---|---|
| commits / contributors | 92 / **1** (`restlessronin`) |
| releases / tags | **none** (v0.2.0 exists only in `pyproject.toml`) |
| CI / lint / typecheck | **none at all** — no `.github/` |
| tests | **361 test functions, ~3,700 LOC vs ~3,750 src LOC** — genuinely good |
| status | `Development Status :: 2 - Pre-Alpha`; "API may still churn" |
| activity | 29 commits Apr · 34 May · **0 Jun** · 29 Jul — bursty, one person |
| stability | `khana build` was **retired last week of activity**; `check()` signature broke with no shim |

Real provenance though: it drove the Sorted Studs LEGO scanner, every part LLM-drawn, and
the docstrings cite concrete measured windows from that machine. The non-obvious
abstractions were pulled out of a working mechanism, not imagined.

**Verdict: high-quality single-author prototype. "Absorb the design, don't take the
dependency" is exactly right — which is what Cameron already said.** Apache-2.0 makes
lifting code legitimate with attribution.

---

## 2. The finding that resolves the neutrality question

> **The build123d coupling is pervasive by *type* but shallow by *behaviour*.**

build123d types (`Part`, `Location`, `Plane`, `Axis`, `Color`, `Shape`, `ShapeList`) leak
into the dataclass field types throughout. But the *actual geometric query surface* is
twelve primitives:

1. `a & b` → intersection volume
2. `.volume`
3. `.area`
4. `.bounding_box()`
5. `.center()`
6. `.is_valid`
7. `.faces()/.edges()/.vertices()` (counts only)
8. `.distance_to(b)` — min surface-to-surface distance
9. `.moved(location)`
10. `Plane(...).to_local_coords(shape).bounding_box()` — directed extent
11. `.tessellate(lin_tol, ang_tol)`
12. `.find_intersection_points(axis)` — ray cast, for min-wall

Define a `GeometryBackend` protocol over those twelve, plus own value types
(`Transform`/`Plane`/`Vec3`/`BBox`), and **~2,000 LOC of the valuable logic becomes
engine-neutral with no loss**. `sweep.py`, `check.py`, `diff.py`, `hints.py` need *zero*
changes — they only touch `intersection_volume`, `bounding_box`, and dicts.

**This is the single most important design input of the whole review.** It means
engine-neutrality is not a rewrite; it is a well-bounded protocol extraction over a dozen
methods, and the design being absorbed was already ~90% engine-independent logic.

### Per-engine porting cost

- **CadQuery: easy (~1–2 days).** Also OCCT/OCP — identical semantics, different spellings.
  Only two real gaps: `distance_to` (drop to `BRepExtrema_DistShapeShape`, which is what
  build123d does internally anyway) and `find_intersection_points`
  (`BRepIntCurveSurface_Inter`). ~20 lines of OCP each.
- **OpenSCAD mesh: moderate, and honestly lossy.**
  - *Free or easier:* bbox, volume, area, center, tessellate (it **is** a mesh), and ray
    casting (mesh raycast is faster and more robust than the BRep version). `min_wall` and
    overhang detection port almost unchanged — `core/tessellation.py` is 32 lines producing
    `(centroid, normal, area)` triangles, which is a mesh's native form.
  - *Needs substitution:* boolean intersection volume (manifold3d/CGAL — and
    `INTERFERENCE_VOLUME_EPSILON_MM3 = 0.001` must be re-tuned); `distance_to` → mesh
    proximity, which is **approximate and tessellation-dependent**.
  - *Becomes meaningless:* `face/edge/vertex_count` (BRep topology ≠ triangle counts — and
    the SKILL.md sells these as "the cheapest way to verify a boolean changed geometry",
    which does not transfer); `is_valid` (different notion entirely).
  - *Needs full replacement:* HLR line-art. Mesh silhouette + crease extraction with hidden
    line removal is substantially harder than calling OCCT's HLR.

⚠️ **The sharpest hazard:** `assert_clearance` and `assert_tangent_contact(tol_mm=1e-3)`
silently degrade on meshes, because chord error typically exceeds that tolerance. A
clearance assertion that is exact on BREP becomes approximate on OpenSCAD **without
changing its name or its report shape.** That must be surfaced explicitly in the report,
or it is precisely the "conforms: true as a stop signal" trap in a new costume.

---

## 3. What to absorb

**The assertion model.** Eight primitives, each a frozen dataclass with `part_refs`,
`qualified(prefix, location)`, `evaluate(parts)`:
`NoInterference · Clearance · TangentContact · AllowedContact · ExpectedInterference ·
Distance · ScalarClaim · AnchorsCoincident`, plus group macros that expand to the
single-pair forms with identical auto-names.

**Claims live inside the model value, not in a sidecar.** `Assembly` is
`@dataclass(frozen=True)` with `parts / subassemblies / assertions / anchors`; every
`with_*`/`assert_*` returns a new one via `replace`. Attachment is **by dotted path name**
(`"turret.rotor.arm"`), resolved at evaluation against a flat `{path: Part}` dict. No face
or edge selectors — the entire vocabulary is whole-solid plus one datum-`Plane` target.

That last point is a deliberate and very good simplification: **it sidesteps the
topological-naming problem entirely**, which the memo named as a central hard problem. It
also means the backend only ever answers whole-solid queries — which is exactly why twelve
primitives suffice.

**Ideas worth stealing outright:**

- **`qualified()` propagation** — a sub-assembly declares a claim once at the level that
  owns the knowledge; composing it into a parent re-frames the claim automatically. This is
  contract-first composition, and it is the best idea in the codebase.
- **Tri-state `passed: True | False | None`** with a principled skip when a referenced part
  is absent. *"Absence is a legitimate run state, not an input error."* This is precisely
  the shape needed for `unsupported` in a tiered engine model — the pattern already exists.
- **`JointWindow` phase gating on joint angle, not animation `t`.** Outside its window an
  `AllowedContact` collapses to no-interference rather than going blind. Re-timing the
  animation cannot invalidate the claim.
- **`drop_contact_shadowed`** — order-free contradiction resolution: group-expanded
  `NoInterference` yields to a hand-declared `AllowedContact` on the same pair, but a
  *hand-written* `NoInterference` never does — "that contradiction is yours to see."
- **Record `value` even on pass**, so `diff` can report **drift on assertions whose pass/fail
  state did not change** — "drift the boolean can't see." Nobody else builds this and it is
  what makes the tool usable in a refactor.
- **`BOUND_EPSILON = 1e-6`** applied to every bound comparison, because consumers derive
  geometry from the same constant they bound against.
- **Deferred failure roll-up** (`_failures.py`) so a batch run leaves every JSON fresh
  rather than aborting midway and leaving stale files that read as current. Includes a
  measured note that `atexit` cannot do this (CPython 3.13 exits 0).
- **`min_wall_alignment`** — a scalar distinguishing "wedge tip" from "real sliver", which
  is what makes a min-wall number actionable instead of a false-alarm generator.
- **Anchors as cross-unit interface contracts** — each unit exports where it *believes* a
  shared datum is; the parent asserts the beliefs coincide after placement. Resolved both at
  declaration time (typo fail-fast) and check time (so joint angles are honored).

**The agent contract in `SKILL.md` (1,318 lines) — arguably the most valuable artifact:**

- Bounded repair loop, **3–5 attempts**, then mandatory machine-greppable escalation:
  `HUMAN_REVIEW: <why> — last failure: <assertion or error>`. *"Escalation is a feature,
  not a failure mode."*
- **"Vacuous green"** named as an anti-pattern: a module with no assertions exits 0 and
  writes `"assertions": []`. *"That is not a passing design; it is an unasked question, and
  an agent will read it as success."* Same family as the unsupported-vs-pass hazard — both
  are "silence read as success."
- Feed failure forward: each retry carries the previous failing script, the JSON slice, and
  the original task. *"Don't restart from scratch."*
- Token-aware drawing: *"load only the view that answers your question"* + a question→view
  table. Ten views exist; loading all ten by default is called out as waste.
- `hint` before traceback — a pattern-matched one-line repair suggestion read first.

---

## 4. What to leave behind

- `export.py` (646 LOC) — 630 of it is glTF animation injection with hand-rolled quaternion
  math and a `gltf-transform` shell-out, serving an unreleased sibling project
  (`chitra-cad`). STL/STEP export is 12 lines.
- `draw.py` (494) — the HLR call is 6 lines; the rest is competent but ordinary raster/SVG
  plumbing, coupled to OCCT's `GeomType` and adaptor API.
- `hints.py` — six regexes mapping build123d/OCCT errors to fixes. Cheap, effective, 100%
  engine-specific; write your own.
- **The five type leaks that constitute the entire lock-in:** `Part`/`Location`/`Plane`/
  `Axis`/`Color`/`Shape`/`ShapeList` appearing in `PlacedPart`, `Anchor`, `RevoluteJoint`,
  `Distance`, and `with_part`'s isinstance guard. Replacing these with own value types is
  mechanical and well-bounded.

---

## 5. Consequences for our design

1. **The declaration model should be Python, not sidecar YAML** — reversing the draft
   sketch. Python is more expressive, needs no schema (avoiding the DSL trap that
   `agent-policy`'s decision log calls *"a cautionary tale"* and marks **locked**), matches
   the `Spec.__post_init__` idiom already in `build123d-template`, and — critically — a
   Python contract module can reference a **`.scad` file** just as easily as a Python
   model. The contract does not need to be in the model's language.
2. **The silent-weakening objection to code-as-contract is answered by `diff`.** A semantic
   report differ that reports `removed:` assertions catches an agent quietly deleting a
   claim, which a YAML schema would not do any better.
3. **`unsupported` already has a home** — extend the existing tri-state skip rather than
   inventing a fourth state.
4. **CLI-first is confirmed by the author's own plan**: `CLAUDE.md` carries
   `# mcp.py  # future: MCP server over the same primitives`, with the discipline note that
   library modules have no CLI or MCP dependencies. Same conclusion, reached independently.
5. **Watch the O(n²):** interference is unconditional all-pairs OCCT booleans, documented
   as good to "~20 parts". Fine for parts and small assemblies; a real ceiling to know about.
