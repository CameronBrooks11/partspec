<!-- Vendored 2026-08-09 from the survey workspace (working-b123d-agentic),
     unmodified below this header. Cited under **Backing:** by the specs in
     docs/, which pointed at a path no reader of this repository could open —
     the loss class notes/README.md exists to prevent. -->

# Direction — second pass

**Date:** 2026-08-02
**Supersedes:** the "Recommendation" section of `SYNTHESIS.md` (first pass).
**Backing:** `investigations/00`–`03`. Everything marked **verified** was executed locally
today, not inferred.

---

## 0. What changed since the first pass

Cameron's calls: engine-neutral across OpenSCAD / CadQuery / build123d from the start;
absorb cad-khana rather than adopt PartCAD; CLI first with MCP layered on; willing to split
into separate repos if forcing them together is bad.

Three findings then reshaped the design, two of them from spikes run locally:

1. **CadQuery is nearly free — verified.** build123d 0.11.1 and CadQuery 2.8.0 install into
   one venv on a shared `cadquery_ocp` 7.9.3. Both `.wrapped` are `TopoDS_Shape` from the
   *same* OCP module, and `bd.Solid(cq_shape.wrapped)` adopts across with zero loss —
   volume, validity, faces, `distance_to`, boolean intersection and bbox all exact.
2. **cad-khana's build123d coupling is pervasive by type but shallow by behaviour.** Twelve
   geometry primitives carry its entire diagnostic vocabulary; ~2,000 LOC of the valuable
   logic is already engine-independent.
3. **The mesh tier works, with a sharp boundary — verified.** On `bayonet-lock-scad` at
   three facet resolutions, bounding box is **exact and resolution-independent**
   (`[15.8, 15.8, 8.0]`, directly encoding `interface_radius`, `allowance`, `part_height`)
   while volume drifts **0.5 %** between `$fn=32` and `$fn=128`.


> ⚠️ **Corrected 2026-08-03, while implementing the mesh backend.** "Resolution-independent"
> is **overstated**. The bbox is *exact* — the polyhedron is measured exactly, per D15 — but
> it is **not invariant to facet settings**. The original spike happened to use explicit
> `$fn` values (32/64/128), and OpenSCAD places a vertex on the +X axis for an explicit
> `$fn`, so the bbox landed on `2r` every time. With the **default** `$fa`/`$fs` (no `$fn`
> at all) the vertex phase differs and the same cylinder measures **15.7377**, not 15.8.
>
> Measured: `cylinder(h=10, r=7.9)` gives bbox_x = 15.800000 at `$fn` ∈ {8,12,16,32,64,128},
> and **15.737706** with no `$fn`. The invariance was an artifact of the test inputs.
>
> This is D15 behaving correctly rather than a defect — with default facets the part
> genuinely *is* 15.74 wide, and that is what a caliper would read. But a contract author
> writing `envelope(max=15.8)` against a curved OpenSCAD part needs to know the number moves
> with `$fn`, so the claim must not be repeated as invariance.

**Net effect: engine-neutrality is much cheaper than it sounded, and the fault line is not
where it appeared to be.**

---

## 1. The answer on "separate repos"

**One repo. Two backends, not three.**

> One **OCCT backend** serves *both* build123d and CadQuery via a `.wrapped` adopt shim at
> the front door. The only genuinely separate backend is **mesh**, for OpenSCAD.

The split you offered isn't needed, because the thing that would have justified it — two
parallel implementations of the same vocabulary — doesn't exist. CadQuery is an adopt
function, not a code path. And the mesh backend shares the *protocol*, not the code, so it
adds a module rather than a fork.

Keeping it in one repo also preserves the property that makes the whole thing worth
building: **one contract, evaluated identically wherever it can be, with honest degradation
where it can't.** Two repos would make that a coordination problem instead of a type
signature.

Your own rule applies — defer the split until a second consumer or a real driver lands.
Design the protocol as the seam so splitting later stays cheap.

---

## 2. On CLI-then-MCP — agreed, with the caveat that decides the design

You're right, it matches `dev-toolbox` core belief #3, and cad-khana's author reached the
same conclusion independently (`CLAUDE.md` carries `# mcp.py # future: MCP server over the
same primitives`, with library modules deliberately free of CLI/MCP deps).

The caveat is *where the seam actually sits*:

> The MCP layer is thin only if the CLI's **output** is machine-readable from day one. The
> real contract is the **report schema plus the exit code**, not the verbs.

Get that right and MCP is ~100 lines, and `diff`, CI annotations and a scorecard all fall
out of the same artifact. Get it wrong — human prose on stdout — and the MCP layer becomes
a parser and you've built it twice.

One second-order note: importing OCP costs seconds per process. Don't solve it with a
daemon (premature); solve it by **batching** — one `check` evaluates the whole contract and
emits one report. Better UX regardless.

---

## 3. Architecture

```
contract (Python)  →  engine adapter  →  GeometryBackend  →  checks  →  report.json + exit code
                         │                    ├── OcctBackend   (build123d, cadquery)
                         │                    └── MeshBackend   (openscad)
                         └── build123d | cadquery | openscad(-D params) → artifact
```

**The `GeometryBackend` protocol** — the twelve primitives, normalized:

```
intersect_volume(a, b) -> float      min_distance(a, b) -> float
bbox(a) -> BBox                      mass_properties(a) -> (volume, area, com)
topology_counts(a) -> Counts|None    is_valid(a) -> bool|None
placed(a, T) -> Shape                directed_extent(a, dir) -> (lo, hi)
triangles(a) -> Tris                 raycast(a, origin, dir) -> [pt]
capabilities() -> set[Cap]           tolerance_class(check) -> exact|approx|unsupported
```

The last two are the additions to cad-khana's implicit surface, and they're what make
tiering honest rather than silent.

**Own value types** (`Vec3`, `Transform`, `Plane`, `BBox`) replace the five build123d type
leaks — `Part`/`Location`/`Plane`/`Axis`/`Color` in `PlacedPart`, `Anchor`,
`RevoluteJoint`, `Distance`, and `with_part`'s isinstance guard. That is the entire
lock-in, and removing it is mechanical.

**Contract stays Python** (reversing my own first sketch — see investigation 02 §8 F2). A
Python contract module references a `.scad` file as easily as a Python model, so it is
engine-neutral anyway; it's more expressive; it needs no schema, avoiding the DSL trap your
`agent-policy` decision log marks **locked**; and it extends the `Spec.__post_init__` idiom
already in `build123d-template`. The "an agent can silently delete an assertion" objection
is answered by a semantic `diff` that reports `removed:`.

---

## 4. Three result states, not two

The single most important design rule, and it generalizes cad-khana's existing tri-state
skip:

| status | meaning |
|---|---|
| `pass` | evaluated, satisfied |
| `fail` | evaluated, violated |
| `skipped` | referenced part absent (cad-khana's existing semantics) |
| `unsupported` | **this backend cannot evaluate this check at all** |
| `approximate` | evaluated, but tolerance-bearing on this backend |

A part must never read as green because half its checks were unavailable. cad-khana already
names the adjacent failure — **"vacuous green"**: a module with no assertions exits 0 and
writes `"assertions": []`, and *"an agent will read it as success."* Unsupported-as-pass is
the same disease. So the top-level verdict must carry the counts, and `just check` should
fail loudly on a contract whose checks were mostly unavailable.

`approximate` is the subtler one and it comes straight from the spike: mesh `clearance` and
`tangent_contact(tol_mm=1e-3)` degrade below tessellation chord error **without changing
their name or report shape.** That's the trap. Naming it in the report is the fix.

---

## 5. v0 scope

Two classes of check, and only one is tiered:

- **Class 1 — parameter checks.** Pure arithmetic over inputs, evaluated *before* any
  engine runs. **Fully engine-neutral, no kernel needed.** `bayonet-lock-scad`'s entire
  documented rule set is class 1: `entry_depth < part_height`,
  `pin_radius + allowance/2 ≤ shell_thickness`, `0 < sweep_angle < 360/number_of_pins`.
- **Class 2 — geometric checks.** Post-build, tiered mesh vs BREP.

**v0 = class 1 + `builds` + `envelope` + `watertight` + `solid_count` + `genus`.**

> **Corrected 2026-08-02 while writing `SPEC-contract.md`:** an earlier version of this
> section also listed `clearance` and `interference`. They are indeed capability-portable
> (exact on polyhedra via `manifold3d.min_gap`), but **they take two bodies, and v0 is parts
> only (D11)** — a category error. They move to post-v0 with assemblies, where they have a
> subject. The portability finding carries over unchanged.

Revised upward after investigation 04 — **the portable core is considerably larger than the
first estimate.** All of these answer *exactly* on both tiers for polyhedral geometry:
bounding box, watertightness, solid count, genus, planar-face grouping, clearance
(manifold3d `min_gap` returned exactly 7.5) and interference volume (800.000000 on both
sides). Genus is the pleasant surprise — a real topological invariant that survived
tessellation perfectly at every `$fn` from 16 up, so **through-hole counting is portable**.

`solid_count` no longer needs `scipy`/`networkx`: manifold3d `.decompose()` and trimesh
`.body_count` both cover it, and manifold3d is already a dependency (D14).

Volume and area remain opt-in with a **mandatory explicit tolerance** — approx and *biased
high* on mesh (+0.32 % at OpenSCAD default, +0.008 % at `$fn=64`).

BREP-only and irreducibly so: hole diameter, fillet radius, bolt circle, self-intersection,
STEP round-trip. **Do not attempt to recover these from mesh** — see D10 and investigation
04 §4 for why fitting produces confident wrong numbers in the unsafe direction.

And one check runs the *other* way: **overhang angle is better on the mesh** (per-triangle
normals are exactly the right granularity) than on BREP (point sampling, wrong on curved
faces). This is not a hierarchy with BREP on top.

---

## 6. First moves

1. Scaffold to current standards — `uv`, `justfile` (`setup/fmt/check/test`), `AGENTS.md`
   with a Constraints section, `ok` CI gate. Python 3.12+, ruff, pyright.
2. Define `GeometryBackend` + value types + the report schema **first**. Schema before
   implementation, per your own discipline.
3. `OcctBackend` with the CadQuery adopt shim. Verified to work today.
4. `MeshBackend` over trimesh, declaring reduced capabilities honestly.
5. Port cad-khana's assertion vocabulary onto the protocol, with attribution (Apache-2.0).
6. **Dogfood**: `bayonet-lock-scad` (OpenSCAD, real fit/clearance rules already written in
   its README) and `parametric-sensor-manifold` (build123d, real requirements already in
   `docs/design_process.md`). Write `results.md` in the `scadman-dogfood` house style —
   numbered findings, before/after table, validation-payoff proof.

Step 6 is the deliverable; 1–5 are setup. Success condition is unchanged from the first
pass: enough evidence to retire *"No unit tests for geometry"* from your own CAD domain
profile.

---

## 6b. Fixtures — better supply than expected

Three finds dominate:

1. **`pzfreo/cadgenbench-build123d` → `selfbench/fixtures/{9001..9017}/part.py`** — 14
   hand-authored build123d reference programs, **Apache-2.0**, 14–97 lines, each with a
   docstring stating the engineering intent *and the specific reasoning failure it
   targets*. Purpose-built, small, permissive. Take wholesale.
2. **`BenCaunt/SynthCAD`'s `m3564c_load_cell.py` + its pytest** (MIT, 236 lines) — the
   requirements ↔ geometry ↔ test triple you're trying to build, at fixture scale, driven
   off a vendor drawing. Real press fits: `DOWEL_HOLE = 3.01` for a Ø3 dowel, tap-drill
   Ø4.2 for M5, bolt circles.
3. **Gridfinity implemented in all three engines, all MIT** —
   `kennetek/gridfinity-rebuilt-openscad` (2,212★), `michaelgale/cq-gridfinity` (201★),
   `Ruudjhuu/gridfinity_build123d` (96★). **The same specified part in OpenSCAD, CadQuery
   and build123d** is the ideal cross-engine differential test: one contract, three
   engines, and any divergence in the report is a tool bug rather than a design difference.

Add for coverage: `build123d/examples/heat_exchanger.py` (149 hex-packed tubes + an inline
design-guard `assert`), `cadquery/examples/Ex100_Lego_Brick.py` (clearance + derived wall +
shell), `bd_warehouse`'s `ClearanceHole(fastener, fit="Close"|"Normal"|"Loose")` backed by
real CSV standards tables — that last one is a **typed fits API**, the rarest thing in the
corpus, and directly relevant to a clearance vocabulary.

Plus your own OpenSCAD: `bayonet-lock-scad` (already spiked) and `most-scad-libraries`.

**Licensing — do not vendor:** NopSCADlib is GPL-3.0 (and is ironically the best finished
OpenSCAD part corpus, 30+ real printed products); `openscad/openscad` examples are GPL-2.0;
Text2CAD, Fusion 360 Gallery and everything derived from it are **non-commercial**;
**CADPrompt has no license at all** (all-rights-reserved by default) — usable as private
fixtures, blocker for redistribution. dotSCAD (LGPL-3.0) and MCAD (LGPL-2.1) have untested
"linking" semantics for `include <>` in a non-compiled language.

Also worth reading as prior art: **`mikelmyers/argus-diff`** — geometric diff and CI for
STEP/mesh with body- and face-level change detection and mass/interference gates.

---

## 7. Calls — all resolved

See `../DECISIONS.md` for the reasoning. Summary:

| | Call |
|---|---|
| C1 Name | **`partspec`** (D9) |
| C2 `approximate` | **Non-green** — its own status (D10) |
| C3 Assemblies | **Parts only in v0**; assemblies a tracked post-v0 goal (D11) |
| C4 PartCAD | **Out of scope for v0**; revisit post-v0 as a parts source (D12) |

The C4 answer turned out to be the sharpest of the four. PartCAD achieves engine
neutrality by **normalizing everything to OCCT** — an OpenSCAD part is rendered to binary
STL and re-imported via `b3d.Mesher().read(...)`, so it arrives downstream as a
`TopoDS_Shape` of triangular faces. Every topology check then runs and returns a number,
but `face_count` is a triangle count and there are no cylindrical faces to find holes in.
No capability declaration, no degradation signal.

That is the exact failure D10 exists to prevent, implemented. It is the right call for
PartCAD's actual consumers (packaging, BOM, sourcing, assembly, visualization — none of
which ask topology questions) and the wrong foundation for a verification tool, whose
whole value is knowing what it cannot prove. **It is now the clearest single point of
differentiation for `partspec`.**

---

## 8. Next: specs and plans

With D1–D12 settled, the remaining writing is:

1. **`SPEC-report.md`** — the report schema and exit-code contract; the product seam (D5).
   **Draft 4. Adversarially reviewed (see `TRIAGE.md`), decisions D-1/D-2/D-3 applied.**
2. **`SPEC-contract.md`** — the Python contract API and the closed v0 `kind` vocabulary.
   **Draft 1 written.** Resolves the report spec's Q7: parameter predicates are not
   measurements — a `requires` check carries `expr` + `operands`.
3. **`SPEC-backend.md`** — the `GeometryBackend` protocol, capability declaration, and the
   OCCT adopt shim. **Draft 1 written** (unblocked by D15).
4. **`PLAN.md`** — **written.**
5. **`POST-V0.md`** — **written.** The assembly backlog from D11, recorded now so the v0
   model carries it rather than being retrofitted.
