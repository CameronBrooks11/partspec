# Dogfood results

Written in the `scadman-dogfood` house style: numbered findings, root cause, and — where
one exists — a validation-payoff proof showing a check predicted a real failure.

**Runs:** 2026-08-03, 2026-08-05 · partspec 0.1.0 · OpenSCAD **2026.08.01** (pinned by
`run-batch.sh`; F13 compares against 2021.01) · build123d 0.11.1 · CadQuery 2.8.0

---

## Population

| part | source | verdict | checks |
|---|---|---|---|
| `bayonet-lock` | `bayonet-lock-scad`, `half="lock"` | PASS | 11 |
| `bayonet-pin` | `bayonet-lock-scad`, `half="pin"` | PASS | 11 |
| `example-spacer` | `partspec/examples/spacer` | PASS | 8 |
| `gridfinity-box-2x1x3` | **cq-gridfinity** (community, CadQuery) | PASS | 8 |
| `pillow-block` | own build123d model | PASS | 10 |
| `gridfinity-2x1x3-cadquery` | **cq-gridfinity** (community) | PASS | 5 |
| `gridfinity-2x1x3-openscad` | **gridfinity-rebuilt-openscad** (community) | **FAIL** | 5 |
| `gridfinity-2x1x3-openscad-cgal` | same source, CGAL backend | PASS | 5 |
| `bevel-gear-11t` | **most-scad-libraries** (no asserts) | **FAIL** on 2026.08.01, **PASS** on 2021.01 | 6 |
| `gridfinity-2x1x3-openscad-unguarded` | same source, no `watertight` claim | **INCOMPLETE** (F14 regression) | 5 |
| `nema17-plate-slot6` | **most-scad-libraries** (no asserts) | PASS | 5 |
| `nema17-plate-slot8` | same source, one design edit | **FAIL** (F15 regression) | 5 |
| `bearing-608` | **most-scad-libraries**, vs ISO 15 | **FAIL** (F16) | 6 |

`./run-batch.sh` drives all 15 targets: 0 unexpected failures, 7 expected ones each with a
recorded cause.

Three deliberately-invalid parameterisations (`broken.py`) all FAIL with exit 1, each
naming the operands that caused it.

---

## F1 — The subject was already defended, so this run proves less than it looks

**Status:** ⚠️ finding, not a payoff.

`bayonet-lock-scad` contains **12 `assert()` statements**. Feeding it
`shell_thickness=1.0` with `pin_radius=1.0, allowance=0.2`, OpenSCAD itself reports:

```
ERROR: Assertion '...((pin_radius + (allowance / 2)) <= shell_thickness))' failed:
"bayonet: shell_thickness must be >= pin_radius + allowance/2 (1.1), got: 1"
```

and **exits 1 writing no STL**. So partspec's `requires` checks on this part are
**redundant with protection the library already had**, and this run does not demonstrate
that the tool catches anything OpenSCAD would miss.

That has to be said plainly, because the plan's own risk table predicted it: *"if every
contract passes first try, the project has proved nothing."* It did, and it hasn't.

**What partspec still adds here, without overclaiming:**

1. The rules move from *inside the `.scad`* — invisible without running the engine, and
   unusable by any other engine — to **declared data in a contract**. The same contract
   would apply unchanged to a build123d reimplementation, which is the substitutability
   claim the whole design rests on.
2. They are enforced **before the engine runs**, so an invalid parameterisation costs no
   render.
3. **The geometry checks are not redundant.** Nothing in the library asserts watertight,
   solid count, or envelope. Those three are new protection.

**What it does not add here:** better failure messages. OpenSCAD's assert output on this
library is genuinely good — it names the rule, the computed value and the offending input.

**Root cause of the weak result:** subject selection. `bayonet-lock-scad` is Cameron's own
recently-rewritten library and is unusually disciplined. It is the *best*-defended OpenSCAD
code in the corpus, which makes it the *worst* choice for showing what the tool is for.

**Action:** the next dogfood subject must be a library with **no asserts**. Candidates from
`~/repos_fast/most-scad-libraries` — `NEMA17.scad`, `bearings.scad`, `hotends.scad` — none
of which validate their inputs. That is the population partspec is actually for, and it is
the majority.

---

## F2 — Relative source paths resolved against the CWD

**Status:** ✅ fixed during the run.

First contract run failed with `source not found: spacer.scad` despite the `.scad` sitting
beside the contract. `openscad("spacer.scad")` was resolved against the process working
directory, so a contract worked or failed depending on the shell's history.

**Fix:** `target._anchor` resolves a relative source against the contract file's directory;
absolute paths are left alone. Regression tests cover both.

Worth noting because it is the same class of defect the tool exists to prevent — behaviour
depending on invisible ambient state.

---

## F3 — The implicit `builds` check defeated the vacuous-green guard

**Status:** ✅ fixed during the run.

A contract declaring **no checks at all** exited **0 (PASS)**, not 3 (EMPTY). Cause:
partspec adds an implicit `builds` check, so `counts.total` was 1 and the emptiness test
passed.

The tool had defeated its own most important guard — the exact failure named in
`SPEC-report.md` §1.1 and in `SPEC-contract.md` §6, which had already specified that
emptiness is tested against checks *"beyond the implicit `builds`"*. The spec was right; the
implementation had missed it.

**Fix:** `Report.verdict` excludes `Report.IMPLICIT_KINDS` from the emptiness test.

**Before / after:**

| contract | before | after |
|---|---|---|
| no declared checks | `PASS`, exit 0 | `EMPTY`, exit 3 |
| declared checks, all pass | `PASS`, exit 0 | `PASS`, exit 0 |

This is the most valuable thing the run produced, and it was found by trying to make the
tool lie rather than by trying to make it work.

---

## F4 — `distinct_normals` matched CGAL on a real part

**Status:** ℹ️ corroboration.

The example spacer (a plate with a `$fn=64` bore) reports `distinct_normals: 70` — 64 bore
facets plus 6 plate faces. That is exactly the coplanar-facet count CGAL reports for the
same shape, independently supporting D16's claim that counting distinct normals is an
adequate substitute for the scipy-dependent facet grouping.

Not proof: they diverge on non-convex parts where disjoint coplanar regions share a normal.
But on the first real part they agree.

---

## F5 — The OCP packaging landmine fired, and broke CadQuery outright

**Status:** ✅ fixed. The most serious finding so far.

D14 recorded that `cadquery-ocp` and `cadquery-ocp-novtk` both install a top-level `OCP/`
package with no conflict detection. Adding the OCCT extras made it happen:

```
$ uv sync --all-extras
$ python -c "import cadquery"
ImportError: cannot import name 'IVtkOCC_Shape' from 'OCP.IVtkOCC'
```

Both wheels resolved to 7.9.3.1.1 and both ship `OCP/` — 326 files vs 322 — and novtk
landed last, stripping the four VTK modules CadQuery needs. **CadQuery could not import at
all.** Nothing warned.

Worth noting the earlier spike that produced D3 installed both in a fresh venv and worked.
That was luck about resolution order, not a property of the packages. The conclusion "CadQuery
is nearly free" is still true *at the API level* — adoption really is a handle rewrap — but
the **packaging is hostile** and D3 should be read with that qualification.

**Fix**, in `pyproject.toml`:

```toml
[tool.uv]
override-dependencies = ["cadquery-ocp-novtk ; sys_platform == 'never'"]
```

The marker never matches, dropping novtk from resolution and leaving the VTK-enabled build
as sole provider. It is a superset, so build123d is unaffected.

**Second-order trap:** uninstalling novtk *deleted co-owned `OCP/` files*, breaking
build123d in turn (`ModuleNotFoundError: No module named 'OCP.Standard'`). Recovery needed
`uv sync --reinstall-package cadquery-ocp`. Co-ownership cuts both ways, and `just ocp-guard`
now passes only with exactly one provider.

---

## F6 — A bug I had already documented and then wrote anyway

**Status:** ✅ fixed.

`SPEC-backend.md` §4 states that build123d exposes `is_valid` as a **property** while
CadQuery exposes `isValid()` as a **method**, and names that as a reason the adopt shim
exists. The OCCT backend then called `a.is_valid()`, which raises
`TypeError: 'bool' object is not callable`.

It was caught only because an adjacent test touched the same attribute — no test covered
`backend.is_valid` directly. Now one does.

Writing the hazard down does not prevent the hazard.

---

## F7 — The naive Euler formula is wrong on a BREP

**Status:** ✅ handled.

Genus on the OCCT tier looked like `V - E + F`. Measured, that reports a box with a
**through-hole as genus 0** and a box with a **blind hole as genus -1**. Cause: OCCT faces
carry inner wires, so a face with a hole is an annulus, not a disc.

The Euler-Poincare form including wires is correct:

    G = S - (V - E + 2F - W) / 2

Verified against a box (0), one and two through-holes (1, 2), a blind hole (0) and a tube
(1) — and on the real pillow block, which returns **genus 5** for one bearing bore plus four
bolt holes. A regression test pins the naive formula's wrong answer so a future
simplification fails loudly.

---

## F8 — Community CAD code is scripts and pinned libraries, not callables

**Status:** ℹ️ design friction, accepted.

Two distinct problems surveying real community models:

1. **Version fragility.** `Ruudjhuu/gridfinity_build123d` (96★, MIT) does not import on
   build123d 0.11.1 — `ShapePredicate` no longer exists. A community model is pinned to the
   build123d of its writing.
2. **Shape.** `gumyr/build123d`'s 66 examples are *scripts* with module-level constants and
   `from ocp_vscode import show`, not parameterised functions. So is most OpenSCAD.

partspec calls a model as `method(**params)` — deliberately dumb, with no signature
inspection. In practice that means **a real contract usually ships a three-line adapter**,
as `parts/gridfinity/model_cq.py` does for cq-gridfinity's class constructor.

That is the right trade — a tool that guessed the calling convention would be worse — but it
is friction worth stating rather than discovering.

---

## F9 — A community model checked against an external standard

**Status:** ✅ the strongest validation so far.

`cq-gridfinity`'s `GridfinityBox(2,1,3)` (community, CadQuery, MIT) was contracted against
the **Gridfinity standard's own numbers** rather than against measurements copied back from
the tool: 42.0 mm pitch, 0.5 mm clearance, 7.0 mm height units.

    envelope measured [83.5, 41.5, 24.8]
    expected 42*2 - 0.5 = 83.5,  42*1 - 0.5 = 41.5

It passes. Re-contracting the same part against a 40 mm pitch **fails**, so the check is
load-bearing rather than decorative.

This is the first check in the project written from a requirement that existed before the
part was measured — which is the thing F1 said was missing.

The report also records `adopted_via: "wrapped"`, the D3 event, and `geometry: {}` because
the OCCT tier has no tessellation to describe.

---

## F10 — OpenSCAD's default backend produced a non-manifold mesh, and said it was manifold

**Status:** 🔴 **the validation payoff F1 said was missing.**

The differential test (F11) flagged `watertight` as diverging between the two gridfinity
implementations. Investigating gave a clean, isolated result — same source, same parameters,
only the OpenSCAD render backend varied:

| backend | triangles | watertight | boundary edges | non-manifold edges | volume |
|---|---|---|---|---|---|
| **Manifold** (the default) | 10,022 | **False** | 0 | **4** | 32341.838 |
| CGAL | 10,688 | True | 0 | 0 | 32341.841 |

The 4 offending edges are each used by **four** faces, all at z = 19.8 — two shells touching
along a plane. That is arithmetic on the face-per-edge count, not a heuristic, and
`manifold3d` independently agrees the topology is degenerate (it reports genus 8 for a shape
whose clean render is genus 0).

**What OpenSCAD reports about this:**

```
Top level object is a 3D object (manifold):
Status:     NoError
exit code:  0
--summary geometry:  { "facets": 10022, "simple": true, ... }
```

It says **manifold**. It says **`"simple": true`**. It exits 0. Every one of those is wrong.

This is D13's thesis proven on a real part, and proven *harder* than the case D13 was built
on. D13 was based on `--summary` **omitting** the validity key on degenerate input; this is
`--summary` **asserting a false one**. The rule "never let OpenSCAD self-report validity" is
not conservatism, it is necessary.

**Scope of the claim, stated carefully:** the defect is in the *rendered mesh*, on a
2,212-star library, in the **default configuration** of current OpenSCAD (2026.08.01). It is
not a design error in the library — the same source renders clean under CGAL. Whether a
given slicer would repair it is not something this run establishes.

**Consequence in the tool:** the render backend is now selectable
(`openscad(..., backend="CGAL")`) and recorded in the report as `engine.render_backend`,
because it changes the artifact rather than merely the speed of producing it.

---

## F11 — The differential test: one contract, two languages, agreement on what the standard fixes

**Status:** ✅ the substitutability proof.

`claims.py` states the Gridfinity requirements once — 42 mm pitch, 0.5 mm clearance, 7 mm
height units — and both contracts import it. No tool feature was needed; the contract is
Python, so sharing claims is a function (D6).

Against **CGAL**, the only remaining divergence is a legitimate design difference:

```
AGREE (3)
  builds        both pass
  solid_count   both pass  1
  watertight    both pass  True

DIVERGE (1)
  envelope: both pass, but measured
            A=[83.5000, 41.5000, 24.5479]  B=[83.5000, 41.5000, 24.8000]
```

**X and Y agree exactly** — 83.5 and 41.5, the standard's `42n − 0.5`, produced
independently by an OpenSCAD implementation and a CadQuery one. That is the claim "one
contract, evaluated identically wherever it can be" holding on real third-party code.

Z differs because the two handle the stacking lip and base differently, which the standard
does not fix. Note the shape of that finding: **both checks PASS and the measurements still
differ.** Nothing in a pass/fail view would show it. This is exactly what `SPEC-report.md`
§7.2 records measurements on pass for — "drift the boolean can't see" — and the first time
it has paid off.

`differential.py` exits non-zero on divergence, because a differential test that exits 0 on
disagreement is not a test.

---

## F12 — My own shared claim was wrong, and the tool caught it

**Status:** ✅ fixed. Worth recording because the error was mine, not the tool's.

`claims.py` originally asserted `genus(0)` with the comment *"an open tray has no
through-holes"*. True of cq-gridfinity. False of kennetek's, which enables **Gridfinity
Refined base holes by default** — 4 per grid unit, so a 2×1 bin measures **genus 8**.

Confirmed by re-rendering with `refined_holes=False`, which returns genus 0 and passes.

The base-hole style is a design choice the Gridfinity standard does not fix, so it never
belonged in claims shared across implementations. `genus` moved out of the shared set.

The general lesson for writing shared claims: assert only what the *specification* fixes,
not what the implementation you happened to look at first does.

---

## F13 — The same source silently produces a different part on a different OpenSCAD

**Status:** 🔴 **The F1 payoff, on the population F1 named — and stronger than asked for.**

F1's action was to test a library with **no asserts**. The corpus in
`~/repos_fast/most-scad-libraries` is that population and then some: **18 libraries, zero
`assert()` statements between them**. The bayonet library's 12 was the outlier.

`parametric_involute_gear_v5.0.scad` uses OpenSCAD's `assign()` construct, which was
deprecated and later **removed** from the language. Modern OpenSCAD ignores it — and
ignoring a module means *its children never render*. Those children are the `polyhedron()`
calls that cut the gear teeth.

Same source, same parameters, two installed OpenSCAD versions:

| version | `assign` warnings | triangles | volume mm³ | outer extents mm |
|---|---|---|---|---|
| **2021.01** (honours `assign`) | 0 | 648 | 44,463 | 71.8 × 72.5 |
| **2026.08.01** (ignores it) | 5 | 120 | 28,760 | **48.8 × 49.2** |

**Both exit 0. Both write clean, watertight, single-solid STLs.** The only signal is a
`WARNING: Ignoring unknown module 'assign'` buried in stderr among other output. The part is
**35% smaller in every planar dimension** and has lost its teeth — 48.8 mm is essentially the
pitch diameter, which is what a gear blank measures before the teeth are cut.

### The validation-payoff proof

The contract asserts involute gear geometry, derived from theory rather than measured off
any part:

```
outside pitch diameter = teeth * outside_circular_pitch / 180   = 61.1 mm
addendum               = pitch diameter / teeth / 2
outer diameter        ~= pitch diameter + 2 * addendum          = 72.2 mm
```

Then, with **the identical contract**:

| binary | `envelope` | verdict |
|---|---|---|
| `PARTSPEC_OPENSCAD=$(command -v openscad)` → 2021.01 | pass | **PASS** (6 checks) |
| default discovery → 2026.08.01 | **fail** | **FAIL** |

That is a controlled experiment with one variable. The contract is correct — it passes on
the version that renders correctly — and partspec catches a silent, version-dependent
geometry regression that neither OpenSCAD reports as an error.

This is what F1 asked for and did not get from the bayonet: **not a rule the library forgot
to assert, but a part that is quietly wrong and looks fine.** No `assert()` anywhere in the
library would have caught it, because the library's own source is unchanged and correct —
the language moved underneath it.

**Consequence in the tool:** `PARTSPEC_OPENSCAD` pins the binary. Deliberately an
environment variable rather than a contract field: which binary is installed is a property
of the *machine*, not of the design. The render backend is the opposite — a design choice —
so it lives in the contract. Both end up in the report either way.

### One hypothesis I had to abandon

The first read was "the teeth are dropped entirely, so normal count will not scale with
tooth count". It does scale (32 → 50 → 166 for 11/20/30 teeth), which killed that. The base
cone's faceting is itself driven by tooth count, so the scaling proved nothing either way.
The version comparison is what settled it, and it is the only test here that isolates a
single variable.

---

## F14 — partspec answered questions it could not answer, on a real part

**Status:** 🔴 **The tool's own thesis, violated in the tool.** Found by a probe, not by
reading the code. Fixed 2026-08-05.

The subject is F10's: kennetek gridfinity through OpenSCAD's default Manifold backend, the
mesh already known to carry 4 non-manifold edges. The contract declares `volume`,
`solid_count` and `genus` but **not** `watertight` — which is what an author who had never
read F10 would write.

```console
$ partspec check spec_scad_unguarded.py:bin_2x1x3
  ok   builds
  ok   volume
  ok   solid_count
  ok   genus

PASS: 4 pass
EXIT=0
```

Four green checks on a mesh partspec itself knows is not a closed solid. Not vacuous green —
the checks were declared and evaluated. This is **failure mode two, unsupported-as-pass**
(`SPEC-report.md` §1.1), in the tool built to prevent it.

Reduced to a cube with one face removed:

| quantity | reported | truth |
|---|---|---|
| `volume` | **500.0**, `exact` | undefined — an open shell encloses nothing |
| `genus` | **1**, `exact` | undefined — a through-hole that does not exist |
| `center_of_mass` | **(-2.5, 0, 0)**, `exact` | undefined — a point outside the material |

### Root cause 1 — a dependency raised its hand and nothing looked

manifold3d, handed that mesh, returns an object reporting:

```
status  : Error.NotManifold
is_empty: True
num_tri : 0
```

`.decompose()` on that empty, explicitly-errored object still returns a one-element list;
`.genus()` still returns 1. partspec read both without ever checking `status()`.

### Root cause 2 — two libraries, two different solids, one report

`volume` came from trimesh; `genus` and `solid_count` from manifold3d. They do not describe
the same geometry. On the **clean, watertight** CGAL render — same 5,330 vertices, none
displaced — manifold3d retriangulated **55 of 10,688 triangles**:

```
independent float64 divergence-theorem sum : 32341.840738   <- ground truth
trimesh                                    : 32341.840738
manifold3d                                 : 32367.150544   <- +25.31 mm3 (+0.078%)
```

So a single report carried measurements of two different solids, every one flagged `exact`.
Under D15 — *measure the artifact as authored and exported* — two of six geometry checks
described something the engine never exported.

### What the fix changed

Preconditions per quantity (`SPEC-backend.md` §5.1.1), each refusal naming the defect; genus
and body count computed directly over the exported triangles; any manifold3d object checked
for `status()` before being read. The same probe now:

```console
INCOMPLETE: 1 pass, 3 unsupported
  n/a  volume — volume is the integral over a closed surface; this mesh has 4 non-manifold edge(s)
  n/a  solid_count — this mesh has 4 non-manifold edge(s), where counting through the
       junction and counting across it give different answers
  n/a  genus — genus is defined for a closed surface; this mesh has 4 non-manifold edge(s)
EXIT=2
```

The real `spec_scad` contract went from `solid_count: pass` — a false green off manifold3d's
repair — to `unsupported` with a reason. Its verdict was already `fail` on `watertight`, so
no exit code moved; the report simply stopped carrying a false claim. **All 11 other targets
are unchanged**, which is the point: refusals landed only where the mesh was actually broken.

`spec_scad_unguarded.py` is kept as a permanent regression contract. If it ever exits 0
again, the central claim is false.

### Three things worth keeping

1. **The refusal has to be narrow.** `solid_count` is refused only for *non-manifold* edges,
   not for an open mesh, because an open mesh still determines its component count. Refusing
   an answerable question inflates `incomplete` and is its own way of not answering.
2. **Neither root cause was findable by reading.** Both took a deliberately broken mesh and
   an independent computation. 169 tests passed throughout — every one of them measured a
   mesh that was already sound.
3. **The mesh-only install is exercised nowhere.** scipy reaches this machine only through
   build123d/cadquery, and `just setup` installs all extras, so a mesh-tier dependency on
   scipy passes locally *and* in CI while breaking `pip install partspec[mesh]`. trimesh's
   `body_count` is exactly that. Now guarded by `just test-mesh-only`.

---

## F15 — One plausible design edit made the plate unmountable, silently

**Status:** 🟢 **Validation payoff, and the before/after table P6 was missing.** The earlier
payoff (F13) turned on an *engine version*. This one turns on a **design change**, which is
the case a user meets every day.

**Subject.** `motor_plate_NEMA17` from `most-scad-libraries` — the 18-library corpus with
zero `assert()` statements. A plate carrying a NEMA 17 motor: four mounting holes on a 31 mm
square plus a central pilot bore for the collar. Five holes through a plate is **genus 5**,
and that is checkable on the mesh tier with no feature recognition at all.

**The edit.** `l_slot` lengthens the mounting slots so the motor can shift to tension a belt
— exactly the number somebody bumps between revisions. The library places no bound on it.
Going from 6 mm to 8 mm:

| | `l_slot` = 6 | `l_slot` = 8 | moved? |
|---|---|---|---|
| `builds` | pass | pass | |
| `envelope` 42x42x4 | pass | pass | |
| `watertight` | pass | pass | |
| `solid_count` 1 | pass | pass | |
| **`genus` 5** | **pass** | **FAIL — measured 1** | ← |
| verdict / exit | PASS / 0 | **FAIL / 1** | |
| volume | 3438.52 mm³ | 3107.33 mm³ | −9.6% |

The plate still renders, still exits 0, is still watertight, is still one solid, and is still
exactly 42 x 42 x 4. Four of the five checks cannot tell the two apart. What happened is that
the slots reached the plate edge and stopped being holes: a hole that opens onto the boundary
is a notch, and the genus falls from 5 to 1. **The part can no longer hold a motor**, and the
only number that says so is the one describing its topology.

This is the failure mode visual review is worst at, because the result does not look broken —
open-ended slots look like a deliberate choice.

**Pushed further**, one parameter, five distinct states, every one of them exiting 0:

| `l_slot` | genus | solids | watertight | volume | what it actually is |
|---|---|---|---|---|---|
| 6 | 5 | 1 | yes | 3438.52 | correct |
| 7 | 5 | 1 | yes | 3270.52 | correct |
| 8 | **1** | 1 | yes | 3107.33 | slots breached the edge — unmountable |
| 12 | 1 | 1 | yes | 2535.27 | same, worse |
| 14 | *refused* | *refused* | **no** | *refused* | 2 non-manifold edges — pinched to a point |
| 16 | *refused* | **6** | yes | 2040.01 | fallen into six disconnected pieces |

Two things worth noting in the bottom rows. At 14 the D17 preconditions fire on a real
part — `volume`, `center_of_mass`, `solid_count` and `genus` all refuse, each naming the two
non-manifold edges, rather than returning the plausible numbers they could have computed. At
16 the refusal is *narrow* in exactly the way D17 argues for: `solid_count` still answers,
and it answers **6**, while `genus` declines with *"genus is defined per body; this part has
6 solids (check solid_count first, or split the part)"*. Over-refusing there would have
hidden the most legible symptom the part has.

**Also found, without measuring anything.** `NEMA17.scad` opens with a header comment giving
the motor's dimensions — `42.67mm square plate`, `22mm diameter shaft collar` — and ten lines
later declares `l_NEMA17 = 42` and `d_NEMA17_collar = 28`. The file disagrees with itself by
6 mm about the part it is named for. Nothing notices, because nothing in the corpus checks
anything.

---

## F16 — A part named for a standard, 0.5 mm off that standard, with no comment saying so

**Status:** 🟢 payoff, on the most standardised object in the corpus.

A 608 bearing is 22 mm outside diameter, 8 mm bore, 7 mm wide, and ISO 492 holds the outside
diameter to 0 / −0.008 mm. `bearings.scad` declares:

```scad
od_608 = 22.5;
id_608 = 8.4;
h_608  = 7;
```

Checked against ISO 15's numbers with a deliberately generous ±0.1 mm band:

| check | claim | measured | |
|---|---|---|---|
| `envelope` | 22.0 x 22.0 x 7.0 ±0.1 | **22.5 x 22.5 x 7.0** | FAIL |
| `volume` | 2309.07 mm³ ±1% | **2394.84 mm³** | FAIL |
| `watertight` / `solid_count` / `genus` | 1 solid, 1 handle | as claimed | pass |

Read charitably these are print clearances for a pocket that *holds* a 608. But the module is
`bearing(608)` and the constants are named for the bearing, so a model that uses it as the
part gets a 22.5 mm bearing. **The width gives the game away**: it is exactly nominal. A
pocket needs axial clearance too. The allowance was applied where somebody was thinking about
fit and omitted where they were not, which is precisely the kind of inconsistency no reviewer
finds by looking at a picture of a ring.

`envelope` alone only sees the outside diameter. The bore carries its own undeclared 0.4 mm,
and `volume` is the only v0 quantity on this tier that can feel it — neither check localises
the divergence, but together they bracket it. `hole_diameter` would say it directly and is
BREP-only (POST-V0 §4).

`$fn=180` is pinned in the contract so the polygon approximation cannot be confused for the
finding: at 180 facets the error is ~0.003 mm against a 0.5 mm divergence. Under D15 the
resolution is part of the question, so it has to be part of the contract.

**Same pattern as F15's header/code mismatch, in a different library by a different author:
a clearance allowance baked into a constant named for a nominal dimension.** Two independent
instances makes it a property of the corpus rather than one author's slip.

---

## F17 — The prose drifted from the reports, and the reports were right

**Status:** ⚠️ small, and it argues for the whole design.

This file's header claimed the runs used **OpenSCAD 2021.01**. Every OpenSCAD report in the
tree recorded **2026.08.01**. The reports were correct.

Root cause was in partspec: `find_executable()` preferred a nightly AppImage at a hardcoded
path in `$HOME` ahead of `PATH`, so `which openscad` said 2021.01 and every render used
2026.08.01. Fixed — the rule is now the pin, then `PATH`, nothing else — and `run-batch.sh`
now exports `PARTSPEC_OPENSCAD` explicitly and prints the version it resolved.

Worth recording because of what it demonstrates rather than its size. The engine version is
the one input F13 proved can change the part outright, and the hand-written summary of these
runs was wrong about it for two days. The machine-readable field never was. That is the
argument for `SPEC-report.md` in one incident: **a report nobody has to remember to update.**

---

## Next

1. ~~Re-run F1 against an unasserted library.~~ **Done — see F13.** The corpus has 18
   libraries and zero asserts, and the gear library silently loses its teeth on modern
   OpenSCAD. Contract passes on 2021.01, fails on 2026.08.01, one variable changed.
2. ~~`parametric-sensor-manifold`~~ — dropped: it is just the build123d template, not a
   real part.
3. ~~A before/after regression table from a real *design* change rather than a version
   change.~~ **Done — see F15.** One parameter, `l_slot` 6 -> 8 mm, and the plate stops being
   able to hold a motor while four of its five checks report no difference.
4. Nothing here exercises `approximate`, as predicted: no v0 check can produce it.
5. **Still open: a part where `incomplete` is the right long-term answer.** Every
   `incomplete` so far has been a gap to close, which is why `--allow-incomplete` stays
   unbuilt (POST-V0 section 7). If one never turns up, that is itself the answer.
6. **Still open: a second author's corpus.** F15 and F16 are two libraries, but from one
   collection. The pattern they share — an allowance baked into a constant named for a
   nominal dimension — is worth confirming somewhere with different provenance.

## F18 — a `-D` that binds nothing is accepted and dropped

**Found by:** partspec #9's guard, on its first run against this corpus (2026-08-06).

All four gridfinity OpenSCAD contracts passed `style_lip=0` to
`gridfinity-rebuilt-bins.scad`. That variable is **not** declared there — it lives in
the sibling entry point `gridfinity-rebuilt-lite.scad`. OpenSCAD accepts a `-D` naming
no top-level variable and silently discards it, so:

- every run built a bin **with** a stacking lip, which is not what the contract asked for;
- the report listed `style_lip: 0` under `params`, positively asserting a value the
  geometry never saw;
- two of the four rows (`spec_scad_cgal`, `spec_scad_noholes`) were **exit 0**, green.

The parameter has been removed from all four contracts. The geometry does not change,
because it never took effect — what changes is that the report no longer claims it did.

This is the third finding of the same shape as F13 and F14: the tool exits 0, the mesh is
clean, and the artifact describes a part that was not built. It is also the first finding
produced by a partspec guard rather than by a human reading output.
