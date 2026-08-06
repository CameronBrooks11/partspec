# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/CameronBrooks11/partspec/compare/main...HEAD
