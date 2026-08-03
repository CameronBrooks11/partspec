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

### Changed

- `geometry.facets` is now `geometry.distinct_normals` (D16), named for what it measures
  rather than borrowing CGAL's vocabulary for a different quantity.
- `GeometryBackend.provenance()` takes the artifact rather than reading instance state.
- `just setup` includes the mesh extra; `just setup-all` adds the OCCT engines.

### Notes

- No subcommands yet. They are absent rather than stubbed on purpose: a verb that pretends
  to check something is the failure this tool exists to prevent.
- The `approximate` machinery ships dormant. As v0 is scoped no check can produce it, so it
  is covered by direct unit tests rather than by use — see `docs/SPEC-report.md` §10.

[Unreleased]: https://github.com/CameronBrooks11/partspec/compare/main...HEAD
