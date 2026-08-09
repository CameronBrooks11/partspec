# SPEC — the `partspec` contract

**Status:** draft 2 · 2026-08-08 · adds §4.4–4.7 (regions, hole_diameter, bolt_circle,
fillet_radius), §10 (referenced values) and §11 (fragments)
**Scope:** the Python API an author (human or agent) writes to declare a part and the
claims it must satisfy. Defines the `kind` vocabulary that `SPEC-report.md` deliberately
left open.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** D6 (contract is Python), D11 (parts only), D15 (measurand), `SPEC-report.md`.

---

## 1. Shape

A contract is an **ordinary Python module** that declares parts. It is not a config file,
not a DSL, and not a test file. Per D6 this buys expressiveness and costs no schema.

```python
# parts/bayonet/spec.py
from partspec import Part, openscad

SHELL_T = 2.5
PIN_R   = 1.0

def lock() -> Part:
    """The bayonet lock half. Defaults are the master design."""
    p = Part("bayonet-lock-pin", openscad(
        "vendor/bayonet_lock.scad",
        half="lock", interface_radius=8, allowance=0.2, part_height=8,
        entry_depth=4, number_of_pins=2, pin_radius=PIN_R, sweep_angle=40,
        shell_thickness=SHELL_T,
    ))
    # parameter phase — arithmetic over inputs, no engine needed
    p.requires("entry_depth < part_height")
    p.requires("pin_radius + allowance/2 <= shell_thickness")
    p.requires("0 < sweep_angle < 360/number_of_pins")
    p.param("interface_radius", min=0.1)
    # geometry phase
    p.envelope(max=(40, 40, 15))
    p.watertight()
    p.solid_count(1)
    return p
```

### 1.1 Rules

1. **A contract module MUST NOT do anything effectful on import.** No building, no export,
   no `if __name__ == "__main__"`. The CLI imports the module and applies exactly one
   effect. Borrowed from cad-khana, where it is load-bearing: the same module is imported by
   `check`, `measure` and `render`, and each applies its own single effect.
2. **A part factory is a module-level function annotated `-> Part`.** The annotation is the
   discovery mechanism (§2).
3. Contract modules MUST be importable without the CAD engines installed. Importing
   `partspec` MUST NOT import build123d, CadQuery, trimesh or OCP — those load lazily in
   the backend, so the parameter phase and `--list` stay fast.

---

## 2. Target resolution

A **target** is `<module-path>[:<factory>]`.

- With `:factory` → call `getattr(module, factory)()` with **its defaults**. A factory's
  defaults are the master design.
- Without → if the module declares exactly one `-> Part` factory, use it. If it declares
  several, that is an error, and **the error message is the discovery mechanism**: it MUST
  list every available factory. (Directly cad-khana's `factories()` idea, which finds them
  by runtime introspection of the return annotation.)
- Resolution failure exits `64` (`EX_USAGE`) and writes no report.

Report paths derive deterministically from the target so co-located targets never clobber
each other's report, and a stale file is overwritten rather than accumulating beside its
replacement (`SPEC-report.md` §5.5).

---

## 3. Source declaration

One constructor per engine. Each takes a source reference plus the parameters to build with.

```python
openscad(path, **params)      # params become -D name=value  (see §3.1)
build123d(target, **params)   # target: "module:callable" or a callable
cadquery(target, **params)    # adopted into the OCCT backend via .wrapped (D3)
```

The engine is declared, never sniffed from the file extension: a `.py` file could be
either Python engine, and guessing is exactly the kind of implicitness this project exists
to remove.

`params` are the single source of truth for the build. They are what parameter checks
evaluate against, what is recorded in `report.params`, and what feeds `source_digest`'s
sibling identity. **A parameter MUST NOT be declared in two places** — if the `.scad` sets
`allowance = 0.2` internally and the contract also passes `allowance=0.2`, the contract
wins and the report records the contract's value.

### 3.1 OpenSCAD parameter passing

Parameters become `-D name=value` overrides of top-level variables. Where the contract
names a `method`, the parameters become a call to that module appended to a **throwaway
copy** of the source; the source file is never modified. This is PartCAD's proven approach
(D12) and is adopted deliberately.

Values render as OpenSCAD literals: numbers as-is, `True`/`False` → `true`/`false`, strings
quoted and escaped, sequences → `[...]`, `None` → `undef`. Any other type is a contract
error.

---

## 4. Check vocabulary — closed at each release

`SPEC-report.md` §7.1 declares `kind` an open vocabulary so the report format never needs
revising when a check is added. **This document closes it at each release**: v0 shipped the
set below through `topology`; `keep_out` / `keep_in` (§4.4), `hole_diameter` (§4.5),
`bolt_circle` (§4.6) and `fillet_radius` (§4.7) are the post-v0.1 additions, from epic #6;
`draft_angle` (§4.8), `self_intersection_free` (§4.9) and `step_roundtrip` (§4.10) are
the depth epic's (#136).

### 4.1 Parameter phase

| method | `kind` | shape |
|---|---|---|
| `p.requires(expr)` | `requires` | predicate — see §5 |
| `p.param(name, min=, max=)` | `param_range` | measurement + limit |

`p.param` is the structured form and SHOULD be preferred when the claim is a simple bound
on one named parameter, because it produces a real measurement that `diff` can track drift
on. `p.requires` is the escape hatch for anything relational.

### 4.2 Geometry phase

| method | `kind` | measurement | tier |
|---|---|---|---|
| *(implicit)* | `builds` | none | both |
| `p.envelope(max=, min=)` | `envelope` | vector, `mm`, exact | both |
| `p.watertight()` | `watertight` | bool-valued, exact | both |
| `p.solid_count(n)` | `solid_count` | scalar, `count`, exact | both |
| `p.genus(n)` | `genus` | scalar, `count`, exact | both |
| `p.cavities(n)` | `cavities` | scalar, `count`, exact | both |
| `p.volume(min=, max=)` | `volume` | scalar, `mm3` | both |
| `p.area(min=, max=)` | `area` | scalar, `mm2` | both |
| `p.topology(faces=, edges=, vertices=)` | `topology` | vector, `count`, exact | **occt only** |
| `p.keep_out(region, shell=)` | `keep_out` | vector, `mm3`, exact | both |
| `p.keep_in(region, shell=)` | `keep_in` | vector, `mm3`, exact | both |
| `p.hole_diameter(d, count=, tol=)` | `hole_diameter` | vector, `mm`, exact | **occt only** |
| `p.bolt_circle(d, count=, bcd=, tol=)` | `bolt_circle` | scalar, `mm`, exact | **occt only** |
| `p.fillet_radius(min=, max=)` | `fillet_radius` | vector, `mm`, exact | **occt only** |

`builds` is **implicit and always present**: every part gets it, and it fails if the engine
exits non-zero or emits no artifact. It is the one check an author cannot forget, and it is
why a contract with no declared checks still reports `empty` rather than crashing.

### 4.2.2 `topology` — the check that makes the tiers visible

Every other v0 kind maps to a primitive both backends declare. `topology` is the exception,
deliberately — and since v0.1 it has company: `hole_diameter` (§4.5) is the first member of
the OCCT-only class whose machinery `topology` shipped to exercise. On the OCCT tier it
compares real modelled counts, and on the mesh tier it
reports `unsupported` with `requires: "occt"`, because a triangle mesh has faces only in the
sense that a mosaic has colours. Returning a triangle count is the PartCAD failure (D12), and
it is prevented structurally — the mesh backend does not declare the capability, so the
refusal happens before dispatch and no measurement is produced to be misread.

Its inclusion is what makes the degradation path **reachable from a contract**. Until it
existed, `SPEC-report.md`'s `requires` field was never populated in a real report and the
capability-refusal branch was unreachable code. A property that cannot be exercised is a
property that has not been tested.

Any subset may be constrained; an omitted axis carries no claim. Edge and vertex counts move
with modelling choices that are rarely intent, so `faces=` alone is usually the honest claim.
`p.topology()` with no arguments is a `ContractError`, not an empty pass — the vacuous-green
guard applies to a single check as much as to a whole contract.

**Its practical use is thin today, and that is recorded rather than papered over.** No part
in the dogfood corpus carries a face count that is *intent* rather than *incident* — the
pillow block's 15 faces are an artefact of how it was modelled, and Gridfinity's standard
fixes no topology, so asserting either would repeat the mistake F12 already caught. What
justifies the kind in v0 is that OCCT-only checks are a **class** the design already
committed to (`hole_diameter`, `fillet_radius`, `bolt_circle`, all post-v0), and shipping
one cheap honest member exercises the machinery those depend on instead of leaving it
unreachable until the first one lands.

A `topology` contract is portable in the sense that matters: it means the same thing on every
engine and says so where it cannot be evaluated. It is **not** portable in the sense of
turning green everywhere, and a part that needs it green belongs on a BREP engine.

### 4.2.1 A consequence of D15 worth stating plainly

An earlier draft required `volume` and `area` to carry a mandatory tessellation tolerance,
citing the 0.5 % drift measured between `$fn=32` and `$fn=128` (investigation 02). **Under
D15 that is wrong, and the reasoning is worth keeping.**

D15 fixes the measurand as *the artifact as authored and exported*. A mesh **is** a
polyhedron; its volume is computed exactly from its triangles. There is no smooth ideal it
approximates, so there is no tessellation error to tolerate. Changing `$fn` does not make a
measurement less accurate — **it produces a different part**, and a volume check written
against `$fn=128` failing at `$fn=32` is the tool working correctly, not a false alarm.

So `volume` and `area` take plain `min`/`max` bounds like any other range check, and the
author sets them from engineering intent rather than from anxiety about facets. The only
residual inexactness on the mesh tier is **float32 coordinate quantization in binary STL**,
which is real, rigorously computable, and roughly 1e-7 relative — see `SPEC-backend.md` §5.

This also retires the framing in `SPEC-report.md` §2 that treated tessellation as the
archetypal source of `approximate`. It is not; under D15 it is a source of *design
difference*, which is a thing the tool should report loudly rather than absorb quietly.

### 4.3 Deliberately NOT in v0

- **`clearance` / `interference`** — `DIRECTION.md` §5 listed these as v0 because they are
  *capability-portable* (exact on polyhedra via `manifold3d.min_gap`). **That was a
  category error: they take two bodies, and v0 is parts only (D11).** They move to post-v0
  with assemblies, where they have a subject. The portability finding stands and carries
  over unchanged.
- **`min_wall`** — `unsupported` on the mesh tier for want of an honest lower bound
  (`SPEC-report.md` §3.2). Ships when the BREP tier does.
- **`hole_diameter`, `fillet_radius`, `bolt_circle`, `self_intersection`, `step_roundtrip`**
  — BREP-tier only. Post-v0.
- **`overhang`** — mesh-native and genuinely better there than on BREP, so it is *cheap*;
  deferred only because printability is a separate concern from dimensional intent and
  would widen v0's story.
- **`is_valid`** — implemented on both backends and reachable through `measure`, but
  deliberately **not** a check kind, because it does not mean the same thing on both. On the
  mesh tier it is "closed, consistently wound, non-zero volume"; on the OCCT tier it is
  "passes `BRepCheck_Analyzer`". Those disagree on real input — an open shell is `is_valid`
  **True** on OCCT and **False** on mesh. A kind whose meaning changes with the tier breaks
  "one contract, evaluated identically wherever it can be", which is a worse failure than
  the gap it would close. `watertight` already carries the portable half of the claim.
- **`center_of_mass`** — tier-consistent and cheap, and it will probably land; held back
  only because nothing in the dogfood corpus has needed it yet, and v0's vocabulary grows on
  demonstrated need rather than on availability. Visible through `measure` meanwhile.

### 4.4 `keep_out` / `keep_in` — interface intent without a second body

A region of space the part MUST be empty in (a bolt hole, a slot, a wrench clearance) or
solid throughout (a boss, a pin, a bearing seat). This is the one form of mechanical
interface intent that needs no reference model and no assembly support, and it is how
CADGenBench scores "interface match". Regions are declared as pure data from
`partspec.region` — `region.box(min=, max=)` and `region.cylinder(d=, h=, at=, axis=,
segments=)` — because the contract layer imports no geometry library (§1.1); each backend
materializes them via its `region_solid` primitive.

**The verification shell is mandatory, and it is the whole design.** The naive claims are
both vacuous: "no material here" is satisfied perfectly by a part with the material
deleted, and "material everywhere here" by an unbounded solid block. Each region is
therefore adjudicated together with a shell of thickness `shell` grown around it, holding
the *opposite* claim in weakened form:

- `keep_out`: the region MUST contain no material, **and its shell MUST NOT be entirely
  empty.** An absent part — and a hole whose clearance exceeds `shell` in every direction —
  fails.
- `keep_in`: the region MUST be entirely material, **and its shell MUST NOT be entirely
  solid.** The brick fails, and so does a feature oversize by more than `shell` in every
  direction.

The shell claims are deliberately the weak forms ("not entirely"), not the strong ones. A
strong keep_out shell — "entirely solid" — is failed by every clearance hole ever modelled,
because the modelled hole is always larger than the declared keep-out and the gap between
them is empty; the mirror kills the strong keep_in shell. `shell` is therefore read as
**the clearance budget**: material must appear within `shell` of a keep-out, and emptiness
within `shell` of a keep-in.

**What this deliberately does not claim: shape.** A hole oversize in one direction only —
an oval through a round keep-out — passes, because material still lies within the shell on
the tight sides. Roundness and diameter are `hole_diameter`'s claims. A region check is a
claim about space, and a contract that needs both should declare both.

**Materialization is tier-identical by construction.** A cylinder region *is* a
circumscribed `segments`-gon prism (flats touch the declared circle), built from one
canonical vertex list on every tier. Circumscribed, because the polygon then contains the
declared cylinder and an "empty" verdict is earned — no material can hide between polygon
and circle. The cost is radial over-approximation by `sec(pi/segments) - 1` (~0.12% at the
default 64), which fails a feature whose clearance to the declared region is micrometres; a
zero-margin region against its own feature's modelled surface is a claim the author should
not write, and on the mesh tier it was never available anyway (the modelled hole is itself
a polygon). Both statuses are conclusive: every volume involved is an exact boolean, so
`approximate` cannot arise; a mesh too broken for exact booleans reports `unsupported`.

The report records the declared region and shell on the check (`SPEC-report.md` §7.1), its
`measurement` is the vector `(region, shell)` of material volumes found, and `limit` is
null — the paired claim has no limit form, and inventing one would misdescribe it.

### 4.5 `hole_diameter` — the first drawing dimension

Exactly `count` cylindrical bores of diameter `d` exist. The first BREP dimension check
(POST-V0 §4), **OCCT tier only**: a triangle mesh has no cylindrical face, and fitting one
to the facets is the confident-wrong-number failure §4.2.2 exists to prevent. On the mesh
tier it reports `unsupported` with `requires: "occt"` — structurally, by the mesh backend
not declaring the `bores` primitive.

**The no-selectors resolution.** §8 deliberately provides no way to name a face, so this
cannot be "*this* hole is Ø8". It is a **count claim over detected bores**: the backend
enumerates every bore on the part, and the check asserts how many fall inside the diameter
band. A **bore** is a set of cylindrical faces sharing one axis line, one radius and one
contiguous axial span, facing *inward* (material surrounds the void — a boss is the same
surface facing out), whose angular extents sum to the full circle. Consequences, each
deliberate:

- **A counterbore counts once per diameter.** Its coaxial portions have different radii, and
  each is a real seat with a real drawing callout — `hole_diameter(8)` and
  `hole_diameter(12)` both hold on a Ø12-counterbored Ø8 hole.
- **A concave fillet (quarter-wrap) and a half-round groove (half-wrap) never count** —
  full-wrap is what separates "a hole" from "a concave cylindrical surface".
- **Two aligned holes through two clevis lugs count twice**: same axis, same radius,
  disjoint axial spans. The drawing says "2× Ø8" and so does the check.
- **Blind and through bores count alike.** Depth is not this check's claim.
- **A cross-drilled hole severed by a larger crossing hole counts once per severed span.**
  This is the clevis rule applied where the drawing disagrees with it: "1× Ø4 cross hole"
  through a Ø8 main bore is two disjoint Ø4 spans, so it counts as two — while two crossing
  holes of *equal* diameter still count once each, because their split spans touch at the
  intersection. An author cross-drilling through a larger bore should declare the count the
  geometry has, not the count the callout abbreviates.
- **A sealed internal cylindrical cavity counts.** The definition is a claim about surfaces,
  not about reachability — a tube's inner wall is a bore (the bearing-seat use case is
  exactly that), and a fully enclosed cylindrical void is the same surface with no opening.
  Nothing distinguishes them at the surface level, and inventing a reachability analysis to
  try would claim more than the check measures.

**What it deliberately does not claim:** position (that is `keep_out`'s and the future
`bolt_circle`'s territory), depth, and the absence of *other* holes — a part with an extra
Ø5 bore still passes `hole_diameter(8, count=2)`, because the claim is about the Ø8 bores.

**`tol` is the drawing's acceptance band** (Ø8 ±0.1 → `tol=0.1`). Omitted, the band is the
comparison epsilon — "modelled exactly as drawn" — the right default for CAD-as-code, where
the model is nominal geometry rather than a measured article. The band is materialised into
`limit` (`min`/`max`) at declaration and membership is plain interval containment: applying
epsilon again at adjudication would tolerance the tolerance.

**Exactness, recorded against a prediction.** POST-V0 §4 expected the first BREP check to
be the first real exercise of `approximate` (`SPEC-report.md` §3.1). It is not: a modelled
cylinder's radius is a surface *parameter*, read exactly, not an estimate carrying an error
interval. The measurement is the vector of matched diameters (exact, `mm`, axes
`bore_1..n`; null when nothing matched), which is what a comparator tracks drift on when a
real tolerance band is in play. The `approximate` machinery remains unexercised, and
POST-V0 §4 now says so.

The report records the declared bore on the check as `hole: {"d", "count"}`
(`SPEC-report.md` §7.1); a failing check's `detail` carries the full bore inventory of the
part, so the reader sees what exists rather than only what is missing.

### 4.6 `bolt_circle` — the mounting-interface callout

Exactly `count` bores of diameter `d`, axes parallel, centres on one circle of diameter
`bcd` — "4× Ø5 on Ø40 BCD" as one check. **OCCT tier only**, built on §4.5's bore
detection (`bore_table`), and adjudicated with **subset semantics**: the claim is that
such a circle of holes *exists*, so an unrelated Ø`d` bore elsewhere does not break it —
while a fifth hole ON the claimed circle does, because "4×" is a count, not a minimum.
Triples of candidate bores *seed* the search; each seed captures loosely (twice the
band), refits the centre by least squares over the capture, and adjudicates **strictly
against the refitted pattern circle** — a raw three-point circumcentre shifts by ~2x any
positional perturbation, enough to eject a conforming hole from a band it genuinely sits
in, and enough to let a cherry-picked centre defeat count exactness. The search is capped
at 60 candidate bores per direction; the cap produces a refusal only when the whole
search ends empty-handed with something unexamined — a passing circle found elsewhere is
still a pass.

Two deliberate edges:

- **`count=2` is a centre-distance claim.** Two bolts on a BCD sit diametrically
  opposite, and a circle through two points is under-determined — so the check asserts
  centre separation `bcd`, and *exactness of count* is only enforceable for `count >= 3`
  (two of four holes on a Ø40 circle genuinely are "2× on Ø40").
- **The bores' own diameters always match at the comparison epsilon**, never at `tol` —
  `tol` is the *positional* band on the circle diameter. A toleranced diameter claim
  belongs to `hole_diameter`; blurring the two would let a wrong-size hole satisfy a
  position claim.
- **`tol` MUST NOT exceed `d`**, refused at declaration. There is no datum to anchor the
  pattern centre (no selectors, §8), so the claim is existential — *some* circle of
  ~`bcd` holds exactly `count` holes — and a band wider than the hole itself makes that
  existential satisfiable by circles no drawing describes. The bound limits the residual
  rather than eliminating it: an author using an explicit `tol` near `d` on a part with
  many same-size holes has weakened the claim, and should keep `tol` at true-position
  scale, far below the hole spacing.

The measurement is the fitted circle diameter (exact, from exact centres; for `count=2`,
the pair closest to `bcd`, so the recorded value cannot depend on face-iteration order);
`limit` is the `bcd` band; the declared callout is recorded as `hole: {"d", "count",
"bcd"}`. On failure the detail carries the candidate count and the nearest circle found.

### 4.7 `fillet_radius` — every blend within bounds

`p.fillet_radius(min=, max=)`: every blend on the part is within the radius bounds.
**OCCT tier only.** `min=` is the machinability claim — no blend tighter than the tool
that must cut it.

**A blend is any partial-wrap cylindrical surface cluster**, either orientation, using the
same clustering as §4.5's bores — which is what stops a seam-split bore's two half faces
from masquerading as blends. Full-wrap surfaces (bores, bosses) never count; their radii
are `hole_diameter`'s business. Slot ends and grooves DO count, deliberately: nothing at
the surface level distinguishes them from fillets, and for the machinability claim they
constrain the tool identically — a definition that guessed at design intent would be
dishonest about what it measured. Toroidal and spherical blends are not yet detected;
that is a recorded gap, not a claim that they conform — and the zero-blend failure detail
names the gap rather than denying such blends exist. One further edge follows from the
partial-wrap definition: a bore *interrupted* along its wall (a keyway'd bore) wraps below
2π, so it leaves `hole_diameter`'s sight and appears here as a blend at the bore's radius.
Both effects err toward spurious FAIL, never silent PASS.

**Zero blends fails.** "Every blend is within bounds" over an empty set is vacuously
true, and vacuous truth is the green this tool refuses; an author who wants no constraint
on an unfilleted part does not declare the check.

The measurement is the full vector of blend radii, ascending, adjudicated by the generic
per-component machinery — so `components` (SPEC-report.md §7.1) names exactly which blend
broke which bound, and the failure detail reads `blend_1=1.5 outside min=2.0`.

---

### 4.8 `draft_angle` — every face releases from the tool

`p.draft_angle(min=, direction=(0, 0, 1))`: every face's draft is at least `min`, for a
mold pulled along `direction`. **OCCT tier only.** `min=` is the release claim — no wall
closer to vertical than the tool can eject.

**There is deliberately no `max=`.** Under the two-half convention every closed solid has
a face square to the pull (a cap, at 90°), so an every-face maximum is unsatisfiable by
construction — and the first draft of this check adjudicated `max` against each face's
MINIMUM draft, letting a face that violated the bound almost everywhere pass silently
(PR #141 review, F1: an executed silent pass). A bound that cannot be held to every face
is refused at the vocabulary level rather than quietly held to fewer.

**Draft is measured per face against a two-half parting axis**: the angle between the face
and the pull line, `asin(|n · d|)` — 0° for a vertical wall, 90° for a face square to the
pull. The two-half convention (the absolute value) is deliberate: a face releases with
whichever mold half it faces, so tops and bottoms measure 90° and pass a `min` naturally —
no exclusion rule exists to game, and the measure is orientation-independent, killing the
reversed-face bug class outright. The declared direction is normalised at declaration and
recorded in the check (`checks[].direction`), because a draft claim without its axis is not
reproducible.

**Exact, or refused — never sampled.** Planes answer directly; cylinders and cones at any
orientation answer in closed form (the face's normal dotted with the pull is a sinusoid in
the wrap parameter; its extreme over the face's wrap interval is at an endpoint, a crest,
or a zero crossing, all enumerable). A face outside those families — sphere, torus,
freeform — refuses the WHOLE check with the face and surface type named: a sampled minimum
has no guaranteed lower bound (more samples can only find a smaller draft, the same
one-sidedness that keeps `min_wall` out — POST-V0 §5), and a verdict that skipped a face
would be silence reading as success. This also means the check does not carry the
`approximate` obligation POST-V0 §4 records; that debt moves to the first check with a
genuinely bounded interval.

**What per-face normals cannot see is a recorded gap, not a claim**: a feature-level
undercut — material elsewhere blocking release along an otherwise-drafted path — is
invisible to surface interrogation. `draft_angle` proves wall-release geometry; it does not
prove moldability.

`min` must be in (0, 90]: the measure is non-negative by construction, so `min=0` would
pass every face vacuously and is refused at declaration. The measurement is the full vector
of per-face drafts, ascending, adjudicated by the generic per-component machinery — so
`components` names exactly which face broke which bound, and the failure detail reads
`face_3=0 outside min=2.0`. `min=` is a number an author chose, so the kind is in
`DIMENSIONAL_KINDS` and an unattributed bound draws the §6 warning; the pull axis is part
of the claim's identity, so `direction` is a claim field the report diff compares.

---

### 4.9 `self_intersection_free` — the shape does not cross itself

`p.self_intersection_free()`: no sub-shape pair intersects where the boundary says it must
not. **OCCT tier only** — D14 accepted the mesh-side gap deliberately rather than pull in
GPL libigl or heavyweight pymeshlab, and that decision stands; the mesh tier refuses with
`requires: occt`.

A self-intersecting BREP measures volume and topology plausibly and fails downstream —
booleans, STEP consumers, slicers — the classic silently wrong part. The check is the
kernel's own argument analysis (`BRepAlgoAPI_Check`, self-intersection mode): **exact**,
because it is analysis, not sampling. The failure detail is an inventory of the faults by
entity type (`8 self-intersecting entity fault(s): 2 edge/edge, 2 edge/face,
4 vertex/edge`) — "fault(s)", not "pair(s)", because a face caught against ITSELF reports
as a single entity.

**The recorded limit, executed:** a self-intersection lying within a single ANALYTIC
surface — the spindle torus, `Torus(6, 10)` — goes undetected and **passes**, alone, fused
with a box, or inside a compound. The escape is specifically the analytic case: the kernel
does test a face against itself, and a self-overlapping SWEPT face (adjacent helix coils,
pitch smaller than the profile) is caught as a pair-less fault. Both directions are pinned
by tests, so if the kernel's reach ever moves, the spec sentence moves with it.

**Relationship to `is_valid`, executed in both directions:** neither subsumes the other —
the overlapping helix is `is_valid` and self-intersecting; an open shell forced into a
solid is invalid and self-intersection-free. `is_valid` is BRepCheck's well-formedness;
this check is interference. Declare the one whose failure you mean.

**Multi-solid parts:** a compound of two overlapping unfused solids **fails** — a
multi-solid compound is one part, and its solids crossing is its own boundary
contradicting itself, not D11 two-body clearance (which needs two parts and stays with
assemblies). A part built as a compound of deliberately touching solids should be fused
before it is measured.

The quantity appears in `measure` (parameterless, like `watertight`), so an author sees it
before deciding to claim it.

---

### 4.10 `step_roundtrip` — the part survives its own exchange format

`p.step_roundtrip(tol=1e-9)`: written to STEP and read back, the part's volume and area
change by at most `tol` (relative) and its topology counts do not change at all. **OCCT
tier only** — STEP is a BREP format; a mesh has no BREP identity to preserve, and the mesh
tier refuses with `requires: occt`.

STEP is how a part leaves for manufacturing; a shape that degrades through its own
exchange ships a different part than the one verified. **Two gates, deliberately
separate**: topology drift (solids, faces, edges) fails at ANY tolerance — a count that
changed is a different part — and only then are the relative deltas held to `tol`. The
deltas are **exact**: both sides are the kernel's own exact quantities, so the comparison
is a computed number, not an estimate. (Consequence: this check does not carry POST-V0
§4's `approximate` obligation either; after this slice that debt rests entirely on
`min_wall`, #140, and if that slice ends in a recorded refusal the obligation stays
outstanding and recorded.)

**The default `tol` is calibrated, not chosen**: healthy construction families (booleans,
fillets, lofts, helical sweeps) round-trip at ≤ ~5e-14 relative; real degradation — an
ill-formed open shell forced into a solid, which the reader's healing silently drops —
loses its ENTIRE volume (`volume_rel = 1.0`, solids 1 → 0, the executed degrader in the
test suite). 1e-9 sits five orders above the noise and nine below the failure.

The writer schema (`AP214IS` on the current toolchain) is recorded on the check
(`checks[].step.schema`) because it changes the artifact — the F13 lesson. The exchange
happens in a scratch directory: the check is about survivability, not producing an
export. `tol` is a fidelity tolerance with a calibrated default, not a design dimension,
so the kind is deliberately NOT in `DIMENSIONAL_KINDS` and draws no attribution warning.

---

## 5. Q7 resolved — predicates are not measurements

`SPEC-report.md` §11 Q7 asked whether `predicate` is a limit form or a kind, and flagged
`{"value": true, "unit": "bool"}` as a tell that parameter checks were being forced through
a model built for geometric measurement. **They were. Resolution:**

> A `requires` check has **no `measurement` and no `limit`.** It records the expression and
> the values of the operands it read.

```jsonc
{
  "id": "pin_fits_shell",
  "kind": "requires",
  "phase": "parameter",
  "status": "fail",
  "measurement": null,
  "limit": null,
  "expr": "pin_radius + allowance/2 <= shell_thickness",
  "operands": { "pin_radius": 1.0, "allowance": 0.2, "shell_thickness": 1.0 },
  "detail": "1.1 <= 1.0 is false"
}
```

This is strictly better than a bool measurement in three ways: an agent reading a failure
gets the *inputs that produced it* without re-deriving them; `diff` can report operand drift
on a check that still passes (the §7.2 principle, applied to parameters); and `unit: "bool"`
disappears, which was never a unit.

`expr` and `operands` are additive fields, so per `SPEC-report.md` §7.1 this is a
non-breaking change and does not bump `schema_version`. `bool` is removed from the §2.2
unit table.

**`p.param(...)`, by contrast, keeps the measurement/limit shape** — it *is* a bounded
scalar, and forcing it into the predicate form would lose the drift tracking that makes
§7.2 worth having. Two shapes, each where it fits.

### 5.1 Expression evaluation

`requires` expressions are evaluated against the declared `params` in a namespace
containing **only** those params and arithmetic builtins. No imports, no attribute access,
no calls. This is not a security boundary — the contract is already arbitrary Python (D6)
— it is a *legibility* boundary: an expression the tool can print operands for is worth
more than one it can only report as false.

An expression referencing an undeclared name is a contract error (`verdict: "error"`), not
a failing check. Chained comparisons (`0 < sweep_angle < 360/number_of_pins`) are supported
and record all operands.

**A `requires` expression MUST be a predicate.** The grammar is recursive, not a rule about
the outermost node:

> An expression is a *predicate* iff it is a `Compare`, a `BoolOp` whose every value is a
> predicate, a `UnaryOp(Not)` whose operand is a predicate, or a bare `Name`.

Anything else is a contract error. Python coerces freely, so without this
`requires("bore_d + 2*wall - plate_y")` — which reads like a clearance — is truthy for
every value except exact equality, and passes green while claiming nothing. The rule has to
recurse because `not (a - b)` and `a <= b and c` both have an admissible outermost node,
and `not X` always yields a genuine `bool`, so no check on the *result* can catch it.

A bare `Name` is admitted because bool parameters are a supported type and
`is_threaded and pitch > 0` is an honest claim. Every `Name` in boolean position MUST
therefore be verified to hold a `bool` **before** evaluation: `and`/`or` short-circuit, so a
guard on the result would fire or not depending on the parameter values, and a contract-shape
error that depends on the values is not one.

Two further refusals, both of expressions that cannot fail:

- An expression that reads **no declared parameter** (`operands_of(expr) == ()`) — its
  result is the same on every run. This matches `Limit.__post_init__`, which already refuses
  a bound that constrains nothing.
- A comparison whose two sides are the **syntactically identical** operand (`x == x`,
  `x >= x`). Broader semantic tautology detection (`x - x >= 0`, `x < x + 1`) is out of
  scope: the cheap syntactic case is worth catching, and the general case is undecidable
  enough that a partial job would mislead about what is guaranteed.

---

## 6. The vacuous-green guard

A `Part` with no declared checks beyond the implicit `builds` produces `verdict: "empty"`
and exit `3` (`SPEC-report.md` §6). The CLI MUST additionally emit a one-line warning
naming the part, because `empty` is the single most likely output when an agent does not
know what to assert, and a silent exit `3` in a batch is easy to miss.

**A run whose every dimensional check is unattributed MUST draw one warning line** on the
same channel, naming the part (#50). The dimensional kinds (`DIMENSIONAL_KINDS`:
`param_range`, `envelope`, `volume`, `area`, `hole_diameter`, `bolt_circle`,
`fillet_radius`) are the ones whose limits are numbers an author chose, and so the ones a
contract can make circular — a bound recomputed from the model's own constants cannot fail
however the design moves, and a single green run cannot distinguish that from a proof.
Attribution (§10) is the distinguisher: **the absence of `source` IS the unattributed
state** — the report does not stamp "unattributed" per check, because an absent claim of
authority must not be dressed as a present one. Topological kinds are absolute claims,
non-circular by construction, and never trigger the warning. Two exclusions are
deliberate and recorded: `requires` predicates are intrinsically relational — attribution
cannot reach an expression string, and counting them would warn forever on legitimate
internal-consistency claims with no remedy — and `keep_out`/`keep_in` regions do not yet
carry attribution (§10), so they stand outside the dichotomy until they do; a
region-only contract receives no warning today, and that is a recorded gap, not a claim
of coverage. The warning is one line, not a status: the five-member status set is closed,
and an unattributed pass is still a pass — of a weaker question. The run-level counts
behind it are in the report as `attribution` (`SPEC-report.md` §7.1), because the report
is the product surface and an agent consuming it over MCP never sees stderr.

**`partspec` MUST NOT auto-generate checks** from an existing part — not even as a
convenience. A check the tool wrote is a check nobody decided, and a report full of them is
vacuous green wearing a costume. `measure` (§7) exists precisely so that authoring a
contract from a real part is easy *and explicit*.

---

## 7. `measure` — how contracts get written

`partspec measure <target>` builds the part and dumps every quantity the backend can
honestly produce, with `exactness` on each, and **emits nothing that would be
`unsupported`**. It is not a check run and produces no verdict.

This is the adoption path and the answer to "how do I retrofit contracts onto 30 existing
OpenSCAD libraries": measure, read, decide which numbers are *intent* rather than
*incident*, and write those as checks. The judgement stays with the author; the arithmetic
does not.

`measure` deliberately reports a **superset** of the check vocabulary. `is_valid` and
`topology_counts` appear here and are not kinds (§4.3) — the first because its meaning
differs by tier, the second because only one tier can answer it. Both are worth *seeing*
while deciding what to claim, which is what this verb is for, and neither can mislead here
because the output carries no verdict. The rule that it emits nothing `unsupported` does the
rest: on a mesh, `topology_counts` is simply absent rather than present-and-wrong.

---

## 8. Non-goals

- **No assemblies, no placement, no joints.** Per D11. §9 records what the v0 model must
  not foreclose.
- **No selectors.** There is no way to name a face or an edge. This is cad-khana's
  deliberate simplification and it is why twelve backend primitives suffice — it sidesteps
  the topological-naming problem entirely.
- **No solver.** Checks check; they do not drive. A contract never adjusts a parameter to
  make itself pass.
- **No severity.** Every declared check is load-bearing (`SPEC-report.md` §9).

---

## 9. Forward compatibility with assemblies

D11 requires the v0 model to *carry* assemblies later rather than be retrofitted. Three
constraints, adopted now at no cost:

1. **`checks[].id` is a free-form string**, so dotted paths (`turret.rotor.arm`) fit without
   a schema change.
2. **Every check records the part references it read** (`part_refs`), even though in v0 that
   is always the single part. It is what makes cad-khana's `qualified()` propagation
   possible later.
3. **The `skipped` status already exists** with the semantics assemblies need — *"absence is
   a legitimate run state, not an input error"* — so a standalone sub-assembly run can
   evaluate the same check list without the absent parts.

---

## 10. Referenced values — where a limit's number came from

Every payoff in the dogfood came from a human supplying an external reference (ISO 15's
22 mm, the NEMA bolt pattern). A limit is only as good as where its number came from, and
`Referenced` is how a contract records where that was: a float subclass that IS its value
— it compares, renders and serialises as a plain number — and additionally carries a
citation, conventionally `{"standard", "subject", "field"}`.

```python
from partspec.refs import iso15

seat = iso15.bearing(608)
p.hole_diameter(seat.od, tol=0.05)     # the check records source: ISO 15 / 608 / od
p.volume(min=1000.0)                    # a bare literal records nothing
```

The seven bound-carrying methods (`param`, `envelope`, `volume`, `area`,
`hole_diameter`, `bolt_circle`, `fillet_radius`) record `source: {field: citation}` on the
check when a `Referenced` reaches their bounds (`SPEC-report.md` §7.1) — the report states
not just what was claimed but on whose authority. Region and shell dimensions do not yet
carry attribution: their values pass through geometric validation that normalises to plain
floats, and a citation silently dropped is worse documented as coverage than implied.
Three rules:

1. **Attribution is additive, never required.** Bare literals behave exactly as before.
2. **Arithmetic sheds it.** `seat.od + 0.1` is a plain float: the derived number is the
   author's, not the standard's, and carrying a citation across an operation the cited
   document never performed would launder authority. (#50 builds the warning channel on
   this axis: a run whose every dimensional limit is unattributed will say so.)
3. **A citation locates, it does not reproduce.** `{"standard": "ISO 15", "subject":
   "608", "field": "outside_diameter"}` is enough to find the number; the tables never
   carry a standard's text.

### 10.1 Scope policy for `partspec.refs`

In scope: **dimensional interface facts** that are widely published and independently
verifiable — boundary dimensions, bolt patterns, envelope sizes — as pure stdlib data,
**shipped in the wheel**: tables this small carry no dependency and no meaningful size,
and an extra would put an import error between an agent and the numbers.
Out of scope: reproducing any standard's text, figures, or tolerancing tables, and any
value not verifiable from public manufacturer documentation. An unknown designation is a
`ContractError` naming what the table does carry — a table must not guess.

---

## 11. Contract fragments — an interface standard as an import

A fragment is a plain function that declares a mechanical interface's checks onto a part:

```python
from partspec.refs import iso15, nema17

nema17.mount(p)            # nema17:pilot + nema17:bolt_circle, pattern cited
iso15.seat(p, 608)         # iso15:608:seat, nominal cited
```

No new machinery — a fragment is ordinary contract authoring, factored. Three rules:

1. **A fragment declares checks and nothing else.** No geometry, no measuring the part,
   and no checks invented from measurements — the §6 auto-generation ban applies to
   fragments exactly as to tools. A fragment's defaults are declarations the caller
   adopts, the same way a factory's defaults are the master design (§2).
2. **Ids are namespaced** (`nema17:pilot`, `iso15:608:seat`), so two *different* fragments
   never collide, a collision with the author's own checks is loud (§4's duplicate-id
   error), and `diff` joins stably across runs. Calling the *same* fragment twice needs a
   distinct `instance=` per call — and because `hole_diameter` counts the whole part (no
   selectors, §8), per-part count arguments (`pilot_count`, `count`) state the total. A
   fragment MUST declare atomically: an invalid argument raises before any check lands,
   so a corrected retry never collides with a failed attempt's leavings.
3. **The standard's numbers carry the citation; the designer's stay theirs.** A pattern
   dimension is `Referenced`; a clearance diameter is an argument the caller owns. Where
   a table *derives* a value (NEMA 17's hole square from the standard's stated pitch
   circle), the derivation is stated in the citation's `note` — a table may derive and say
   so, while a call site deriving silently owns the result (§10 rule 2). Get the direction
   right: the first cut of the NEMA table derived the circle from the catalogue square and
   attributed the square to the standard, 25.6 µm off the AJ dimension the document states
   directly — the review caught it against the standard's own text, and the table now
   converts what the document says, inch figures in every note.
