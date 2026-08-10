# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `p.min_wall(min=)` — every wall thick enough within a declared measurand,
  OCCT tier (#140): kernel-exact face-pair minima and certified diametric
  self-spans bound the wall from below; a witnessed crossing bounds it from
  above — an inward normal ray, or a diametric chord certified material end
  to end by exact boolean, which is what makes every closed analytic family
  exact and answers a frustum whose every normal exits through an adjacent
  cap (#145). One consequence to know: a fillet band is a closed analytic
  face, so the documented fillet-flip now FAILS conclusively where it used
  to straddle. A crossing thinner than the bound refuses the check as
  self-contradictory, and a straddling limit adjudicates `approximate` —
  the first genuine exercise of the interval machinery, closing POST-V0's
  outstanding obligation. Gap-limited claims straddle honestly (never
  falsely tight); edge-sharing webs, single-face folds and step/counterbore
  ledges are recorded escapes with fixtures, not silent green; the wedge
  policy is structural. The mesh
  tier's refusal stands with the research's executed evidence recorded.
  SPEC-contract 4.11.
- `p.step_roundtrip(tol=)` — the part survives its own exchange format,
  OCCT tier (#139): written to STEP and read back, volume/area within a
  calibrated relative tolerance (default 1e-6: most families measure below
  4e-13, threaded parts ~1.9e-8, the executed degrader loses everything)
  and topology counts unchanged at any tolerance. Plain membership — the
  tol is never epsilon-widened. The writer schema rides on the check
  (`checks[].step.schema`). SPEC-contract 4.10.
- `p.self_intersection_free()` — the shape does not cross itself, OCCT tier
  (#138): the kernel's own pairwise interference analysis, exact, with the
  faults inventoried in the failure detail. The recorded limit is pinned
  by tests in both directions: an analytic single-surface self-intersection
  (spindle torus) escapes, while a self-overlapping swept face is caught as
  a pair-less fault. Listed by `measure`. SPEC-contract 4.9.
- `p.draft_angle(min=, direction=)` — every face's draft at least `min`
  for a declared pull axis, OCCT tier (#137). Deliberately no `max=`: an
  every-face maximum is unsatisfiable under the two-half convention (caps
  measure 90), and a bound held to fewer faces would pass silently. Exact on planes, cylinders and
  cones at any orientation (closed-form wrap extremes, no sampling); a
  freeform face refuses the whole check with the face named, never a subset
  pass. The two-half parting convention makes tops measure 90 and pass a min
  naturally, and the pull axis is recorded in the check
  (`checks[].direction`). SPEC-contract 4.8.

## [0.6.0] - 2026-08-08

An agent can see the part it made (epic #2): renders on every engine, section
cuts, a visual diff — plus the lint tier that reads the geometry.

### Added

- `render` and `check --render` accept build123d and CadQuery parts (#18): the
  part builds through the same backend `check` uses and the canonical views are
  rasterized from its tessellation — deterministic (identical geometry renders
  byte-identical), headless, no new dependency. Framing is the OpenSCAD path's,
  measured and verified cross-tier to the pixel. OCCT payloads and reports carry
  `render_tessellation` (`{tolerance_mm, triangles}`) beside `renders` (D15).
- `render` payloads carry the report's identity prefix, and a render failure is
  a JSON artifact with `error`/`hint` at exit 4 instead of a bare stderr line
  (#103); the MCP `render` tool returns the whole payload as `rendered`.
- `partspec vdiff old new` compares two runs' renders visually (#21):
  per-view changed-pixel fractions with grey-plus-magenta diff images, a
  reproducible scalar magnitude, and refusals for everything that would let
  noise read as change — differing image sizes (never rescaled), engine
  versions (7.68% renderer noise), part ids or view sets. Pure scale is
  pixel-invisible by construction, so every render now records its framing
  bbox (`render_bbox`) and the render verb leaves `render.json` on disk;
  a bbox delta with identical pixels reads as change, referred to `measure`.
  Exposed over MCP as `vdiff`.
- `render --section xy|xz|yz[:offset]` cuts through a named plane and renders
  the cut with exposed material in a distinct colour, on both tiers (#19):
  OpenSCAD subtracts a half-space from its exported STL (kernel-capped), the
  OCCT tier booleans the shape, and the shared rasterizer draws both. The
  payload records the resolved plane, offset and cut-facet count; a plane
  that misses the part is refused with its span.
- `partspec lint` tier 2 — the geometry rules, over OpenSCAD's constant-folded
  `.csg` export via a hand-rolled stdlib reader (`csg.py`; sca2d is GPLv3 and
  geometry-blind, FreeCAD's importer LGPL and welded to its document model):
  `csg-coincident-face` (exact plane coincidence of cutter and minuend — zero
  epsilon, the literals are folded) and `csg-difference-order` (analytic
  upper-bound volumes, convention stated in the finding). Requires the engine;
  a missing engine, failed export, unmodelled node (`hull()` and kin on a
  rule's evaluation path) or string-carrying export produces per-rule
  `unsupported` entries — a rule that could not run is an entry, never an
  absence. Tier-2 findings carry line 0: the folded tree has no source lines
  (#118, #125).

### Changed

- Lint payload schema 2: per-file `{file, digest, findings[, unsupported]}`
  blocks — a clean file is a visible entry with the sha256 of the linted
  bytes, and duplicate arguments are deduped. A breaking reshape of the
  schema-1 payload that shipped in 0.5.0, versioned honestly (#120, #124).

### Fixed

- Module eviction covers every CLI exit path: contract-sibling imports are
  recorded and evicted on failed resolves and on the error paths of `check`,
  `measure` and `render` (record-in-finally), closing the remaining
  cross-directory stale-module windows (#114, #124).
- A stranded `cadquery-ocp-proxy` (proxy installed, no OCP — the observed
  `uv pip` outcome at the time) is named as the environment state with a
  plain-pip hint, instead of the circular "pip install partspec[occt]"
  (#109, #124).

## [0.5.0] - 2026-08-08

The repo teaches the craft it verifies (epic #3): skills, exemplars, the failure
catalogue, a source linter, and a recorded before/after on agent output.

### Added

- **`partspec lint`** — tier-1 advisory source lint over `.scad`/`.py` models, in the
  wheel and engine-free: five rules with exact predicates (`docs/LINT.md`), findings
  as data at exit 0 — advisory and never a verdict on the part — with 64 reserved for
  unlintable input. The `-1`/`+2` overshoot idiom is exempt by design; tier 2
  (geometry-dependent rules over the `.csg` tree) is deferred to #118 behind its
  prior-art survey (#119).
- **Three authoring skills** (repo content, not wheel content): `contract-authoring`
  (the decision table, the limit-provenance ladder, the retrofit path),
  `openscad-authoring`, and `build123d-authoring` — every executable claim in them is
  executed by the test suite, and several were corrected by exactly that discipline
  before shipping (#115, #116, #117).
- **Three worked exemplars** under `examples/`: a NEMA 17 bracket whose interface is
  one cited `nema17.mount` call, a bearing-seat family in OpenSCAD **and** build123d
  with shared claims stated once and the ISO 15 designations cited, and a
  sealed-cavity enclosure whose sealedness claim is `cavities(1)` — because an open
  tray is also watertight, one solid, genus 0 (#112).
- **`docs/FAILURE-MODES.md`** — the eight observed CAD-as-code failure modes from the
  dogfood corpus, each with symptom, root cause, detection, and what it looks like
  when green; raw record frozen at `notes/dogfood-results.md` (#111).
- **The authoring before/after, recorded** (`evals/AUTHORING.md`): guidance-present vs
  absent arms over exemplar-shaped tasks, 12 trials. Pass rate saturated (6/6 both
  arms); on the transfer tasks the guidance moved source quality from mixed to
  uniformly lint-clean (6 → 0 findings) while LoC rose — the added lines are the
  parameterisation. One task's treatment output was a line-for-line copy of a skill's
  own worked block; it is scored separately as retrieval and kept as the
  contamination exhibit (#121).
- **`notes/`** — the analysis the tracker cites (gap inventory, W1–W10 findings, the
  audit synthesis, as-filed tracker scripts) is tracked and visible to clones, with
  per-item dispositions recorded (#110).

### Fixed

- **`measure` reports `cavities`** — the number distinguishing a sealed enclosure
  from an open tray was absent from the verb whose job is showing every claimable
  number (#113, landed with #115).
- **A contract's sibling imports no longer cross directories** — a shared `claims.py`
  cached from directory A silently supplied directory B's checks in one process; the
  module-cache registry now covers resolve-time additions for every engine (#112).

## [0.4.0] - 2026-08-08

The loop can be trusted unattended (epic #4's remnant): a run that cannot hang, a
contract that cannot shrink silently, and the rules an agent follows written down.

### Added

- **Bounded builds.** `--timeout SECONDS` on `check`, `measure` and `render`
  (default 300 s, then `PARTSPEC_TIMEOUT`; `0` explicitly waives), recorded in
  `invocation.timeout_s`. A blown budget is `error` exit 4 with
  `build_origin: "environment"` naming the elapsed time and the budget — never a
  failing `builds` check: a stopwatch disproves nothing about the part. The Python
  tier gets a real SIGALRM bound that records it fired — a model whose mundane
  `except Exception` swallows the alarm still has its over-budget result discarded —
  and re-fires past `except Exception`; the residual ceilings (C-kernel hangs,
  signal-owning models, leaked threads) are stated in `SPEC-backend.md`, not hidden
  (#100).
- **Multi-target `check`.** One process, one report per part at its deterministic
  path, exit by highest-precedence verdict (`error > empty > fail > incomplete >
  pass`, SPEC-report §6.2); an unresolvable target exits 64 with the remaining
  targets still evaluated; placeholders for every target go down before any runs;
  colliding slugs under one `--out` are refused rather than silently overwritten.
  The `sys.modules` model cache is invalidated after every Python-engine build —
  a second contract importing an edited helper used to get the previous version, a
  stale build reported as fresh (POST-V0 §8) (#104).
- **The claims pin.** `check --pin LOCK` writes the declared claim set;
  `check --expect LOCK` fails before the engine starts unless the set matches
  exactly — removed, added, and changed claims named with both slugs, stripped
  `source` citations included, verdict `error` exit 4 with every check skipped and
  the adjudication in the artifact as `expectation`. A pinned part no target
  produced fails too. This closes silent contract weakening with **no baseline in
  hand**; `diff` remains the comparison half (#105).
- **`measure` is as identifiable as a report.** Its payload opens with the report's
  exact identity prefix (`schema_version`, `tool`, `part` with digests and closure,
  `engine`, `params`, `geometry`), built by the same code, and any failure after
  the target resolves emits that identity plus `error`/`hint` as JSON on stdout
  (#102).
- **`docs/AGENT-CONTRACT.md`** — the agent contract: a bounded 5-attempt repair
  loop with failure fed forward, an action map keyed on (exit, verdict, report
  fields), the greppable `HUMAN_REVIEW:` escalation format with its parse rule,
  and the out-of-bounds section naming the guards that watch every weakening move.
  A drift-guard test file holds the document's executable claims to the code (#106).

### Fixed

- **A missing third-party package at model import read as a disproven design.**
  Found live: a `uv sync` dropped a wheel and the batch reported the part as
  failing. Now `origin: "environment"`, exit 4, package named in the hint; a
  broken local import chain stays the part's fault (#101).
- **Stale bytecode could answer for an edited file.** CPython validates a `.pyc`
  by (mtime seconds, size), so a same-length edit within one second re-executed
  the OLD contract under the NEW `contract_digest` — precisely an agent's rapid
  edit-loop shape, and precisely what would blind the claims pin. Contract and
  model entry files now compile from source, never from the bytecode cache (#105).

## [0.3.0] - 2026-08-08

Reference data with provenance — limits that know where their numbers came from (epic #5).

### Added

- **`partspec.refs`** — reference tables shipped in the wheel, importable with no engine
  installed: ISO 15 deep-groove bearing boundary dimensions (`iso15`, 22 designations) and
  the NEMA 17 mounting interface (`nema17`, exact conversions of the standard's own inch
  figures, with the inch figure in every note) (#95, #96).
- **`Referenced` values.** A bound taken from a reference table carries its citation into
  the report as `checks[].source` (`{standard, subject, field}`). Arithmetic sheds the
  attribution — a derived number is the author's, and a fragment must never launder the
  designer's numbers into a standard's (#95).
- **Contract fragments.** `nema17.mount(p)` and `iso15.seat(p, 608)` declare an interface
  standard's checks in one call, with namespaced ids (`nema17:pilot`,
  `nema17:left:bolt_circle`) and atomic failure — an invalid argument lands no checks. The
  bolt pattern carries the standard's citation; the clearance diameters are the designer's
  arguments and deliberately carry none (#96).
- **The report says when it proved nothing external.** A run-level
  `attribution: {dimensional, attributed}` block, and a CLI warning when every dimensional
  limit is unattributed — bounds derived from the model's own numbers prove only that the
  model matches itself (#97). The signal lives in the artifact, not just on stderr, because
  the MCP tools run `--quiet`.

### Changed

- `partspec diff` treats a check's `source` as part of the claim: stripping a citation
  reports as `limit_changed`, so quietly de-attributing a limit is visible on comparison
  (#95).

### Fixed

- The first version of the NEMA 17 table cited the catalogue's 31 mm hole square to the
  standard and derived the pitch circle from it — exactly backwards: NEMA ICS 16 states the
  pitch circle (1.725 in) directly. Caught in review against the standard's own text before
  release; the corrected derivation is recorded in `SPEC-contract.md` §11 as the cautionary
  example (#96).

## [0.2.0] - 2026-08-08

A part proven against mechanical intent (epic #6): the check vocabulary reaches drawing
callouts, and reports become comparable.

### Added

- **`keep_out` / `keep_in`** — spatial claims over declared regions, each with a mandatory
  weak-form verification shell so a region check can never pass vacuously; the region
  materializes tier-identically as a circumscribed prism (#85, `SPEC-contract.md` §4.4).
- **`checks[].components`** — a vector check names the failing axis: per-axis statuses whose
  worst is exactly the check's own, one adjudication rendered two ways (#86).
- **`hole_diameter`** — the first drawing dimension: count claims over detected bores, OCCT
  tier only; the mesh tier refuses rather than approximating a cylinder from triangles
  (#87, §4.5).
- **`partspec diff`** — two reports compared semantically (`SPEC-diff.md`): `removed` /
  `added` / `regressed` / `fixed` / `drifted` / `limit_changed`, exit 0 identical / 1
  different / 2 indeterminate / 64 usage. A partial or missing source closure blocks only
  the `identical` claim, and every indeterminate entry carries a machine-readable code.
  This closes the silent-contract-weakening gap on comparison (#88).
- **`bolt_circle`** — the mounting-interface callout as one check: the pattern circle is
  least-squares fitted, adjudication is strict against the fitted centre, and `tol > d` is
  refused at declaration (#89, §4.6).
- **`fillet_radius`** — every cylindrical blend within bounds; a part with no detected
  blends FAILS rather than passing vacuously, and the message names the detection gap
  (toroidal/spherical blends) rather than claiming none exist (#90, §4.7).

### Changed

- Usage errors exit 64 CLI-wide — argparse's exit 2 is remapped, because 2 belongs to
  `incomplete` (#88).

## [0.1.0] - 2026-08-07

### Added

- The report/status seam (P0), specified before implementation because it — not the CLI
  verbs — is the product contract.
  - `status.py`: five check statuses, verdict precedence, exit-code mapping, and interval
    adjudication. A relative comparison epsilon, `1e-6 + 1e-7·|limit|`, because binary STL
    stores float32 and a flat `1e-6` fails a geometrically perfect part above ~16.8 mm.
  - `report.py`: the JSON artifact, fixed field order, atomic writes, and an `error`
    placeholder written *before* the engine runs, since a `try/finally` cannot survive an
    OCP segfault.
  - `backend.py`: the `GeometryBackend` protocol and value types. `Unsupported` is a return
    value rather than an exception.
- Specs and decision log under `docs/`, promoted from the design survey.
- A conformance test asserting the schema example in `docs/SPEC-report.md` satisfies its own
  stated rules — that example is the contract, so it should be executable.
- `just ocp-guard`, asserting exactly one OCP provider is installed. `cadquery-ocp` and
  `cadquery-ocp-novtk` both own the top-level `OCP/` package and pip does not detect the
  conflict.

- **P1 — the mesh backend.** OpenSCAD → binary STL → trimesh/manifold3d, never
  `--summary` (D13). Implements bbox, volume, area, centre of mass, watertightness, solid
  count, genus, min distance, intersect volume and raycast; refuses topology counts.
  - Verified against closed-form geometry rather than against its own output: a 30x20x10
    block with a 6x6 square through-hole checks out on volume, area, bbox, genus and centre
    of mass, and a `$fn=16` cylinder matches the **16-gon prism** volume, not `pi*r^2*h` —
    which is D15 in one assertion.
  - `solid_count` via `manifold3d.decompose()` and `distinct_normals` by face-normal
    counting, both because trimesh's equivalents need `scipy`/`networkx` (D16).
  - `genus` is refused for multi-body parts: manifold3d reports the genus of the whole
    complex (two disjoint boxes give -1), which answers a question nobody asked.

- **P2 — the contract API.** `Part` with the closed v0 check vocabulary, engine-declaring
  source constructors, target resolution (`<module>[:<factory>]`, where the error message
  lists the available factories rather than saying "ambiguous"), and a `requires` evaluator
  that records the operands it read.
  - Phase ordering with short-circuiting: a failing parameter check stops the engine from
    running, and the geometry checks are reported `skipped` naming the blocker rather than
    quietly omitted.
  - `check` and `measure` subcommands. `measure` emits nothing that would be unsupported
    and produces no verdict — it is the adoption path, and partspec deliberately will not
    auto-generate checks from it.
  - A worked example under `examples/spacer/`.

### Fixed

- **A contract declaring no checks exited 0.** The implicit `builds` check satisfied the
  emptiness test, so the tool defeated its own vacuous-green guard. `Report.verdict` now
  excludes implicit kinds; a contract that asserts nothing is `EMPTY` with exit 3, as
  `SPEC-contract.md` §6 had already specified.
- **Relative source paths resolved against the CWD**, so a contract worked or failed
  depending on the shell's history. They now anchor to the contract file's directory.
- **`operands_of` returned names in `ast.walk` order**, which is breadth-first: `z + a*z + m`
  came back as `(z, m, a)`. Now sorted by source position, since the order reaches a report
  that gets diffed.

- **P4 — the OCCT backend.** One implementation serving build123d *and* CadQuery, with
  adoption at the front door (`adopted_via: "wrapped"` records it). Answers
  `topology_counts`, which the mesh tier refuses — that asymmetry is the point of tiers.
  - `genus` via the Euler-Poincare form `G = S - (V - E + 2F - W)/2`. The naive
    `V - E + F` is wrong on a BREP and quietly so: OCCT faces carry inner wires, so it
    reports a through-hole as genus 0 and a *blind* hole as genus -1. Verified on a box,
    one and two through-holes, a blind hole, a tube, and a real pillow block (genus 5).
  - `engines/pycad.py` builds from either Python engine. Adoption dispatches on
    `ShapeType()`, because `build123d.Shape.cast` returns `None` in 0.11.1 and
    `Compound(topods_solid)` constructs happily while reporting volume 0.
  - Models are called as `method(**params)` — no signature inspection, no guessing. A
    differently-shaped model gets an explicit adapter in the contract.

### Fixed

- **`is_valid` was called as a method** on the OCCT backend, raising
  `TypeError: 'bool' object is not callable`. build123d exposes it as a property —
  the exact divergence `SPEC-backend.md` §4 documents as the reason the adopt shim exists.
- **CadQuery could not import at all** after adding the OCCT extras.
  `cadquery-ocp` and `cadquery-ocp-novtk` both install a top-level `OCP/` package (326 vs
  322 files) with no conflict detection, and novtk landed last, stripping the VTK modules.
  Fixed with a `[tool.uv] override-dependencies` marker that drops novtk from resolution.

- **P5 — the differential test.** One contract, the same specified part in OpenSCAD and
  CadQuery, reports compared field-by-field. No tool feature was needed: the contract is
  Python, so sharing claims across implementations is a function.
- **`openscad(..., backend=...)`** selects the render backend, recorded as
  `engine.render_backend`. It changes the *artifact*, not just the speed — measured, the
  default Manifold backend produced 4 non-manifold edges on a community gridfinity bin
  where CGAL produced a clean mesh from identical source.
- **`watertight` now says why it failed** — boundary edges (a hole) versus non-manifold
  edges (surfaces touching). trimesh's `is_watertight` conflates them, and they have
  different causes and different fixes.

- **`part.source_closure`** — a digest over *every* file an OpenSCAD render reads, not just
  the entry point. `source_digest` covers one file, and on real libraries that is a small
  fraction of the build: the gridfinity bin in the dogfood corpus is one file of sixteen, so
  editing a helper three levels down changes the part while the entry hash does not. That is
  F13's failure class arriving in the provenance layer, and `diff` would have inherited it.
  - Digested over sorted **content** hashes rather than paths, so a CI run and a laptop run
    of the same tree agree.
  - Reports what it could not cover: `unresolved` includes, and `reads_external_data` when
    `import()`/`surface()` name files whose paths may be computed at render time. Either
    sets `partial`, stated positively so absence cannot be read as a guarantee.
  - Python engines emit none — a claim withheld rather than one made. **(Historical note, corrected 2026-08-09: this was already untrue at the tag. The Python closure shipped in `83f1119`, inside v0.1.0, emitting `scope: "model_directory", partial: true`; SPEC-report §8.3 records the reversal two days before the tag and this entry was written from the superseded plan.)**. `environment.packages`
    already covers installed deps; local helper modules beside a model are a recorded gap.

- **`p.topology(faces=, edges=, vertices=)`** — modelled face/edge/vertex counts, and the
  first v0 check that a tier cannot answer. On build123d or CadQuery it compares real
  topology; on OpenSCAD it reports `unsupported` with `requires: "occt"`, because a triangle
  mesh has no modelled faces and returning a triangle count is the PartCAD failure. That
  path was previously unreachable from any contract — every other kind resolved to a
  primitive both backends declare — so `requires` had never appeared in a real report.
  Any subset of the three may be constrained; `p.topology()` with none is a `ContractError`.

- **`PARTSPEC_OPENSCAD`** pins the OpenSCAD binary. The engine version changes the
  artifact: 2021.01 honours the removed `assign()` construct and 2026.08.01 ignores it, so
  a gear library's teeth silently vanish and the part comes out 35% smaller in every planar
  dimension — both versions exiting 0 with clean watertight meshes. An environment variable
  rather than a contract field, because which binary is installed is a property of the
  machine, not of the design.

### Changed

- `geometry.facets` is now `geometry.distinct_normals` (D16), named for what it measures
  rather than borrowing CGAL's vocabulary for a different quantity.
- `GeometryBackend.provenance()` takes the artifact rather than reading instance state.
- `just setup` installs **all** extras, matching CI exactly; `just setup-mesh` is the
  lighter OpenSCAD-only path and is explicitly not what the gate runs.
- `measure` now also reports `is_valid` and, on the OCCT tier, `topology_counts` — a
  deliberate superset of the check vocabulary. `is_valid` is not a check kind because it
  means different things per tier (an open shell is valid on OCCT, invalid on mesh), and a
  kind whose meaning moves with the backend breaks the one-contract property.
- A vector limit may now leave components unconstrained — `equals=(6, None, None)` claims a
  face count and nothing else. Those axes are skipped rather than adjudicated; previously
  they raised, because a per-component `Limit` of three `None`s trips its own validation.
  A limit that constrains *no* component is a `ContractError`, since folding zero components
  would return `pass`.
- `volume`, `center_of_mass`, `solid_count` and `genus` may now return `Unsupported`. The
  protocol signatures widened to match; `bbox`, `area` and `watertight` stay total.

### Fixed

- **The mesh tier answered questions it could not answer** (dogfood F14) — the second of
  the three failure modes `docs/SPEC-report.md` §1.1 names, in the tool built to prevent
  it. A contract declaring `volume`, `solid_count` and `genus` but not `watertight` scored
  four green checks and exit 0 on a community gridfinity bin that partspec itself knew
  carried 4 non-manifold edges. Reduced: a cube missing one face reported `volume 500.0`
  (against 1000.0 closed), `genus 1` and a centre of mass outside the material — all
  flagged `exact`.

  Each quantity now declares its precondition (`docs/SPEC-backend.md` §5.1.1) and refuses
  with the defect named rather than returning a number. Deliberately narrow: `solid_count`
  is refused only for non-manifold edges, since an *open* mesh still determines its own
  component count and over-refusal is its own way of not answering.

- **A dependency's error status was discarded.** Handed an open mesh, manifold3d returns an
  object reporting `Error.NotManifold`, `is_empty()` and zero triangles — on which
  `.decompose()` still returns a one-element list and `.genus()` still returns 1. Both were
  read without checking `status()`. Now checked.

- **Two libraries were measuring two different solids into one report.** `volume` came from
  trimesh and `genus`/`solid_count` from manifold3d, which rebuilds its input: on the clean
  CGAL gridfinity render — same 5,330 vertices, none displaced — it retriangulated 55 of
  10,688 triangles and moved the enclosed volume by 25.31 mm³ (0.078 %). An independent
  divergence-theorem sum agrees with trimesh, not manifold3d. Body count and genus are now
  computed over the exported triangles, which is what D15 requires. Verified equivalent to
  manifold3d on sound meshes.

- **`same-source` OCCT gap closed too:** `volume` and `center_of_mass` refuse for a shape
  bounding no solid. An open shell reports `volume 0.0` with `is_valid` True, so
  `volume(max=…)` would have passed on a shape containing no material.

### Notes

- The `approximate` machinery ships dormant. As v0 is scoped no check can produce it, so it
  is covered by direct unit tests rather than by use — see `docs/SPEC-report.md` §10.
- `just test-mesh-only` runs the mesh tests against a throwaway `partspec[mesh]` install.
  Because `just setup` takes all extras and scipy arrives only via build123d/cadquery, a
  mesh-tier dependency on scipy would otherwise pass both locally and in CI while breaking
  every mesh-only user.

- `PARTSPEC_REQUIRE_ENGINES` turns a missing engine from a skipped test into a hard failure.
  CI reported 195 passed / 23 skipped because no runner had an OpenSCAD binary, and the 23
  were the entire end-to-end path. The gate was green because the tests were absent.
- CI runs the mesh tier across **two OpenSCAD versions** — apt 2021.01 and a pinned
  2026.08.01 snapshot — because F13 found the same source builds a different part on each,
  and one version leaves that an anecdote. A step asserts each leg got the engine it
  declares, so an apt bump cannot collapse the matrix while still reporting two green checks.
  `just test-mesh-only` becomes a CI job; it guards a failure mode defined as "passes
  locally and in CI" and had been running only locally.
- `tests/test_cli.py` — the verbs had no tests at all, on a design whose D5 makes the exit
  code half the product contract. Every verdict now round-trips through `main` on a real
  render.

### Fixed

- **`measure` went silent exactly where it became most useful.** It dropped every
  `Unsupported` result, which was honest while a refusal only meant "this tier cannot answer
  this quantity". Since D17 it also means "this part is broken, and here is the defect", and
  the two arrived identically: absent. On a cube missing one face, `measure` printed area,
  bbox and solid_count with no volume, centre of mass or genus — in the verb that exists so
  somebody can see the numbers before deciding which are intent. `refused` now carries the
  reason per quantity and `unavailable` lists tier gaps separately.
- **A contract that raises exited 1** — this tool's code for *the part failed its contract*.
  A mistyped keyword argument raised `TypeError` out of `resolve()` and the traceback escaped
  `main`, so a malformed question was reported as a wrong answer about the design. Now exit
  4, for the same reason a `ContractError` during a run is.
- **The engine was resolved from a hardcoded path in `$HOME`.** `find_executable` preferred
  `~/Applications/openscad/OpenSCAD-nightly.AppImage` ahead of `PATH`, so `which openscad`
  said 2021.01 while every render used 2026.08.01 — on a tool whose own F13 says the version
  changes the part. The dogfood write-up claimed the wrong engine for two days as a result;
  the reports never did. The rule is now the pin, then `PATH`.
- **OpenSCAD's own diagnosis was discarded** unless it contained `ERROR` or `WARNING`, so
  `unrecognised option '--backend=CGAL'` — what 2021.01 says to a contract written against a
  newer engine — became `openscad exited 1` with no hint.
- **A mistyped `PARTSPEC_OPENSCAD` raised `FileNotFoundError` out of `run()`**, escaping the
  report machinery entirely: no artifact, no verdict, no exit code. Now a `BuildError`.
- **The Python tier recorded one file as the whole build input.** `engines/pycad.py` puts the
  model's directory on `sys.path` so a model can import helpers beside it, which makes those
  helpers build inputs by design — and editing one changed the part while `source_digest`
  stayed identical. `part.source_closure` now covers them, read from `sys.modules` after the
  build, with `partial` unconditional. `SPEC-report.md` §8.3 previously specified emitting
  nothing here; the reversal and its reasoning are recorded in place.

### Added

- **P6 — the product surface for agents.** `partspec-mcp`, an MCP server exposing `check`,
  `measure` and `render` as stateless tools — every call a fresh subprocess returning the
  same artifact the CLI writes, per the D18 boundary (#63, #66). `partspec render` emits
  canonical multi-view PNGs on the mesh tier, and the report references the renders it
  produced (#64, #65).
- **The convergence eval, run and recorded** (`evals/CONVERGENCE.md`): 15/15 trials across
  five defect classes, an agent taking a broken part to green with exactly one edit each and
  zero contract-weakening attempts (#67).
- Tagged releases publish to PyPI via trusted publishing: tag/version assertion, build,
  `twine check`, cold-wheel smoke test, then OIDC upload (#60).

### Fixed

- The two pre-tag adversarial audits (#56, #57) and the eight-defect close: measurements
  that lied, failures that blamed the part instead of the machine, and one rename the audit
  itself got backwards.
- Release-window fixes (#70–#77): a failed build's hint is the diagnosis rather than a
  cache statistic; comparison operators slug to distinct check ids; the report records the
  invoked callable and how parameters applied; `engine.render_backend` is always present;
  `measure` and `render` carry the same engine provenance as `check`; the OpenSCAD method
  scratch moved out of the source tree.

[Unreleased]: https://github.com/CameronBrooks11/partspec/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/CameronBrooks11/partspec/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/CameronBrooks11/partspec/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/CameronBrooks11/partspec/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/CameronBrooks11/partspec/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CameronBrooks11/partspec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CameronBrooks11/partspec/releases/tag/v0.1.0
