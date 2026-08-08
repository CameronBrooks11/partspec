# Observed CAD-as-code failure modes

**Status:** v1 · 2026-08-08 · closes #24
**Source:** the 2026-08-03/05 dogfood runs (partspec 0.1.0, 15 targets, 18-library
OpenSCAD corpus plus community CadQuery/build123d models), distilled from the scratch
workspace's `results.md`. Finding numbers (F5, F10, …) refer to that record.
**Scope:** failure modes of *CAD-as-code itself* — the ways a part goes wrong while
every tool in the chain reports success. partspec's own development bugs are deliberately
excluded (the tracker and `notes/` carry those); this file is what an authoring agent
needs to have seen *before* writing a part.

**Workspace ruling (#24's last acceptance box):** `docs/PLAN.md` records the dogfood
workspace's untracked status as a deliberate call, and that call **stands** — it remains
a scratch corpus of third-party code. What changes is that everything load-bearing now
lives here: this catalogue is the shipped artifact, `results.md` the frozen raw source.
Entries below are marked **[repo]** when reproducible from this repository alone and
**[corpus]** when they need the external library corpus.

Every entry answers four questions: the symptom, the root cause, how it was caught, and
— the one that matters most — **what it looks like when it's green**: the exact face a
quietly-wrong part shows you.

---

## 1. A removed language construct silently deletes geometry **[corpus]**

- **Symptom.** A gear library renders a part **35% smaller in every planar dimension**
  with its teeth missing — 48.8 mm outer extent where theory says 72.2 mm, essentially a
  gear blank at pitch diameter.
- **Root cause.** The source uses OpenSCAD's `assign()`, deprecated and later *removed*.
  Modern OpenSCAD ignores an unknown module — and ignoring a module means **its children
  never render**. The children were the `polyhedron()` calls cutting the teeth. The
  library's source is unchanged and correct; the language moved underneath it.
- **Detected by.** A contract asserting the involute-gear envelope *derived from theory*
  (`teeth × outside_circular_pitch / 180`, plus addenda), run under two pinned binaries:
  PASS on 2021.01 (honours `assign`), FAIL on 2026.08.01 (ignores it). One variable. (F13)
- **When it's green.** Both versions **exit 0 and write clean, watertight, single-solid
  STLs**. The only signal is a `WARNING: Ignoring unknown module 'assign'` buried in
  stderr. No `assert()` in the library could catch it — the corpus of 18 libraries
  contains zero asserts, and the one that had 12 (the bayonet) only guarded its inputs.
- **Guards.** `PARTSPEC_OPENSCAD` pins the binary; the version is recorded in every
  report because it changes the artifact; bounds derived from theory, not measured off
  the part (see `docs/SPEC-contract.md` §10 on reference-derived limits).

## 2. The default backend emits a broken mesh and certifies it valid **[corpus]**

- **Symptom.** A 2,212-star Gridfinity library, rendered with current OpenSCAD's
  **default** Manifold backend, produces a mesh with **4 non-manifold edges** (each
  shared by four faces — two shells touching along the z = 19.8 plane; genus 8 where the
  clean render is genus 0).
- **Root cause.** Backend-specific tessellation of coincident geometry. The same source
  under CGAL renders clean — the defect is the *render*, not the design.
- **Detected by.** A differential run varying only the backend; the face-per-edge count
  is arithmetic, not a heuristic, and `manifold3d` independently agrees. (F10)
- **When it's green.** OpenSCAD prints `Status: NoError`, `"simple": true`, **manifold**
  — and exits 0. Every one of those statements is false. This is why partspec never
  parses `--summary` (D13): the engine's self-report asserted a false validity key on a
  real part.
- **Guards.** `openscad(..., backend="CGAL")` selects the backend and
  `engine.render_backend` records it; `watertight` names boundary vs non-manifold edges;
  D17 preconditions make `volume`/`genus` refuse on the broken mesh instead of
  answering.

## 3. A hole that reaches the boundary stops being a hole **[corpus; essence [repo]]**

- **Symptom.** Lengthening a NEMA 17 plate's belt-tension slots from 6 mm to 8 mm —
  exactly the parameter someone bumps between revisions — makes the plate **unable to
  hold a motor**: the slots breach the plate edge and become open notches.
- **Root cause.** A hole is a topological property. When it opens onto the boundary the
  genus falls (5 → 1); nothing about "a slot got longer" warns that a threshold was
  crossed. Pushed further, one parameter yields five distinct states, all exiting 0:
  correct (genus 5), unmountable (genus 1), pinched to non-manifold (refused, named),
  and shattered into six solids (`solid_count` answers 6 while `genus` declines,
  per-body).
- **Detected by.** `genus 5` — the only check of five that moved. (F15)
- **When it's green.** Renders, exits 0, watertight, one solid, exactly 42 × 42 × 4 —
  four of five checks identical to the good part. **Visual review is worst here**:
  open-ended slots look like a deliberate design choice.
- **Guards.** Assert topology (`genus`, `solid_count`), not just size; the mesh tier
  answers both with no feature recognition.

## 4. A clearance allowance baked into a constant named for a nominal dimension **[repo]**

- **Symptom.** `bearings.scad` declares `od_608 = 22.5` — but a 608 bearing is Ø22.0
  (ISO 15), held to 0/−0.008 by ISO 492. Any model using `bearing(608)` *as the bearing*
  gets a phantom part 0.5 mm oversize; the bore carries its own undeclared +0.4.
- **Root cause.** A print-fit allowance for a *pocket* was written into the constant
  named for the *part*, with no comment. The width gives it away: exactly nominal — the
  allowance was applied where somebody was thinking about fit and omitted where they
  were not. The same shape recurs one library over: `NEMA17.scad`'s header says
  `42.67mm square plate` and ten lines later declares `l_NEMA17 = 42`. **Two authors,
  same slip — a property of the corpus, not a person.**
- **Detected by.** A contract carrying ISO 15's numbers with a generous ±0.1 band:
  `envelope` and `volume` both FAIL, bracketing the divergence between them. (F16; the
  in-repo reproduction is the Ø22.5-seat test in `tests/test_provenance.py`, and
  `partspec.refs.iso15` exists so the standard's numbers arrive cited instead of
  retyped.)
- **When it's green.** Nothing in the corpus checks anything, so the 22.5 mm "608" passes
  every render, forever, and every model built on it inherits the half-millimetre.
- **Guards.** Take limits from `partspec.refs` or the drawing — never from the model's
  own constants (the circular-contract disclosure, SPEC-contract §6/§10).

## 5. A parameter that binds nothing is accepted and dropped **[repo]**

- **Symptom.** Four contracts passed `style_lip=0` to a Gridfinity entry point that does
  not declare that variable (it lives in a sibling file). OpenSCAD silently discards a
  `-D` naming no top-level variable — so every run built a bin **with** the lip, while
  the report listed `style_lip: 0` under `params`, positively asserting a value the
  geometry never saw. Two of the four runs were green.
- **Root cause.** `-D` is an unchecked write into the interpreter's namespace; a typo'd
  or misrouted name reaches nothing and nobody says so.
- **Detected by.** partspec's unbound-parameter guard (#9), on its first run against the
  corpus — the first finding produced by a guard rather than a human. (F18)
- **When it's green.** Exit 0, clean mesh, and an artifact describing a part that was
  not built — the same shape as entries 1 and 2: **the tool chain is unanimous and
  wrong**.
- **Guards.** A `-D` matching no top-level variable fails the build, naming the variable
  and listing the ones that exist.

## 6. Shared claims that assert the first implementation you looked at **[corpus]**

- **Symptom.** A claims file shared by two Gridfinity implementations asserted
  `genus(0)` — "an open tray has no through-holes". True of the CadQuery
  implementation; false of the OpenSCAD one, which enables refined base holes by
  default (genus 8 on a 2×1 bin).
- **Root cause.** The claim encoded an *implementation choice* the Gridfinity standard
  does not fix. Written while looking at one implementation, it silently became a claim
  about all of them.
- **Detected by.** The differential run: one contract, two engines, a FAIL that was the
  contract's fault. (F12)
- **When it's green.** With only one implementation in the loop, the over-tight claim
  passes indefinitely — and rejects every conforming alternative the day one appears.
- **Guards.** In shared claims, assert **only what the specification fixes**. The
  standard's numbers (42n − 0.5 pitch) agreed across engines to the micrometre;
  everything else is per-implementation.

## 7. The engine ecosystem breaks at install time, silently **[repo]**

- **Symptom.** After adding OCCT extras, `import cadquery` dies:
  `ImportError: cannot import name 'IVtkOCC_Shape'`. Later, *uninstalling* the culprit
  deleted co-owned files and broke build123d too.
- **Root cause.** `cadquery-ocp` and `cadquery-ocp-novtk` both install the same
  top-level `OCP/` package (326 vs 322 files); neither pip nor uv detects the conflict;
  whichever lands last wins. A fresh-venv spike that worked was resolution-order luck.
  (F5; the successor hazard is #109 — `cadquery-ocp-proxy` under `uv pip` installs no
  OCP at all.)
- **When it's green.** The install exits 0. The breakage surfaces only at first import,
  possibly days later, and looks like the *library's* bug.
- **Guards.** `[tool.uv] override-dependencies` drops novtk from resolution;
  `just ocp-guard` asserts exactly one provider; `_engine_import_error` names the
  two-provider state instead of relaying the raw ImportError.

## 8. Community CAD code is scripts and pinned libraries, not callables **[corpus]**

- **Symptom.** A 96-star community build123d library fails to import on build123d
  0.11.1 (`ShapePredicate` no longer exists); the flagship library's 66 examples are
  module-level scripts ending in `show(...)`, not parameterised functions. Most OpenSCAD
  is the same.
- **Root cause.** Community models are written against the engine version of their
  moment and for interactive use. Nothing about the ecosystem pushes toward
  `factory(**params) -> shape`.
- **Detected by.** Attempting to drive the corpus through `method(**params)`. (F8)
- **When it's green.** It isn't subtle — but the *cost* is: every real contract on
  community code ships a three-line adapter, and an agent that doesn't know this
  pattern will rewrite the model instead.
- **Guards.** partspec deliberately does not guess calling conventions; the adapter
  pattern is the documented friction (`SPEC-backend.md` §4).

---

## The shared moral

Five of these eight (1, 2, 3, 5, and the header half of 4) have the same signature:
**exit 0, a clean watertight mesh, and an artifact that is not the part you asked for.**
Nothing in the render pipeline is positioned to notice, because every stage's contract
with the next is "produce *a* mesh", not "produce *the* mesh". The checks that caught
them — envelope from theory, topology, external standards, unbound-parameter refusal —
are all statements about **intent the model does not contain**, which is the reason this
tool exists and the reason a contract derived from the model's own numbers proves
nothing (§4).

*Cross-references from the authoring skills (#22, #23) land with those skills; each
entry above carries a stable heading for them to anchor to.*
