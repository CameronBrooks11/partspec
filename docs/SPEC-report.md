# SPEC — the `partspec` report

**Status:** draft 13 · 2026-08-09 · §10 rewritten (`approximate` is live), §2.2 gains
`bool` and `rel`, the example's phantom `timestamp` removed; the render verb leaves
`render.json` on disk (its
payload with `renders` relativized, §8 rule 4) and every render records `render_bbox`
(`{min, max}` mm) — the framing scales with the part, so the bbox is the scale witness
`vdiff` (#21) compares when the pixels cannot; draft 11 added `render --section` (#19):
the payload may carry a `section_<plane>` view and a `section` block; draft 10 made `render` cover the OCCT tier
(#18): the verb accepts every engine, its OCCT payloads and reports carry
`render_tessellation`, and the Scope's engine-block subset is now the OpenSCAD case only;
draft 9 extended the identity-prefix scope to `render` (#103);
draft 8 added `expectation` (the claims pin), `invocation.timeout_s`, the exit-130 row,
batch coverage of `64` (reversing the earlier no-aggregation theory), the
model-cache-invalidation MUST, and the `measure` identity-prefix scope; draft 7 added
`checks[].components` / `region` / `hole` / `source`, run-level `attribution`, render
references, and the §8.3 closure reversal
**Scope:** the JSON artifact `partspec check` emits, and the process exit code that
accompanies it. `partspec measure` and `partspec render` emit sibling payloads that MUST
share the identity prefix — `schema_version`, `tool`, `part`, `engine`, `params`, built
by the same code (#47, #103) — followed by `geometry` for `measure` and by `renders` for
`render`, which carries no `geometry` block. `render`'s engine block states what ran
(#18): on the OCCT tier the part builds through the same backend `check` uses, so the
block is §7's in full — `backend` included — and the payload carries
`render_tessellation` after `renders` (`{tolerance_mm, triangles}`: under D15 the
tessellation is what was shown, so its quality rides with the images). On OpenSCAD the
engine draws its own geometry and no measurement tier runs, so the block is the subset
`kind`, `version`, `render_backend`, `method`, `param_mode` (`backend` would name a tier
that did not run; `adopted_via` could only ever be null there) and there is no
tessellation record. With `--section` (#19) the payload's `renders` additionally carries
`section_<plane>` and a `section` block follows — `{plane, offset_mm, cut_triangles}`:
the offset is always the RESOLVED value (the bounding-box centre when none was given,
never left implicit), and `cut_triangles` counts the facets lying on the plane, so zero
states the plane passed only through voids rather than looking like an uncut render. A
plane outside the part's span on its axis MUST be refused (a section that misses the
part renders an image that looks fine — the documented failure), and the refusal names
the span. `measure --out` names where the engine's build artifact goes, and only the
OpenSCAD tier produces one (#204): where `--out` was passed and the tier exports nothing,
the payload MUST carry an `artifact` entry — `{requested, written: false, reason}` — and
stderr MUST say the same, because a request the run could not fulfil must not read as one
it did (§1.1), and a fact living only on stderr is invisible to the machine this payload
is for. The two spellings of that request differ in the exit code alone: a *filename*
destination is refused (§6.2's `64`, the caller named a path they will go looking for),
while a *directory* keeps `0`, because the measurement itself succeeded and is the verb's
product. `check --out` is out of scope here — it writes `report.json` into that directory
on every tier. On any failure after the target resolves, both
MUST emit a JSON object carrying that identity plus `error`/`hint` — `renders` empty
rather than absent — so a consumer always learns which file and revision it was talking
about. A target that never resolves has no identity to emit: those failures are stderr +
exit code only (for `check`, the placeholder artifact covers that window; `measure` and
`render` write no artifact).
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** `DECISIONS.md` D5, D10, D13; [`notes/survey/04-kernel-capability.md`][survey-capability].

---

## 1. Why this document exists first

Per D5, the CLI verbs are not the contract. **The report schema plus the exit code is the
contract.** Everything else — the MCP layer, `diff`, CI annotations, a scorecard — is a
consumer of this artifact. If the report is right, an MCP server is a thin adapter; if it
is wrong, every consumer re-derives meaning from prose and the tool gets built twice.

So this is specified before any implementation.

### 1.1 The one property everything else serves

> **Silence must never read as success.**

Three distinct failure modes collapse into that sentence, and all three have been observed
in shipping tools:

- **Vacuous green** — cad-khana's own named anti-pattern: a module declaring no assertions
  exits 0 and writes `"assertions": []`. *"That is not a passing design; it is an unasked
  question, and an agent will read it as success."*
- **Unsupported-as-pass** — PartCAD normalizes an OpenSCAD mesh into a faceted
  `TopoDS_Shape`, so topology checks *run* and *return numbers* that mean nothing
  (`face_count` is a triangle count; there are no cylindrical faces to measure).
- **Approximate-as-pass** — an OpenSCAD `cylinder($fn=16)` is a genuine 16-sided prism.
  Fitting recovers the circumscribed radius (5.0000) while real bolt clearance is the
  apothem (4.9039), so `hole_diameter >= 10.0` passes at a reported Ø10.000 on a hole that
  clears Ø9.808 — **error always in the unsafe direction**.

A verification tool that reports any of these as green is worse than no tool, because it
converts an open question into a false assurance.

---

## 2. The measurement model

Every geometric quantity in a report is a **measurement**, not a float. A bare float cannot
express what the mesh tier actually knows.

```jsonc
{
  "value": 634.5135,
  "unit": "mm3",
  "exactness": "exact" | "approximate",
  "bounds": [633.9, 634.6]        // REQUIRED iff exactness == "approximate"
}
```

- `value` — the best estimate.
- `exactness` — **a property of *(check, backend, geometry)*, not of *(check, backend)*.**
  It MUST be determined per evaluation, never looked up in a static table.
- `bounds` — a closed interval `[lo, hi]` guaranteed to contain the true value, where "true
  value" means what §2.3 says it means. **Asymmetric bounds are expected and MUST be
  preserved**; a backend derives the interval from what it actually did, never from a
  constant and never from an assumed sign.

> **Tessellation is not a source of `approximate`.** An earlier draft treated it as the
> archetypal one. Under §2.3 a mesh **is** a polyhedron and its volume, area, bbox, genus
> and watertightness are computed exactly from its triangles — changing `$fn` does not
> degrade a measurement, it **produces a different part**, which the tool should report
> loudly rather than absorb into an error bar. The one genuine source of inexactness on the
> mesh tier is float32 coordinate quantization in binary STL (~1e-7 relative); see
> `SPEC-backend.md` §5.2.

A backend that cannot honestly produce `bounds` for a quantity MUST NOT report that
quantity as `approximate`; it MUST report the check as `unsupported` (§3). Guessing an
error bar is the same lie in a smaller font.

### 2.1 Scalar and vector measurements

Measurements are **scalar by default**. A vector quantity (an envelope, a centre of mass)
carries an array `value`, and its `bounds`, when present, is an array of intervals
**positionally aligned with `value`**. A measurement is vector iff `value` is an array;
there is no separate type tag.

```jsonc
{
  "value":  [15.8, 15.8, 8.0],
  "unit":   "mm",
  "exactness": "exact",
  "axes":   ["x", "y", "z"]
}
```

```jsonc
{
  "value":  [30.02, 20.01, 10.00],
  "unit":   "mm",
  "exactness": "approximate",
  "bounds": [[29.98, 30.04], [19.97, 20.03], [9.98, 10.02]],
  "axes":   ["x", "y", "z"]
}
```

`axes` is REQUIRED on vector measurements and names each component, so a consumer never
infers meaning from position alone. Adjudication (§3.1) is applied **per component**, and
the check's status is the worst across components in the order
`fail > approximate > pass`.

### 2.2 Units

`mm` is the only length unit in v0, matching every engine in scope. `unit` is nonetheless
REQUIRED on every measurement, because it distinguishes quantities a bare number cannot:

<!-- BEGIN GENERATED: unit-table -->
| unit | emitted by |
|---|---|
| `mm` | `envelope`, `hole_diameter`, `bolt_circle`, `fillet_radius`, `min_wall` |
| `mm2` | `area` |
| `mm3` | `volume`, `keep_out`, `keep_in` |
| `deg` | `draft_angle` |
| `count` | `solid_count`, `genus`, `cavities`, `topology` |
| `bool` | `watertight`, `self_intersection_free` |
| `rel` | `step_roundtrip` |
<!-- END GENERATED: unit-table -->

`bool` and `rel` were absent from this table while the tool emitted both. §5's remark that
`unit: "bool"` disappears was scoped to `requires` predicates, which carry no measurement
at all, and got over-generalised into a claim about the vocabulary. The table is generated
from `contract.MEASURANDS` now, so a new check emitting a new unit brings its own row.

Values are never scaled. There is no `part.units` field: a single legal value is not
information, and every measurement carries its own unit anyway.

### 2.3 The measurand — what "the true value" refers to

**A measurement describes the geometry as actually authored and exported, NOT an idealized
smooth solid the designer may have had in mind.** (Settled 2026-08-02; this determines
every backend method's obligation to produce `exactness` and `bounds`.)

An OpenSCAD `cylinder($fn=16)` **is** a 16-sided prism. Its volume, bounding box, genus,
clearance and interference are therefore **closed-form exact**, not approximations of a
cylinder. This is consistent with §1.1 (which calls it "a genuine 16-sided prism"), with
§3.2's prohibition on reconstruction, and with investigation 04 §4's conclusion that for
fit and printability the mesh is sometimes the *more honest* representation.

The rejected alternative — measuring against the idealized smooth solid — would make every
curved-surface quantity approximate, and is **unimplementable on the mesh tier anyway**,
because the exported STL has erased `$fn` and the tool cannot recover what the designer
meant.

**The honest corollary, which MUST be stated rather than hidden:** `partspec` measures the
artifact, not the intent. A coarse `$fn` is a *design choice the tool reports* (via
`geometry.triangles`), not an error the tool bounds away. A part whose bore is a 16-gon
will be measured as a 16-gon — which is what a real dowel will experience.

---

## 3. Check status — five values, and how they are decided

```
pass · fail · approximate · unsupported · skipped
```

Only `pass` is green.

| status | meaning |
|---|---|
| `pass` | Evaluated and satisfied, **conclusively** |
| `fail` | Evaluated and violated, **conclusively** |
| `approximate` | Evaluated, but the error interval straddles the threshold — **indeterminate** |
| `unsupported` | This backend cannot evaluate this check on this geometry at all |
| `skipped` | Not evaluated: a referenced part is absent, or a `parameter` check short-circuited the run (§4.1) |

### 3.1 Adjudication against an interval

This is the core algorithm and the reason `approximate` is a *status* rather than a flag.

For a threshold check (`measurement ≥ limit`, or `≤`, or within a range):

1. If `exactness == "exact"` → compare `value` directly → `pass` or `fail`.
2. Otherwise compare the **whole interval** `[lo, hi]` against the limit:
   - interval lies **entirely** in the satisfying region → `pass`
   - interval lies **entirely** in the violating region → `fail`
   - interval **straddles** the limit → `approximate`

So an approximate measurement still adjudicates **conclusively** most of the time. A wall
measured at 2.4 mm ±0.01 against a 2.0 mm minimum is a real `pass`; the same wall measured
at 2.01 mm ±0.05 is `approximate`, because the tool genuinely does not know.

`approximate` therefore means exactly one thing: **the answer is inside the error band.**
It is not a general "this was a mesh" marker — that is what `exactness` on the measurement
records.

### 3.2 `unsupported` vs `approximate`

`unsupported` MUST be used when the *representation lacks the entity*, not merely precision.
On a triangle mesh there is no cylindrical face, so hole diameter is `unsupported` — never
`approximate`, and never fitted (see §1.1). Per investigation 04 §4, fitting produces
confident wrong numbers in the unsafe direction; **a backend MUST NOT satisfy a check by
reconstructing an entity the representation does not contain.**

There is a second, less obvious route to `unsupported`: **a quantity for which no honest
two-sided bound exists.** Wall thickness is the worked example. It is measured by ray or
maximum-inscribed-sphere sampling on *both* tiers, and sampling is one-sided by
construction — more samples can only ever find a *thinner* wall. A measurement is therefore
an **upper bound on the true minimum**, not a centred interval, and no principled `lo`
exists.

By §2's rule ("a backend that cannot honestly produce `bounds` MUST NOT report that
quantity as `approximate`"), **`min_wall` is `unsupported` on the mesh tier** until someone
derives a defensible lower bound — the tier refusal stands.

On the OCCT tier it **is** an `approximate` check, and the first one: a guaranteed `[lo,
hi]` interval whose straddle of a limit adjudicates `approximate` and exits 2 (§10, and
`SPEC-contract.md` §4.11). An earlier draft of this paragraph said "it is not an
`approximate` check" without the tier qualifier, which stopped being true when #140
shipped.

### 3.3 Bound epsilon

Every threshold comparison MUST apply a tolerance, because contracts routinely derive
geometry from the same constant they bound against and exact float equality at a boundary
is a coin flip. The tolerance is **relative as well as absolute**:

```
ε(limit) = 1e-6 + 1e-7 · |limit|
```

**A purely absolute `1e-6` is wrong, and it breaks the v0 envelope check.** Binary STL
stores coordinates as float32, whose half-ulp is `v · 2⁻²⁴ ≈ 5.96e-8 · v` and therefore
exceeds `1e-6` for any dimension above ~16.8 mm. Measured:

```
cube([120.3, 80.7, 40.1])  →  extents 120.30000305, 80.69999695, 40.09999847
                              deltas  +3.05e-6, −3.05e-6, −1.53e-6
```

Against `max: 120.3` an absolute `1e-6` yields a **conclusive `fail` on a geometrically
perfect part** — and `envelope` is one of only three geometry checks in v0, so this is the
main path, not a corner case. The relative term covers float32 quantization with an order
of magnitude of headroom while staying far below any real engineering tolerance.

(cad-khana uses a flat `1e-6`, which is safe there because it operates only on in-memory
OCCT doubles and never round-trips through binary STL.)

### 3.4 Limit forms

A check's `limit` is one of a small closed set, so consumers can render and compare limits
without knowing the check kind:

| form | shape | satisfied when |
|---|---|---|
| minimum | `{"min": 2.0}` | `value ≥ min` |
| maximum | `{"max": 40.0}` | `value ≤ max` |
| range | `{"min": 7.9, "max": 8.1}` | `min ≤ value ≤ max` |
| equality | `{"equals": 1}` | `value == equals` (exact types only) |
| membership | `{"in": ["inner", "outer"]}` | `value ∈ in` |

`equals` and `in` MUST NOT be used with an `approximate` measurement — equality against an
interval is not decidable, and a check that needs it MUST be expressed as a `range`.

**Vector limits.** Any of the numeric forms MAY carry an array value instead of a scalar,
positionally aligned with the measurement's `value` and `axes`, and compared elementwise:
`{"max": [40, 40, 15]}`. A length mismatch between limit and measurement is a **contract
error** (`verdict: "error"`), never a partial evaluation. The limit does **not** carry its
own `axes` — a second copy of the axis order is redundant state that can desynchronize from
the measurement's, and the measurement is the authority.

---

## 4. Phases

Checks run in two phases, and the distinction is visible in the report because it changes
what a result means.

| phase | when | engine required |
|---|---|---|
| `parameter` | before the engine is invoked; pure arithmetic over declared inputs | no |
| `geometry` | after the artifact is built | yes |

Every check carries `"phase": "parameter" | "geometry"`.

The parameter phase is the fully engine-neutral core — `bayonet-lock-scad`'s entire
documented rule set (`entry_depth < part_height`,
`pin_radius + allowance/2 ≤ shell_thickness`, `0 < sweep_angle < 360/number_of_pins`) lives
here and needs no kernel at all. Parameter checks MUST report `exactness: "exact"` and MUST
NOT report `approximate` or `unsupported`; arithmetic does not degrade by backend.

### 4.1 Short-circuiting

**If any `parameter` check fails, the engine MUST NOT be invoked.** Building geometry from
parameters already known to be invalid wastes time and, worse, produces a shape whose
geometric measurements describe something the contract has already rejected.

In that case every `geometry` check MUST still appear in the report with
`status: "skipped"` and `detail` naming the parameter check that short-circuited. They MUST
NOT be silently omitted — an absent check is indistinguishable from a check that was never
declared, which is the vacuous-green failure in another form.

The verdict is `fail` (a check failed), so the exit code is `1`, not `2`.

---

## 5. Write semantics

1. **A report MUST be written on every terminal outcome, including `error`.** A run that
   crashes and leaves the previous report in place is the worst failure in the system: the
   file is stale but reads as current, and both a human and an agent will trust it. This is
   why `verdict: "error"` exists rather than simply exiting non-zero.
2. **An `error` placeholder MUST be written *before* the engine is invoked**, and replaced
   by the real report on completion. A `try/finally` cannot survive a native fault: an OCP
   segfault or an OOM kill takes the process down with no Python unwinding, leaving
   yesterday's `verdict: "pass"` at a deterministic path. Writing the placeholder first
   means the *worst* case is a report that says the run died, never one that says the part
   was fine. Only the in-process OCCT tier is exposed to this — OpenSCAD runs as a
   subprocess whose crash the parent observes normally.
3. **Writes MUST be atomic** — write to a temporary file in the destination directory, then
   rename. A partially-written report that happens to parse is worse than none.
4. **Batch runs MUST NOT abort early.** When several parts are checked in one invocation,
   a failure in one MUST NOT prevent the others from being evaluated and written; failures
   are collected and reported as a single non-zero exit at the end. Directly cad-khana's
   deferred-failure lesson — the purpose is that every report on disk is fresh.
5. The report path is deterministic from the target, so that a stale file is overwritten
   rather than accumulating beside its replacement.

---

## 6. Verdict and exit codes

### 6.1 Verdict

Computed from the check statuses, in this precedence order:

A build failure is split by **cause**, because the two mean opposite things to a
reader. A design that does not compile is a statement about the part: `builds` fails,
`verdict: "fail"`, exit `1`. An *environment* fault — no engine on `PATH`, a mistyped
`PARTSPEC_OPENSCAD`, a missing engine package, a source file that is not there, a render
that exceeded its timeout — is not a statement about the part at all, and MUST NOT be
reported as one. It is `verdict: "error"`, exit `4`, with every declared check `skipped`
and `builds` never `fail`. A CI run on a machine with no OpenSCAD installed must not
report the design as disproven.

The distinction is carried in `BuildError.origin` (`"environment"` or `"model"`) and
surfaced in the report as a field a consumer can branch on — not as prose in `detail`.

| verdict | condition |
|---|---|
| `error` | the contract raised, or the build could not be *attempted* (see above) |
| `empty` | zero checks were declared |
| `fail` | ≥1 `fail` |
| `incomplete` | no `fail`, but ≥1 `approximate` / `unsupported` / `skipped` |
| `pass` | ≥1 check, **all** `pass` |

`empty` is a distinct verdict rather than a degenerate `pass`, because a contract with no
checks is the vacuous-green case and is the single most likely thing an agent produces when
it does not know what to assert.

### 6.2 Exit codes

| code | verdict | meaning |
|---|---|---|
| `0` | `pass` | everything asserted was proven |
| `1` | `fail` | something asserted was disproven |
| `2` | `incomplete` | nothing disproven, **not everything proven** |
| `3` | `empty` | no checks declared |
| `4` | `error` | the contract raised, or the environment prevented a build |
| `64` | — | usage error: unresolvable target, bad arguments (`EX_USAGE`) |
| `130` | — | user interrupt (SIGINT convention); the operator's own abort, never a verdict |

**`2` is the load-bearing one.** It is what stops D10 from being a comment. A tool that
exits 0 on a part whose checks were mostly unavailable has told the operator that the part
is fine, which it has not established.

**Batch invocations.** One report is written **per part** (§5.4), not per invocation. When
several parts are checked at once, the process exit code is that of the
**highest-precedence verdict across all parts**, using the same order as §6.1
(`error > empty > fail > incomplete > pass`).

An unresolvable target exits `64`, outranking every verdict — but the remaining targets
MUST still be evaluated and written first (§5 rule 4). An earlier draft reserved `64`
from this aggregation on the theory that usage failures produce no reports; the
placeholder rule (§5 rule 2) means they do — an error artifact naming the dead run — and
a batch that reported a mistyped (or deleted: that is how a contract vanishes in a
weakening attack) target as a mere part-verdict would bury the fact that a question went
unasked. A user interrupt (exit `130`) is the one failure that does stop a batch: it is
the operator's own abort, not a part's.

The model-module cache MUST be invalidated after every Python-engine build in a process
(every module a resolve or build introduced from the model's directory evicted from
`sys.modules`), because a second contract
importing an edited helper otherwise gets the previous version — a stale build reported
as fresh, with a closure digest computed from a file that never reached the interpreter
(POST-V0 §8, shipped with #29).

**`--allow-incomplete` is deliberately NOT in v0.** It would map `incomplete` → exit `0`,
and it is the obvious first request once exit `2` becomes inconvenient. Shipping the escape
hatch alongside the discipline means the discipline is never actually tested: the first
time a mesh-tier part reports `incomplete`, the flag gets set in CI and D10 quietly stops
existing.

Withhold it until the dogfood run shows a case where `incomplete` is genuinely the right
long-term state for a part rather than a gap to close. If it is added later it MUST NOT
change the report body, and MUST be recorded (`invocation.allow_incomplete: true`) — an
escape hatch that leaves no trace is indistinguishable from the bug it papers over.
Adding both the flag and the field later is a non-breaking change (§7.1, unknown fields),
so nothing needs reserving now.

---

## 7. Schema

`schema_version` is an integer, incremented on any breaking change. Consumers MUST reject
an unknown major version rather than best-effort parse it.

```jsonc
{
  "schema_version": 1,
  "tool": { "name": "partspec", "version": "0.1.0" },

  "part": {
    "id": "bayonet-lock-pin",
    "contract": "parts/bayonet/spec.py:lock",
    "contract_digest": "sha256:4a17...",
    "source": "vendor/bayonet_lock.scad",
    "source_digest": "sha256:9f2c...",
    "source_closure": {                // §8.3 — every file the render reads
      "digest": "sha256:b304...",      // over sorted content hashes, not paths
      "files": 16,
      "imports": {},                   // distributions the model loaded; {} is a claim, absent is not
      "unseen": []                     // the closed gap vocabulary; partial == bool(unseen)
    }
  },

  "engine": {
    "kind": "openscad",              // openscad | build123d | cadquery
    "version": "2021.01",
    "backend": "mesh",               // the measurement tier: mesh | occt
    "render_backend": "CGAL",        // always present: the pinned choice, or null = the engine's own default
    "adopted_via": null,             // "wrapped" when a cadquery shape entered the occt backend
    "method": null,                  // the invoked callable/module when method= was set; null = the default entry
    "param_mode": "define"           // OpenSCAD only: "define" (-D) | "call" (a derived entry invoking method)
    // "source_rendered": "derived"  // call path only: the engine's entry was a derived scratch, not the digested file
  },

  "params": { "interface_radius": 8, "allowance": 0.2 },

  "geometry": {
    "triangles": 3748,               // mesh tier only; drift explainer (chord error ~ edge length)
    "distinct_normals": 70           // mesh tier only; identity signal, tracks $fn, retriangulation-invariant
  },

  "renders": {                       // only when the run produced images (§8.4); omitted otherwise
    "iso": "renders/iso.png",        // relative to the report's directory, per §8 rule 4
    "front": "renders/front.png",
    "top": "renders/top.png",
    "right": "renders/right.png"
  },
  "render_tessellation": {           // §8.4 — beside renders when they came from the OCCT
    "tolerance_mm": 0.1,             // tier's rasterizer (#18): the tessellation is what was
    "triangles": 520                 // shown (D15). Absent for OpenSCAD renders.
  },

  "verdict": "incomplete",
  "counts": { "total": 5, "pass": 3, "fail": 0,
              "approximate": 0, "unsupported": 1, "skipped": 1 },
  "attribution": { "dimensional": 2, "attributed": 0 },   // envelope + hole_diameter,
                                                         // neither citing a source: this
                                                         // example draws the §6 warning

  "checks": [
    {
      "id": "sweep_fits_pin_count",
      "kind": "requires",
      "phase": "parameter",
      "status": "pass",
      "measurement": null,
      "limit": null,
      "expr": "0 < sweep_angle < 360/number_of_pins",
      "operands": { "sweep_angle": 40, "number_of_pins": 2 },
      "detail": null
    },
    {
      "id": "pin_fits_shell",
      "kind": "requires",
      "phase": "parameter",
      "status": "pass",
      "measurement": null,
      "limit": null,
      "expr": "pin_radius + allowance/2 <= shell_thickness",
      "operands": { "pin_radius": 1.0, "allowance": 0.2, "shell_thickness": 2.5 },
      "detail": null
    },
    {
      "id": "envelope",
      "kind": "envelope",
      "phase": "geometry",
      "status": "pass",
      "measurement": {
        "value": [15.8, 15.8, 8.0], "unit": "mm",
        "exactness": "exact", "axes": ["x", "y", "z"]
      },
      "limit": { "max": [40, 40, 15] },
      "components": { "x": "pass", "y": "pass", "z": "pass" },
      "detail": null
    },
    {
      "id": "watertight",
      "kind": "watertight",
      "phase": "geometry",
      "status": "skipped",
      "measurement": null,
      "limit": { "equals": true },
      "detail": "not evaluated: part 'cap' absent from this run"
    },
    {
      "id": "bore_diameter",
      "kind": "hole_diameter",
      "phase": "geometry",
      "status": "unsupported",
      "measurement": null,
      "limit": { "min": 10.0 },
      "detail": "mesh backend has no cylindrical faces; fitting is unsafe on faceted prisms",
      "requires": "occt"
    }
  ],

  "error": null,
  "hint": null,
  "build_origin": null,              // "environment" | "model" | null — see below
  "build_stderr": null,              // engine's full stderr on a build failure; hint is one selected line of it

  "environment": {
    "python": "3.12.7",
    "packages": { "build123d": "0.11.1", "cadquery-ocp": "7.9.3.1.1",
                  "cqgridfinity": "0.5.7", "numpy": "2.5.2" },  // every installed
                                                                // distribution, name-sorted
    "platform": "linux-x86_64",
    "duration_ms": 812
  },

  "invocation": { "argv": ["check", "parts/bayonet"], "timeout_s": 300.0 }
}
```

This example is **conformant and confined to the v0 check set** (D11): parameter predicates
plus `envelope` and `watertight`. `counts.total` equals `len(checks)`, and the five status
counts sum to it — both MUST hold. `bore_diameter` is shown only to illustrate
`unsupported` + `requires`; it is not a kind, then or now — the shipped hole check is
`hole_diameter` (`SPEC-contract.md` §4.5, since 0.2.0), and the example predates it.

Note there is **no `approximate` check here, and there cannot be one in v0** — see §10.

### 7.1 Field rules

- **`part.contract_digest` / `part.source_digest`** — sha256 of the contract module and of
  the source content. Digests give **identity**, and support **comparison-based** tamper
  evidence: two reports whose `contract_digest` differs were produced from different
  contracts.

  They do **not** make a weakened contract visible in a *single* report — "the digest
  changed" is a two-observation predicate, and D6 assigns that job to the semantic `diff`
  that §9 defers. Two further limits, stated rather than glossed: the contract digest is
  **module-scoped** while `part.contract` names a symbol, so an unrelated edit to the same
  module also changes it; and `source_digest` covers only the named file, **not** anything
  it pulls in via `include <>` / `use <>`.

  > **The v0 gap, closed post-v0.1: silent contract weakening.** An agent that deletes a
  > check produces a report that is internally consistent and green. `counts.total` and
  > `contract_digest` make it *detectable on comparison*, not *visible on inspection* —
  > and `partspec diff` (`SPEC-diff.md`) is now that comparison: a removed check is named
  > by id, exit 1. Since #31 the no-baseline half is closed too: the claims pin
  > (`--expect`, the `expectation` block below) fails a single run whose declared claim
  > set drifted from its committed lock — no previous artifact required.

  Module-scoping is deliberate, not an oversight: digesting only the resolved symbol would
  miss an edit to a module-level constant such as `MIN_WALL`, which is precisely the
  attack. Over-firing is the right direction of error here.
- **`expectation`** — present only when the run was invoked with `--expect`: the claims-pin
  adjudication `{claims, matched[, differences]}` (#31). "Make the check pass" and "delete
  the check" are the same action from where a model sits; `diff` catches the second on
  comparison, and the pin catches it with no previous artifact in hand — a fresh CI
  checkout, or an agent loop whose first run is already post-tamper. A mismatch MUST be
  `verdict: "error"` with every declared check `skipped` and the differences named — the
  question changed identity, so nothing may be said about the part — and MUST live in the
  artifact, not only on stderr, for the same reason `attribution` does. The pin covers the
  claim *set* (kind, limits, region, hole, expression, citation per id), not the count:
  swapping a strict check for a lax one under the same id, or stripping a `source`
  citation, is a named difference. Every pinned part MUST be covered by the invocation —
  a pinned part no target produced is the same failure, on stderr and in the exit code,
  since no report exists to carry it. Two scope limits, stated: the pin binds *claims*,
  not the source (identical claims pointed at a different model pass — `source_digest`
  and `diff` own source identity), and the lock is regenerable by design — the tool makes
  weakening impossible to do *silently*, while forbidding re-pin-after-weakening is the
  agent contract's job.
- **`invocation.timeout_s`** — the build budget that governed the run, in seconds. The CLI
  always records the fully resolved value (`--timeout`, then `PARTSPEC_TIMEOUT`, then the
  300 s default); `0` records an explicit waiver of the bound, and `null` means a library
  caller invoked `run` without choosing (the backend default still applied). A run stopped
  by its budget MUST be attributable to that budget from the artifact alone — `verdict:
  "error"` with `build_origin: "environment"`, never a failing `builds` check: a stopwatch
  disproves nothing about the part (#46).
- **`geometry.triangles`** and **`geometry.distinct_normals`** — both recorded, because
  `$fn` lives *inside* the `.scad` and is invisible to the tool while these are not.
  `distinct_normals` is the count of distinct face normals: it tracks `$fn` one-to-one (a
  cylinder at `$fn=n` yields `n+2`) and is invariant under retriangulation, making it the
  better *identity* signal. `triangles` is the better *drift explainer*, because chord error
  scales with edge length. Neither substitutes for the other. Both are mesh-tier only and
  MUST be absent on the OCCT tier.

  It is deliberately **not** a coplanar-region facet count (D16): that needs `scipy` or
  `networkx`, a large dependency for one provenance field. The two agree on convex solids
  and differ only where disjoint coplanar regions share a normal, so the field is named for
  what it measures rather than borrowing CGAL's vocabulary for a different quantity.
- **`engine.method` / `engine.param_mode` / `engine.source_rendered`** — `method` is
  always present (mirroring `adopted_via`): the callable or module `method=` invoked, or
  `null` for the default entry. Two runs of one contract can build different things, and
  a single report must say which happened. On OpenSCAD, `param_mode` states how the
  parameters reached the geometry — `"define"` (`-D`) or `"call"` — and on the call path
  `source_rendered: "derived"` records that the engine's entry was a derived scratch
  including the digested file, so `source_digest` cannot be read as naming the rendered
  input. Additive, same terms as `engine.render_backend` below.
- **`engine.render_backend`** — always present: the pinned string, or `null` when the run
  took the engine's default. `null` MUST be read against the recorded `engine.version`:
  it means "the default for that version", which on OpenSCAD is **CGAL on 2021.01 and
  Manifold on current builds** — so the null case is exactly the run whose backend a
  reader could not otherwise infer. Recorded at all because it
  **changes the artifact, not merely the speed of producing it**: measured on a community
  gridfinity bin, OpenSCAD's default Manifold backend emitted 4 non-manifold edges where
  CGAL emitted none, from identical source. Two reports that differ only here are not
  comparable on mesh validity.
- **`build_origin`** — `"environment"`, `"model"`, or `null`: whose fault a build failure
  was. `"model"` is a statement about the part (the design does not compile) and adjudicates
  as a failing `builds` check; `"environment"` is not a statement about the part at all — no
  engine on PATH, a missing wheel, an option the installed engine does not accept, a render
  that ran out of time — and MUST NOT be reported as a verdict on the design (§6.1). Null
  when the build succeeded. This is the primary routing key `docs/AGENT-CONTRACT.md` §2.3
  tells an agent to read, and it was emitted by every report since v0.4.0 while appearing in
  this document only in passing; the omission is what let two faults ship misclassified into
  the v0.7.0 audit.
- **`environment.packages`** — **every distribution installed** in the environment that ran
  the build, name → version, sorted by name, first occurrence on `sys.path` winning so the
  report cannot disagree with a hand-run `importlib.metadata.version()`. Through v0.7.4 it
  was a five-name allowlist of engine packages (`build123d`, `cadquery`, `cadquery-ocp`,
  `trimesh`, `manifold3d`), which could not see the library a contract wraps and therefore
  could not explain a number that moved when *that* was upgraded (#211). It is keyed on
  what is installed, **not** on what the process imported, and rule 2 below is why: several
  targets share one interpreter, so an import-keyed field would make a part's recorded
  environment depend on which unrelated target ran before it — measured, an OpenSCAD-tier
  part recorded 6 distributions alone and 41 in a batch behind a build123d part, from
  identical inputs on one machine. An environment is a property of the venv. Which
  distributions *a given part* loaded, and whether the bytes that ran are the ones the
  installer recorded, is answered by `part.source_closure` (§8.3), not here — with the
  same shared interpreter still in the way there: `source_closure.imports` scopes the
  question to the part but is still read from one `sys.modules`, so it over-reports in a
  batch and §8.3 rule 7 requires it to name what it cannot attribute. Moving the field did
  not remove the sharing; it made the bound statable per part.
- **`checks[].requires`** — present only on `unsupported`, naming the tier that would answer
  **for an equivalent part**. The hedge is load-bearing: porting a 16-gon bore to build123d
  does not merely enable the check, it **changes the part** (investigation 04 §4). This is
  an actionable pointer, not a promise that the answer would be the same.
- **`checks[].id`** — stable within a contract, used as the join key by `diff`. Two checks
  in one report MUST NOT share an `id`. A contract that would emit a duplicate is a
  contract error (`verdict: "error"`), not a silently deduplicated report.
- **`checks[].components`** — present on a check whose measurement is a vector **and whose
  components are adjudicated against a limit**: axis → status (e.g. `{"x": "pass", "y":
  "pass", "z": "fail"}`), so a failure names *which* component to act on instead of leaving
  the consumer to re-derive it from the vectors. This said "every check whose measurement is
  a vector" until v0.7.0, which `hole_diameter` falsifies: its measurement is the vector of
  matched diameters, adjudicated as a set against a band rather than per axis, so it carries
  a `hole` callout and no `components`. A consumer must therefore test for the key rather
  than assume a vector implies it.
  Derived from the same per-component adjudication the check status folds, never computed a
  second way. Recorded on pass too (the §7.2 principle applied to attribution); an
  unconstrained axis is **absent**, because an omitted claim has no status. The check-level
  `status` remains the worst constrained component — this field adds attribution, not a new
  verdict path. On `keep_out` / `keep_in` the two clauses appear as `region` and `shell`.
  Additive (no schema bump). Resolves Q8.
- **`checks[].region`** — present only on `keep_out` / `keep_in` checks: the declared region
  (`shape`, its dimensions, and the mandatory `shell` thickness), so the report states what
  was claimed and not just how it went. These checks carry `limit: null` — the claim is a
  paired one (empty here AND solid nearby, or the mirror) that no limit form expresses — and
  their `measurement` is the two-component vector `(region, shell)` of material volumes.
  Additive (no schema bump).
- **`checks[].hole`** — present on `hole_diameter` and `bolt_circle` checks: the declared
  callout, `{"d": ..., "count": ...}` (plus `"bcd"` for a bolt circle). The diameter band lives in the check's `limit`; the
  measurement is the vector of matched diameters (null when none matched, with the part's
  full bore inventory in `detail` on failure). Additive (no schema bump).
- **`checks[].direction`** — present only on `draft_angle` checks: the pull axis the draft
  was measured against, as `[x, y, z]`. Part of the claim's identity, not context — the same
  part measures differently under a different pull, so a draft claim without its axis is not
  reproducible, and `SPEC-diff.md` compares it as a claim field. Additive (no schema bump).
- **`checks[].step`** — present only on `step_roundtrip` checks: `{"schema": ...}`, the
  application protocol the writer emitted (`AP214IS` today). The check answers whether the
  part survives its own exchange format, and which format that was is part of the answer.
  Additive (no schema bump).
- **`checks[].source`** — present when any of the check's bounds was a `Referenced` value
  (`SPEC-contract.md` §10): `{field: {"standard", "subject", "field"}}`. The report states
  not just what was claimed but on whose authority; a bare-literal bound records nothing,
  which is itself the signal #50's warning channel reads. Additive (no schema bump).
- **`checks[].kind`** — an **open vocabulary**, defined in `SPEC-contract.md`. This document
  deliberately does not enumerate it: the report format must not need revising every time a
  check is added. Consumers MUST treat an unrecognized `kind` as opaque and rely on
  `status`, `measurement` and `limit`, all of which are closed.
- **`checks[].phase`** — `parameter` or `geometry` (§4). Lets a consumer explain a report
  full of `skipped` geometry checks without re-deriving the short-circuit rule.
- **`attribution`** — run-level `{"dimensional": N, "attributed": M}` over the
  `DIMENSIONAL_KINDS` (`SPEC-contract.md` §6): how many checks carry chosen numbers, and
  how many of those numbers came from somewhere (§10). `dimensional > 0 && attributed == 0`
  is the circular-contract signal, carried in the artifact because the artifact is the
  product surface — the CLI warning derives from this field, and an agent consuming the
  report over MCP would otherwise never see the disclosure. Additive (no schema bump).
- **`counts.total`** — MUST equal `len(checks)`, and the five status counts MUST sum to it.
  Redundant by construction and included anyway, because it is the cheapest signal that a
  contract lost checks between two runs.
- **`build_stderr`** — the engine's complete stderr when a build failed, `null` otherwise.
  Additive (no schema bump). `hint` is one *selected* line of engine output and selection
  can be wrong — noise filtering must never be able to lose the diagnosis, so the
  unabridged text travels with the report.
- **`error` / `hint`** — `error` carries the full traceback when `verdict == "error"`;
  `hint` carries a pattern-matched one-line repair suggestion when one is recognized.
  Consumers SHOULD surface `hint` before `error`.
- **On `verdict: "error"`, `checks` MUST still list every declared check**, each with
  `status: "skipped"`. An error report with an empty `checks` array is indistinguishable
  from `empty`, and would let a crash masquerade as an unwritten contract.
- **Unknown fields.** Consumers MUST ignore fields they do not recognize. This is the
  precondition for every deferral in this document: adding a field is a non-breaking change
  and MUST NOT bump `schema_version`; removing or re-typing one MUST.

`engine.backend` is the **measurement tier** (`mesh` | `occt`); `engine.render_backend` is
the OpenSCAD **kernel** (`Manifold` | `CGAL`). Two different things, and the shared word is
unfortunate — but `engine.tier` was tried and dropped in an early draft, and
`tests/test_report.py::test_spec_example_uses_no_deleted_fields` exists to stop it coming
back. `measure` MUST emit `backend` too; it emitted `tier` until 2026-08-07, which is the
only reason the name looked unsettled.

### 7.2 Measurements are recorded on pass, not only on failure

`checks[].measurement` MUST be populated whenever the check was evaluated, **including when
it passed.** This is non-obvious and load-bearing: it is what lets `diff` report *drift on
checks whose pass/fail state did not change* — "drift the boolean can't see." A wall
thinning from 2.9 mm to 2.1 mm against a 2.0 mm minimum is two passes and one very
important trend, and nothing else in the system can see it.

---

## 8. Determinism

The report is compared across runs, so instability is a correctness bug.

1. **Ordering.** `checks` MUST appear in contract declaration order. Object keys MUST be
   emitted in the order given in §7. Any derived collection MUST be sorted by a stated key.
2. **Volatile data is quarantined — by field, not by block.** Only
   `environment.duration_ms` and `environment.platform` may vary
   between two runs of identical inputs on the same machine, and only those MUST be excluded
   from comparison.

   **`environment.packages` MUST NOT be excluded.** It is exactly what distinguishes "a
   trimesh upgrade moved this number" from "the design changed" — the drift §7.2 exists to
   surface. A comparator that quarantines the whole block loses the ability to explain its
   own findings. The corollary binds the producer as well as the comparator: a field that
   is mandatory to compare MUST be stable across two runs of identical inputs, which is
   why `packages` enumerates the installed distributions rather than the imported ones.

   Nothing outside `environment` and `invocation` may carry a timestamp, duration,
   hostname, or PID. **Exception:** `error` and `build_stderr` carry engine and
   interpreter output verbatim — tracebacks with absolute paths, cache statistics,
   rendering times. That is intentional and outside rules 2 and 4: a diagnosis with the
   volatile parts stripped is materially harder to act on, and both fields are `null`
   except on a failure, where run-to-run comparability is not the concern.
3. **Floats.** Emitted at full `repr` precision. Byte-stability across OCCT or engine
   versions is **not** guaranteed and MUST NOT be assumed — rebuilding identical geometry
   through a different transform-composition order perturbs coordinates at ~1e-13. Any
   comparator MUST therefore apply a numeric tolerance (`1e-6` recommended) rather than
   exact equality, or it will report noise and bury signal.
4. **Paths** are project-relative, POSIX-separated.

### 8.3 `part.source_closure` — identifying the whole input

`source_digest` covers the entry file. On real OpenSCAD libraries that is a small fraction
of the build: the gridfinity bin in the dogfood corpus is one file of **sixteen**. Edit a
helper three levels down and the part changes while `source_digest` does not, so two
genuinely different builds compare as identical inputs. This is F13's failure class — a
library moving underneath a source that did not change — arriving in the provenance layer,
and a comparator would have inherited it silently.

An OpenSCAD report therefore carries:

```json
"source_closure": {
  "digest": "sha256:…",
  "files": 16,
  "unresolved": ["some/missing.scad"],
  "reads_external_data": true,
  "partial": true,
  "imports": {},
  "unseen": ["external_data_reads", "unresolved_includes"]
}
```

- **`digest`** is taken over the member **content hashes, sorted** — never over paths. A
  comparator's whole purpose is comparing a CI run against a laptop run, and a
  path-sensitive digest would differ on every one of them. The trade is deliberate: it
  identifies the set of file *contents*, not the layout, so relocating a file without
  editing it does not move the digest.
- **`unresolved`** lists `include`/`use` targets not found on any search path. Resolution
  follows OpenSCAD's rule — relative to the file containing the statement, then
  `OPENSCADPATH`, then the library directories.
- **`reads_external_data`** is `true` when any file-reading construct appears anywhere in the
  closure: `import()` and its deprecated `import_stl()`/`import_dxf()`/`import_off()`
  spellings, `surface()`, the `dxf_*` extrudes and dimension functions, and
  `linear_extrude()`/`rotate_extrude()` given a `file=`. Those name STL/DXF/DAT files that
  genuinely are build inputs, and their paths may be computed at render time, so no static
  reader can resolve them. **The deprecated spellings count**: the version floor executes
  them, so a reader that recognised only the modern two reported a complete closure for a
  build that reads a file.
- **`partial`** is `true` whenever the closure left anything unseen — `partial ==
  bool(unseen)`, which for this tier is exactly "either of the previous two is non-empty".
  It is stated positively so a consumer cannot read the *absence* of those fields as a
  completeness guarantee the closure never made. **A comparator MUST treat a `partial`
  closure as inconclusive evidence of sameness**, exactly as `unsupported` is treated for a
  check: matching digests then mean "nothing we looked at changed", not "nothing changed".
- **`imports`** is `{}` on this tier and MUST be present anyway. The render happens in a
  subprocess and loads no Python, and *that is a finding*: an absent `imports` means the
  question was never asked, which is what every report written before 0.7.5 says.
- **`unseen`** names the gaps; see below.

A **Python** report carries a closure too, of a different shape:

```json
"source_closure": {
  "digest": "sha256:…",
  "files": 2,
  "scope": "model_directory",
  "partial": true,
  "imports": {
    "cadquery":     { "identity": "metadata", "version": "2.8.0", "digest": "sha256:…" },
    "cqgridfinity": { "identity": "content",  "version": null, "digest": "sha256:…", "files": 16 }
  },
  "preloaded": [],
  "unseen": ["native_reads"]
}
```

- **`scope`** names the boundary of `digest`/`files`: local modules imported from the
  model's own directory. That is not arbitrary. `engines/pycad.py` puts exactly that
  directory on `sys.path` before exec'ing the model, so a model can import helpers beside
  it — which makes those helpers build inputs by design.
- Membership is read from `sys.modules` **after the build**, so it records what was
  imported rather than what appears importable, and catches helpers imported lazily inside
  the factory.
- The contract file is excluded. `contract_digest` already covers it, and a *source* closure
  that moved whenever a claim changed would answer a different question than its name.
- **`preloaded`** names the entries of `imports` this run cannot attribute to itself,
  because a batch shares one interpreter; rule 7 below states the bound in full.
- **`partial` is unconditional here**, because `native_reads` always is. Python can import
  from anywhere on `sys.path`, read data files at run time and load C extensions, none of
  which this sees — measured: an audit hook watching `OCP.StlAPI_Reader().Read()` load an
  STL saw zero `open` events.

#### `imports` — the distributions the model loaded

A contract that wraps a third-party library identifies none of the code that built the
part: `scope` is the model's directory, and the library is not in it. The fleet-01 study
that produced #190 recorded `files: 1` for a bin whose sixteen files of `cqgridfinity`
did all the work, so every `diff` over it was permanently indeterminate and both agents
wrote their own tree hash outside the tool.

Each entry is keyed by **distribution** name where `identity` is `metadata`, and by
**top-level module** name where it is `content` or `unidentified`, because a distribution
is what carries a version and an unowned source tree has none.

The map covers what was imported **after partspec was**, which excludes the tool itself
and the interpreter's own scenery — `partspec` is already `tool.version` and would
otherwise report an input moving on every part whenever the tool was edited, and
`_virtualenv` records which program created the venv rather than anything a model reads.
Everything a contract loads happens after that point, engines included: they import their
CAD kernel lazily at build time.

| `identity` | when | `digest` covers | `version` |
| --- | --- | --- | --- |
| `metadata` | every loaded file of that distribution is declared in its installer RECORD | the RECORD's own declared hashes, `path,hash` rows sorted by path | the distribution's |
| `content` | a loaded file no RECORD declares — an editable install, a `sys.path` checkout, a package no installer wrote | the bytes of the package tree the import was loaded from, sorted content hashes as `digest` above, with `files` | `null` |
| `unidentified` | `__file__ is None` and nothing under the name is identifiable | `null` | `null` |

Rules a producer MUST follow:

1. **`metadata` identity requires positive proof of ownership.** A distribution appears
   with `identity: "metadata"` only because a file it declares was actually loaded.
   Without that check the tier is vacuous where it matters most: an editable install's
   RECORD lists only a `.pth` and a finder shim, so a material source edit left both the
   version and the RECORD digest unmoved while the bytes that ran had changed.
   Correspondingly, **a row that is not the distribution's code MUST NOT be proof**:
   setuptools writes `__editable___<name>_finder.py` into site-packages and lists it, and
   accepting it hands a `metadata` entry to a library nothing imported, with a digest over
   a shim that embeds the checkout's absolute path.
2. **Rows beginning `../` MUST be excluded from a `metadata` digest**, with `__editable__`
   rows, `.pyc` rows and the `dist-info` metadata. Console-script shebangs embed the
   venv's absolute path: unfiltered, numpy 2.5.2's digest differed across all five fleet
   venvs and agreed across none. The rule is by location, not by kind, and so also drops
   stable rows outside site-packages such as installed man pages — a reproducible digest
   over slightly less is worth more than a complete one that differs per machine.
3. **A `metadata` digest MUST cover every row of the distribution, not the imported
   package's directory.** `cadquery_ocp.libs/` holds 69 vendored OCCT shared objects,
   105 MB, beside the `OCP/` package rather than inside it, and `sys.modules` never names
   it; the RECORD does, so a digest scoped to the distribution catches it and one scoped
   to the imported directory silently does not.
4. **An import that cannot be identified MUST still be listed.** A map that omits it reads
   as an import that never happened.
5. `identity: "metadata"` is the installer's word, taken deliberately (§7.1: digests are
   comparison-based tamper *evidence*, not tamper-proofing). Ownership is decided by path,
   so **a post-install edit to a file the RECORD declares does not move a `metadata`
   digest** and does not demote the entry to `content`. Detecting it would mean hashing
   every loaded file to compare against its declared hash, which is the cost this tier
   exists to avoid. What rule 1 bounds is vacuity, not tampering.
6. A `content` digest covers **the package tree the import was loaded from**. Where a
   distribution's unit is wider than that tree — vendored shared objects in a sibling
   directory, as in rule 3 — nothing outside RECORD can discover the association, so a
   `content` entry MUST NOT be read as covering it. This is a stated bound rather than a
   gap token because a Python-tier closure is `partial` unconditionally (`native_reads`),
   so no reader may treat any of it as complete coverage.
7. **`imports` is read from a process and describes a part, so it over-reports in a
   batch, and `preloaded` MUST name what it cannot attribute.** Several targets share one
   interpreter (§8 rule 2 is the same fact one block up), and `sys.modules` does not
   record which target imported what: measured, one build123d cube recorded 38 imports
   alone and 44 behind a CadQuery target, `cadquery` among them. The map stays wide,
   because a producer that reported only the delta since the target began would drop a
   library the second target genuinely uses whenever the first loaded it first — the
   under-reporting direction this whole section refuses. So the bound is stated instead:
   `preloaded` lists, sorted, the entries of `imports` that were already in `sys.modules`
   when this target's contract was resolved, and an entry named there is one **this report
   cannot claim as its own**. It is `[]` for a target that ran first or alone, and it is a
   **Python-tier field**: an OpenSCAD closure carries `imports: {}` and no `preloaded` at
   all, because the render is a subprocess that imports nothing and there is nothing to
   attribute. Its absence therefore dates no report — `imports` is the field that does
   that (above), and a consumer reading the same absence rule into this one would misdate
   every 0.7.5 OpenSCAD report as pre-0.7.5. A consumer MUST NOT report
   an entry it names as a build input that appeared; the honest reading is that this
   comparison cannot attribute it (SPEC-diff.md §2 rule 3). It is not an `unseen` token:
   the coverage is not incomplete, the attribution is, and routing it through the gap
   vocabulary would make every multi-target Python comparison indeterminate — the exact
   outcome #190 removed.

#### `unseen` — the gaps, by name

A closed vocabulary. `partial` is derived from it: `partial == bool(unseen)`.

| token | tier | class | meaning |
| --- | --- | --- | --- |
| `native_reads` | Python | irreducible | a C extension may read files Python cannot observe |
| `unidentified_imports` | Python | bounded | an import with no `__file__`, listed in `imports` |
| `external_data_reads` | OpenSCAD | bounded | `import()`/`surface()`/`import_stl()`/… in the closure |
| `unresolved_includes` | OpenSCAD | bounded | named `include`/`use` targets not found |

A **bounded** gap is one a run could in principle close; an **irreducible** one is a
property of the tier and is present in every report that tier will ever write.

**A consumer that meets a token it does not recognise MUST treat it as a bounded gap.**
Closed vocabularies leak, and the failure must be closed: an older reader of a newer
report goes inconclusive rather than silently ignoring a gap it does not understand.

**The same rule covers the field's absence, wherever the field could have carried an
answer.** A closure missing `unseen` **or** `imports` was written before the question was
asked, and MUST NOT be read as an answer to it — so a consumer synthesises a bounded gap
for it. The qualifier is load-bearing and is not a softening: on the Python tier the
absence is exactly the pre-0.7.5 state this section describes, where `partial` was
unconditional and every comparison was already inconclusive, so the rule reproduces what
that reader already did. A pre-0.7.5 **OpenSCAD** closure is the case the qualifier
excludes: a complete one carries no `partial` key at all and compares conclusively today,
and synthesising a gap for it would raise a first alarm, on upgrade, about a question that
tier never had — the render happens in a subprocess and loads no Python. Such a closure is
classified from the legacy fields it does carry (`unresolved`, `reads_external_data`,
`partial`), which name the same gaps this vocabulary does. This is why `imports` is `{}`
and not absent on that tier from 0.7.5 on: an empty map is the answer "nothing was
imported", and only absence means "never asked".

> **Reversed 2026-08-05.** This section previously specified that the Python engines emit no
> closure at all, on the grounds that partial coverage would "assert coverage that does not
> exist, which is worse than the silence." That was wrong, and the mistake is worth keeping
> visible: silence here is not the absence of a claim, because `source_digest` remains in the
> report asserting that **one file** identifies the build. The choice was never between a
> claim and no claim — it was between a flagged partial claim and an unflagged overclaim.
> `partial` is the mechanism this very section defines for known-incomplete coverage, so a
> comparator treats matching Python digests as inconclusive rather than proven.

---

### 8.4 `renders` — images a run produced

View name → image path, relative to the report's own directory (rule 4). Present **only**
when the invocation actually produced images (`check --render`); when nothing was rendered
the key MUST be absent — never an empty object, and never an empty-string path, which reads
as a file that exists. A requested render that fails exits `4` and leaves the key absent:
the report speaks for the part, the exit code for the run. (The `render` verb's own
sibling payload is the opposite by design — its failure artifact carries `renders: {}`
beside an `error`, per the Scope above — because there the empty map sits next to the
error that explains it, while in a report it would sit next to a verdict it has nothing
to do with.)

`render_bbox` MUST sit beside `renders` whenever they are present (#21): `{min, max}`
in mm, the framing bbox. Two runs whose sizes differ uniformly render byte-identical
pixels — the camera scales with the part — so this block is the only scale witness the
images leave behind.

When the images came from the OCCT tier's rasterizer (#18), `render_tessellation` —
`{tolerance_mm, triangles}` — MUST sit beside `renders`: under D15 the tessellation is
what was shown. It is absent for OpenSCAD renders, where the engine draws its own
geometry, and never present without `renders`.

The images are evidence, not judgement — no verdict, status, or measurement may be derived
from them (D18). §9's rule stands: paths only, never inline image data.

## 9. Non-goals for v1

Stated so they are decisions rather than omissions:

- **No assemblies.** Per D11, v0 is parts only. The schema anticipates them only in that
  `checks[].id` is a free-form string, so dotted paths (`turret.rotor.arm`) will fit without
  a schema change.
- **No diff output.** `diff` consumes two reports and emits its own artifact; that is a
  separate spec.
- **No embedded renders.** Images are files on disk referenced by path, never inline.
- **No remediation advice** beyond `hint`. The report states what is; it does not plan.
- **No severity or weighting.** Every check is load-bearing or it should not be declared.
  Introducing `warning` would immediately recreate the silence-as-success problem this
  document exists to prevent.

---

## 10. The `approximate` machinery, and how it stopped being dormant

Through v0 this section said the opposite of what it says now, and the correction is worth
keeping rather than overwriting: **as v0 was scoped, no check in it could produce
`approximate`.** The v0 set was parameter predicates plus `builds`, `envelope`,
`watertight`, `solid_count` and `genus`; under §2.3's measurand every one of those is exact
on a polyhedron, and an exported OpenSCAD part *is* a polyhedron. So `bounds`, §3.1's
interval adjudication and the `approximate` status were correct, load-bearing for the
design D10 commits to, and unexercised. The two consequences were stated openly: the
dogfood run would not test the machinery, and its first real exercise would be its first
bug report.

**That debt is paid.** `min_wall` (#140, `SPEC-contract.md` §4.11) is a genuine interval
measurement on the OCCT tier — a guaranteed `[lo, hi]` from kernel-exact face-pair minima
and certified diametric spans — and a limit inside that interval adjudicates `approximate`
and exits 2. It is routine, not exotic: a U-channel bounded by a nearby gap, a stepped
slab bounded by its ledge, a tilted pocket. The first exercise was a fixture, not a bug
report.

Two notes for a reader arriving from an older copy of this document:

1. **`approximate` is live and an agent must act on it.** `AGENT-CONTRACT.md` §2.2 used to
   call it dormant and instruct an agent to escalate it as a tool bug; correct output was
   being described as a defect. Both are fixed.
2. **The mesh tier still cannot produce it.** `min_wall` is `unsupported` there for want of
   an honest lower bound (§3.2), so a mesh-only run remains exact-or-refused. That is a
   property of the tier, not of the machinery.

---

## 11. Open questions

- **Q1** — Should `skipped` and `unsupported` share exit code `2`? They differ in kind:
  `skipped` is usually the operator's doing, `unsupported` is the tool's limitation.
  Splitting them costs an exit code and may buy clarity in CI.
- **Q2** — Is `empty` (exit `3`) worth a distinct code, or should it be `fail`? Argument for
  `fail`: a contract with no checks is a defect, not a partial result. Argument for `3`: it
  is not a *geometry* failure and conflating them muddies CI triage.
- **Q3** — Should `bounds` be mandatory on *every* measurement, with exact measurements
  carrying a degenerate `[v, v]`? Uniform shape for consumers, at the cost of noise.
- **Q6** — Where does an error bound come from, for the first check that needs one? Two
  things are now known. **The one rigorously derivable bound is float32 quantization from
  binary STL** — `±v·2⁻²⁴` per coordinate, propagating trivially to a bounding box; real,
  computable, defensible, and currently unused. And **sampled quantities admit no honest
  two-sided bound at all** (§3.2), so they are `unsupported`, not `approximate`. What
  remains open is the middle ground: a defensible interval for mesh *volume* and *area*.
  Not a v0 blocker (§10).
*Resolved in draft 2:* Q5 (`--allow-incomplete` withheld from v0, §6.2).
*Resolved in draft 3:* Q4 (a facet-resolution signal added alongside `triangles`, §7.1;
implemented as `distinct_normals` per D16).
*Resolved in draft 4:* Q7 — parameter predicates are **not** measurements. A `requires`
check carries `expr` and `operands` instead of `measurement`/`limit`; `bool` is gone from
the unit table. See `SPEC-contract.md` §5.
*Resolved post-v0.1:* Q8 — per-component statuses are recorded in `checks[].components`
(§7.1), not left to `detail`: prose is for humans, and the failing axis is data an agent
acts on.

[survey-capability]: https://github.com/CameronBrooks11/partspec/blob/main/notes/survey/04-kernel-capability.md
