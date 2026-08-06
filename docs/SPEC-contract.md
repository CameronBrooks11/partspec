# SPEC — the `partspec` contract

**Status:** draft 1 · 2026-08-02
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

## 4. Check vocabulary — closed for v0

`SPEC-report.md` §7.1 declares `kind` an open vocabulary so the report format never needs
revising when a check is added. **This document closes it for v0.**

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
| `p.volume(min=, max=)` | `volume` | scalar, `mm3` | both |
| `p.area(min=, max=)` | `area` | scalar, `mm2` | both |
| `p.topology(faces=, edges=, vertices=)` | `topology` | vector, `count`, exact | **occt only** |

`builds` is **implicit and always present**: every part gets it, and it fails if the engine
exits non-zero or emits no artifact. It is the one check an author cannot forget, and it is
why a contract with no declared checks still reports `empty` rather than crashing.

### 4.2.2 `topology` — the check that makes the tiers visible

Every other v0 kind maps to a primitive both backends declare. `topology` is the exception,
deliberately: on the OCCT tier it compares real modelled counts, and on the mesh tier it
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

---

## 6. The vacuous-green guard

A `Part` with no declared checks beyond the implicit `builds` produces `verdict: "empty"`
and exit `3` (`SPEC-report.md` §6). The CLI MUST additionally emit a one-line warning
naming the part, because `empty` is the single most likely output when an agent does not
know what to assert, and a silent exit `3` in a batch is easy to miss.

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
