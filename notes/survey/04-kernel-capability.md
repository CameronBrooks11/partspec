<!-- Vendored 2026-08-09 from the survey workspace (working-b123d-agentic),
     unmodified below this header. Cited under **Backing:** by the specs in
     docs/, which pointed at a path no reader of this repository could open —
     the loss class notes/README.md exists to prevent. -->

# Investigation 4 — Kernel capability, verified by execution

**Date:** 2026-08-02. All findings run locally against OpenSCAD 2021.01 **and** the
2026.08.01 nightly, build123d 0.11.1, CadQuery 2.8.0, trimesh 5.0.0, manifold3d 3.5.2.

---

## 1. Verdict

Tier the vocabulary — but the split is **two tiers, not three**, and the portable core is
**larger** than assumed.

- **CadQuery and build123d are the same kernel, the same binding, the same objects.**
  Both resolve to OCP **7.9.3.1.1**. `IsSame()` is `True` after rewrapping in *both*
  directions — the conversion is a handle rewrap, not a geometric rebuild. Writing a second
  CadQuery backend is wasted work.
- **OpenSCAD is not a weaker BREP engine.** It is a different category of thing that never
  had faces, edges, volume or area. No conversion creates them.

---

## 2. The capability table

**Exact** = analytically correct · **Approx** = tessellation-dependent · **✗** = unavailable.

| # | Check | OCCT BREP | Triangle mesh | Mesh library |
|---|---|---|---|---|
| 1 | Bounding box | Exact | **Exact** | trimesh `.extents` |
| 2 | Volume | Exact | Approx, **sign depends on geometry** — see correction below | trimesh, manifold3d |
| 3 | Surface area | Exact | Approx (+0.0006 % `$fn=64`) | trimesh, manifold3d |
| 4 | Center of mass / inertia | Exact | Approx (exact for polyhedra) | trimesh `.center_mass` |
| 5 | Watertight / manifold | Exact | **Exact** — topological property of the mesh | trimesh `.is_watertight` |
| 6 | Self-intersection | Exact (`BOPAlgo_ArgumentAnalyzer`) | **✗ — real gap** | needs GPL libigl or heavy pymeshlab |
| 7 | Solid / component count | Exact | **Exact** | trimesh `.body_count`, manifold3d `.decompose()` |
| 8 | Genus / through-holes | Exact | **Exact** — recovered genus=1 at every `$fn` from 16 up | trimesh `.euler_number`, manifold3d `.genus()` |
| 9 | Planar face detection | Exact | **Good** — coplanar grouping gave 70, matching CGAL exactly | trimesh `.facets` |
| 10 | Cylindrical face / hole Ø | Exact (`f.radius` → 3.000000) | **✗** | fitting is unsafe — see §4 |
| 11 | Edge / fillet radius | Exact | **✗** | — |
| 12 | Hole axis + bolt circle | Exact — *"4 holes Ø5.000 on Ø40.000 bolt circle"* in ~10 lines | **✗** | inherits §4's unsafety |
| 13 | Wall thickness | Approx (no closed form; ray/sphere over a tessellation) | Approx — **the industry-standard method** | trimesh `proximity.thickness` |
| 14 | Clearance / min distance | Exact (`BRepExtrema_DistShapeShape`) | **Exact for polyhedra** — manifold3d `min_gap` returned exactly 7.5 | **manifold3d `.min_gap()`**, no extra deps |
| 15 | Interference volume | Exact | **Exact for polyhedra** — 800.000000 both sides | manifold3d boolean |
| 16 | Overhang angle | **Approx and awkward** — point sampling, wrong on curved faces | **Exact and natural** — per-triangle normals | trimesh `.face_normals` |
| 17 | Cross-section | Exact | Approx (polyline) | trimesh `.section()` |
| 18 | STEP round-trip | Exact (Δvol 1e-11) | N/A | — |
| 19 | Draft angle | Approx | Approx | trimesh face normals |

> ⚠️ **Correction (2026-08-02, after adversarial review).** The original row 2 read
> *"biased high (+0.32 % default, +0.008 % `$fn=64`)"*. **That is wrong, and it was
> contradicted by our own data at the time.** An inscribed polygonal approximation
> under-reports: measured, `cylinder(h=10, r=5, $fn=16)` gives **765.37 vs a smooth 785.40
> — −2.55 %**, eight times the cited magnitude and the opposite sign. The bayonet spike in
> investigation 02 already showed volume *rising* with refinement (631.24 → 633.85 →
> 634.51 for `$fn` 32 → 64 → 128), i.e. coarse tessellation reads **low** — and that was
> not reconciled against the "+0.32 %" figure. The original number came from a different
> part whose own caveat said "characteristic, not a general bound"; it was generalized when
> it should not have been. **There is no universal sign.** Derive it per evaluation.

**Read it by shape, not row by row:**

- **Rows 1, 5, 7, 8, 9, 14, 15 — genuinely engine-neutral.** Bounding box, watertightness,
  solid count, genus, planar faces, clearance and interference all answer *exactly* on both
  sides for polyhedral geometry. **This is a much larger portable core than expected** —
  genus especially, a real topological invariant that survives tessellation perfectly.
- **Rows 2, 3, 4, 17 — neutral in form, tiered in trust.** Same number, different error
  bars. Usable everywhere *if each result carries its bound and sign*.
- **Rows 6, 10, 11, 12, 18 — BREP-only, irreducibly.** No conversion recovers them.
- **Row 16 runs the other way.** Overhang is *better on the mesh*; the BREP needs deliberate
  sampling. Rows 13 and 16 are naturally mesh-side checks that work on BREP only by meshing
  it first. **This is not a hierarchy with BREP on top — it is two representations with
  different strengths.**

---

## 3. OpenSCAD: three traps

**Stable OpenSCAD is 2021.01, dated 2021-01-31 — five and a half years old.** Nightlies ship
roughly weekly and are a different product: Manifold backend by default, `--summary`,
`--backend`, 19 export formats vs 8. Everything machine-readable exists **only in
unreleased nightlies**.

But `--summary` is not worth the dependency, for three measured reasons:

1. **It gives only bounding box, counts, and a `simple` flag.** No volume, no area, no
   center of mass, no genus (`Genus: 1` prints to console but is deliberately absent from
   the JSON).
2. **The schema depends on the backend.** Same file, same nightly: `facets` = **272**
   (triangles) under Manifold, **70** (planar facets) under CGAL. And solid count
   (`volumes`) exists *only* on CGAL — the non-default backend.
3. **Invalid geometry produces JSON missing the validity field, and exits 0.** Fed an open
   3-triangle shell, the `geometry` block came back with **no `simple` key at all**, and
   OpenSCAD wrote the STL and exited 0. A checker doing `.get("simple", True)` **silently
   passes broken geometry.** trimesh caught it instantly: `is_watertight=False,
   volume=-416.67`.

> **Never let OpenSCAD self-report validity.** Export `binstl` and measure the mesh.

This also dissolves the version problem: if the tool ignores `--summary` entirely, 2021.01
and the nightly become nearly interchangeable and the schema drift stops mattering.

(`binstl` specifically: lib3mf **cannot read ASCII STL**, and 2021.01's STL default *is*
ASCII. PartCAD hit this too.)

---

## 4. Mesh→BREP is a trap — and the reason is beautiful

Sewing an STL gives a valid solid with empty semantics, at absurd cost:

| | faces | types | STEP size |
|---|---|---|---|
| Native BREP (block + Ø6 hole) | 7 | 6 PLANE + **1 CYLINDER** | **19 KB** |
| Sewn from its own STL | 272 | 272 PLANE, **0 CYLINDER** | 614 KB (**32×**) |
| Native BREP (bracket, 9 holes) | 19 | 6 PLANE + **13 CYLINDER** | **65 KB** |
| Sewn from 5,096-tri STL | 5,096 | 5,096 PLANE, **0 CYLINDER** | 11.9 MB (**182×**) |

~2.4 KB of STEP per triangle, linear. A 100k-triangle part ≈ 240 MB.

build123d shipped `brep_from_stl.py` with RANSAC `detect_primitives()` in April 2026, and it
works well in general (5,096-triangle bracket → all 13 cylinder radii recovered exactly,
58 s). **Applied to OpenSCAD it is actively dangerous:**

OpenSCAD's `cylinder($fn=16)` is not a tessellated cylinder — it is a **genuine 16-sided
prism** whose true BREP is all planes. Its vertices lie exactly on the nominal circle, so
fitting recovers the **circumscribed** radius:

```
$fn=16  →  detected "CYLINDER", radius 5.0000
           true minimum clearance (apothem) = 4.9039
```

So `hole_diameter >= 10.0` **PASSES at a reported Ø10.000** on a hole whose real bolt
clearance is **Ø9.808** — and **the error is always in the unsafe direction**: over-reporting
holes, under-reporting shafts.

> **The genuinely useful inversion:** for an OpenSCAD part the *inscribed* diameter
> `d·cos(π/n)` is the number a real dowel experiences — and the BREP tier, reporting a
> perfect `radius = 3.000000`, **cannot see this at all.** The mesh is not merely a degraded
> BREP. For fit and printability it is sometimes the *more honest* representation.

Note also which way every production tool actually travels: Netfabb — the industry's answer
to "one tool for mesh and CAD" — converts CAD *"directly and permanently into triangle
meshes"* on import. Glovius runs wall-thickness on STEP by tessellating. **The mainstream
solution is BREP→mesh, not mesh→BREP.**

---

## 5. PartCAD — the confirmation, sharpened

Independently corroborates the primary-source read in `DECISIONS.md` D12, and goes further:

**PartCAD has no measurement layer at all.** `shape.py` contains no `volume`,
`bounding_box`, `area`, `is_valid`, `is_manifold` or `center_of_mass`. Repo-wide,
`BRepGProp` appears in exactly two places, one of which is a dedup hash. Its entire
geometric test is:

```python
class CadTest(Test):
    async def test(self, ...):
        wrapped = await shape.get_wrapped(ctx)
        if wrapped is None:
            return self.failed(shape, "Failed to get the shape")
        return self.passed(shape)
```

That checks only that a shape was produced. The one real geometric check
(`cam_additive_solid.py`, free-bounds → "not solid") carries two `TODO(clairbee)` markers
conceding it is a stub. And the `interfaces:`/mating layer is **pure declared YAML** — port
locations come from `config["location"]`, never from geometry. **Nothing verifies that a
declared port corresponds to real material.**

> **PartCAD's engine-neutrality is real *because it never measures anything*.** Uniformity
> across mesh and BREP is easy at the representation layer and hard at the measurement
> layer, and PartCAD only ever attempted the easy one.

Strong precedent for `TopoDS_Shape`-as-currency; **no precedent at all** for a verification
layer — which is exactly where `partspec`'s value sits.

Also: the fallback path is worse than the primary and chosen *silently in an exception
handler* — `import_stl` returns a single **`Face` carrying a triangulation**, not a solid,
with no computable volume. Same `TopoDS_Shape` type, radically different measurability.

**Dependency weight, if it were ever considered:** PyPI latest is **0.7.135, uploaded
2025-04-11** — ~16 months behind `main`. Resolves to **101 packages** including Docker SDK,
`sentry-sdk`, and five OpenTelemetry packages. Pins **`build123d==0.8.0` and
`cadquery-ocp==7.7.2`**, which would collide head-on with a 0.11.1 / 7.9.3 environment.

---

## 6. The market gap

**There is no open-source DFM check library to adopt.** Consumer slicers (PrusaSlicer,
Orca, Cura, Bambu) do **no DFM at all** — they check mesh validity and treat thin
walls/overhangs as *slicing strategies*, not reported checks. Commercial mesh DFM exists
and its methods are documented and reimplementable (ray casting and maximum-inscribed-sphere
for thickness, per-facet normals for overhang, voxel flood-fill for trapped volume), but
`dfm-checker` and `AMDFM` do not exist and `SmartDFM` is an empty 3-star skeleton. PySLM
(overhang, supports, build time; trimesh-based) is the closest reusable component.

**That gap is the strongest argument that the value lives in the check library itself.**

---

## 7. Dependency call

**trimesh + manifold3d.** Light, pure wheels, no Blender or OpenSCAD shell-out for
booleans, and manifold3d is *the same kernel OpenSCAD now uses by default* — so measuring an
OpenSCAD part with manifold3d is unusually well matched. manifold3d also exposes far more
than CSG: `genus`, `volume`, `surface_area`, `min_gap`, `decompose`, `slice`, `ray_cast`,
`calculate_curvature`.

Accept the row-6 gap (self-intersection) rather than pulling in **GPL** libigl or heavyweight
pymeshlab. Add `rtree` only if trimesh proximity is needed over manifold3d's `min_gap`.

⚠️ **Confirmed dependency landmine:** `cadquery-ocp` and `cadquery-ocp-novtk` both install a
top-level `OCP/` package, and pip/uv **do not detect the conflict** — both install and one
silently clobbers the other. It happened to work in our spike because versions matched.
PartCAD hits this in production and works around it (*"Last: re-asserts the VTK-enabled OCP
that build123d's 'cadquery-ocp-novtk' dependency has just replaced"*). **Pin one OCP
explicitly and lock it.**

---

## 8. Caveats on this evidence

The hands-on OpenSCAD comparisons used one deliberately simple part (block + through-hole)
plus one 9-hole bracket. The volume-error figures are characteristic, not a general bound —
a part dominated by curved surfaces would be worse. The PartCAD read was of `main` at clone
time; its PyPI release differs substantially.
