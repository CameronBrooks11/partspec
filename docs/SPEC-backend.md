# SPEC — the `partspec` geometry backend

**Status:** draft 2 · 2026-08-03
**Scope:** the protocol a geometry backend implements, the two v0 implementations, and how
`exactness`, `bounds` and capability gating are determined.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** D3 (two backends), D13 (ignore `--summary`), D14 (trimesh + manifold3d),
D15 (measurand), `investigations/03` §2, `investigations/04`.

---

## 1. Why a protocol at all

Investigation 03 established the finding this whole design rests on:

> cad-khana's build123d coupling is **pervasive by type but shallow by behaviour** — twelve
> geometry primitives carry its entire diagnostic vocabulary, and ~2,000 LOC of the valuable
> logic is already engine-independent.

So engine neutrality is not a rewrite. It is a protocol over a dozen methods, plus own
value types replacing five leaked build123d types.

**Two backends, not three** (D3): one OCCT backend serves build123d *and* CadQuery via a
`.wrapped` adopt shim; the only genuinely separate backend is mesh, for OpenSCAD.

---

## 2. Value types

Own types, so no engine type appears in the check layer.

```python
@dataclass(frozen=True)
class Vec3:   x: float; y: float; z: float

@dataclass(frozen=True)
class BBox:   lo: Vec3; hi: Vec3          # .size -> Vec3

@dataclass(frozen=True)
class Measured:                            # what every primitive returns
    value: float | tuple[float, ...]
    exact: bool
    bounds: tuple[float, float] | tuple[tuple[float, float], ...] | None = None
```

`Transform` and `Plane` are **deliberately absent in v0**. They are needed for placement and
datum targets, which are assembly concerns (D11). Adding them later is additive.

`Measured` is the protocol's whole answer to `SPEC-report.md` §2: a backend never returns a
bare float, so a caller cannot accidentally lose provenance.

---

## 3. The protocol

```python
class GeometryBackend(Protocol):
    kind: str          # "occt" | "mesh"
    engine: str        # "build123d" | "cadquery" | "openscad"
    engine_version: str

    # --- lifecycle ---
    def build(self, source: SourceRef, params: dict) -> Artifact | BuildError: ...
    def provenance(self, a) -> dict: ...    # -> report.geometry block

    # --- the twelve primitives (investigation 03 §2) ---
    def bbox(self, a) -> Measured: ...
    def volume(self, a) -> Measured: ...
    def area(self, a) -> Measured: ...
    def center_of_mass(self, a) -> Measured: ...
    def is_valid(self, a) -> Measured: ...
    def watertight(self, a) -> Measured: ...
    def solid_count(self, a) -> Measured: ...
    def genus(self, a) -> Measured: ...
    def topology_counts(self, a) -> Counts | Unsupported: ...
    def min_distance(self, a, b) -> Measured | Unsupported: ...
    def intersect_volume(self, a, b) -> Measured | Unsupported: ...
    def triangles(self, a) -> Tris: ...
    def raycast(self, a, origin, direction) -> list[Vec3] | Unsupported: ...

    # --- honesty ---
    def capabilities(self) -> frozenset[str]: ...
```

`min_distance` / `intersect_volume` / `raycast` are present because they are part of the
twelve and the mesh backend implements them cheaply; **no v0 check calls them** (they serve
`clearance` / `interference` / `min_wall`, all post-v0 per `SPEC-contract.md` §4.3). They
are specified now so the protocol does not change when those land.

### 3.1 `Unsupported` is a return value, not an exception

A backend that cannot answer returns `Unsupported(reason, requires)`. It MUST NOT raise, and
it MUST NOT return a plausible-looking number.

This is the protocol-level enforcement of `SPEC-report.md` §3.2. It is also the exact point
at which PartCAD went wrong (D12): by normalizing an OpenSCAD mesh into a faceted
`TopoDS_Shape`, its topology queries *run* and return triangle counts dressed as
engineering topology. **A backend MUST NOT satisfy a query by reconstructing an entity its
representation does not contain.**

### 3.2 Capabilities are declared, not discovered

`capabilities()` returns the set of primitives the backend can answer *at all*. The check
layer consults it before dispatch, so an `unsupported` result is produced without building
anything the backend cannot use. Per-call `Unsupported` remains necessary for the
geometry-dependent cases — capability is static, exactness is not (§5).

---

## 4. The OCCT backend

Serves **build123d and CadQuery from one implementation**, verified (D3):

```
both .wrapped are TopoDS_Shape from the SAME OCP module
bd.Solid(cq_shape.wrapped)  ->  volume 6000.0, is_valid True, faces 6
distance_to (expect 90) -> 90.0    intersection volume (expect 6000) -> 6000.0
```

**Adoption happens once, at the front door.** A CadQuery result enters as
`bd.Solid(shape.wrapped)`; everything downstream is build123d. There is no second code path,
which is why CadQuery costs an afternoon rather than a parallel backend.

The shim also normalizes the small API divergences so they never reach the check layer —
notably build123d's `is_valid` is a **property** while CadQuery's `isValid()` is a method.

Every quantity is `exact=True` on this tier. `bounds` is `None` throughout.

### 4.1 Dependency pinning — mandatory

`cadquery-ocp` and `cadquery-ocp-novtk` **both install a top-level `OCP/` package, and
pip/uv do not detect the conflict** — both install and one silently clobbers the other. Our
spike worked only because the versions matched. PartCAD hits this in production and
re-asserts the VTK-enabled OCP last, after build123d.

The project MUST pin one OCP explicitly and commit the lockfile. A CI job SHOULD assert that
exactly one `OCP/` provider is installed, because the failure mode is silent.

---

## 5. The mesh backend

OpenSCAD → binary STL → trimesh/manifold3d (D13, D14).

1. Render: `openscad --export-format binstl -o <tmp>.stl -D name=value ... <source>`.
   `binstl` specifically — lib3mf cannot read ASCII STL, and OpenSCAD 2021.01's STL default
   *is* ASCII.
2. Load with `trimesh.load_mesh()` — **explicitly**, never `load()`, so a multi-body file
   cannot silently degrade into a different type with different semantics.
3. Measure the mesh. **Never parse `--summary`** (D13): it omits volume and area entirely,
   its `facets` field means different things per backend, and — the reason it is banned — on
   invalid geometry it emits JSON with the validity key **absent** while exiting 0, so
   `.get("simple", True)` silently passes a broken part.

### 5.1 Exactness under D15 — and why this is simpler than it looked

D15 fixes the measurand as *the artifact as authored and exported*. **A mesh is a
polyhedron.** Its volume, area, centre of mass, bounding box, watertightness, solid count
and genus are computed exactly from its triangles. There is no smooth ideal being
approximated, so there is no tessellation error to bound.

This dissolves the question the review raised — *"how does a backend know whether its input
is polyhedral or a tessellated curve?"* Under D15 the backend does not need to know, because
the distinction is not about measurement accuracy. It is about **design identity**, and it
is reported through `geometry.facets` and `geometry.triangles` rather than through error
bars.

### 5.2 The one real bound: float32 quantization

The single rigorously derivable inexactness on this tier, and the only source of
`approximate` the mesh backend may legitimately produce:

Binary STL stores coordinates as **float32**. The exported artifact therefore differs from
what the engine computed by at most a half-ulp per coordinate:

```
ε_coord(v) = |v| · 2⁻²⁴  ≈  5.96e-8 · |v|
```

Measured: `cube([120.3, 80.7, 40.1])` round-trips as `120.30000305, 80.69999695,
40.09999847` — deltas of ±3.05e-6 mm, which is **three times** an absolute `1e-6` and is why
`SPEC-report.md` §3.3's epsilon carries a relative term.

Propagation:

- **bbox** — directly: each extent inherits the quantization of its two bounding
  coordinates. Trivially computable, and the honest source of `bounds` if a bbox check is
  ever reported `approximate` rather than absorbed by the epsilon.
- **volume / area** — a first-order bound follows from the coordinate perturbation, of order
  `1e-7` relative. Real, computable, and far below any engineering tolerance.
- **watertight / solid_count / genus** — topological and therefore **unaffected**;
  quantization cannot open a closed mesh at these magnitudes. Report `exact=True`.

Backends SHOULD report bbox, volume and area as `exact=True` when the resulting interval is
narrower than `SPEC-report.md` §3.3's epsilon, because an interval below the comparison
tolerance carries no information and would produce `approximate` statuses that mean nothing.
This is the one place a backend is permitted to collapse a bound, and it MUST be the
epsilon that justifies it, never convenience.

### 5.3 Known gaps on this tier

- **Self-intersection is not available.** Neither trimesh nor manifold3d detects it, and the
  alternatives are GPL (libigl/CGAL) or heavyweight (pymeshlab). Accepted per D14; report
  `Unsupported`.
- **Topology counts are meaningless** and MUST return `Unsupported(requires="occt")`. A
  triangle count is not a face count, and returning one is the PartCAD failure.
- **`min_distance` is exact for polyhedra** via `manifold3d.min_gap` (verified: returned
  exactly 7.5). Under D15 that is simply exact — the polyhedron is the part.

### 5.4 OpenSCAD version floor

D13's consequence: because `--summary` is never read, **2021.01 and current nightlies are
interchangeable** for our purposes and no nightly install is a v0 prerequisite. The backend
MUST record `engine_version` in the report regardless, since a Manifold-vs-CGAL backend
change alters triangulation and therefore `geometry.triangles`.

---

## 6. Provenance

`provenance(a)` populates `report.geometry`. Mesh tier emits `triangles` and
`distinct_normals`; OCCT tier emits neither (`SPEC-report.md` §7.1) and MAY emit nothing at
all in v0.

`distinct_normals` counts distinct face normals — retriangulation-invariant and tracking
`$fn` one-to-one (`$fn=n` on a cylinder yields `n+2`; a cube yields 6). `triangles` is the
drift explainer, because chord error scales with edge length. Both, not either.

**Not** trimesh's `.facets` coplanar grouping, which requires `scipy` or `networkx` — see
D16. Likewise `solid_count` uses `manifold3d.decompose()` rather than trimesh's
`body_count`, which routes through the same graph machinery and raises `ImportError`
without it.

---

## 7. Testing obligation

The protocol is only worth its cost if both backends genuinely agree where they claim to.

**A differential test MUST exist**: the same part, specified once, implemented in OpenSCAD
and in build123d, checked against one contract, with the report's `checks[]` compared
field-by-field excluding `engine` and `geometry`. Gridfinity is the ready-made subject —
implementations exist in all three engines under MIT
(`kennetek/gridfinity-rebuilt-openscad`, `michaelgale/cq-gridfinity`,
`Ruudjhuu/gridfinity_build123d`), so any divergence is a tool bug rather than a design
difference.

This is the substitutability proof. Without it, "one contract, evaluated identically
wherever it can be" is an assertion rather than a property.
