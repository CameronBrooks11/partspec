# partspec lint — the tier-1 rules

**Status:** v1 · 2026-08-08 · closes #26 (tier 1)
**Scope:** `partspec lint <source>…` over `.scad` and `.py` model sources. Findings are
**advisory and never a verdict on the part — it is about the source** (#26, verbatim):
exit 0 says the lint ran, the findings are data in the JSON payload, and 64 is reserved
for inputs that cannot be linted at all. The payload (schema 2) is per-file
blocks — `{file, digest, findings}` — so a clean file is a visible entry with the
sha256 of the bytes that were linted, not an absence; duplicate arguments are deduped
(#120). Tier 1 runs **without an engine installed**.

Each rule states its exact predicate — a lint whose rules are vibes teaches nothing —
plus the rationale and a real example. The rule registry in `src/partspec/lint.py` and
this document are held together by test (`tests/test_lint.py`).

Lint is for **model sources**. Pointing it at a contract flags check *limits* as if
they were model constants — advice aimed at the wrong file. An agent loop should read
each file block's `findings[]` before the first render and treat each as an optional aimed edit, never
as a failure to clear (exit 0 with findings is not AGENT-CONTRACT's exit-0 row: that
map governs `check`).

## `scad-unused-top-level`

- **Predicate:** a top-level variable **of the entry file itself** (deliberately
  narrower than the `-D` guard's include-closure walk: lint speaks about the file it
  was pointed at) whose name appears nowhere in the noise-stripped source outside its
  own assignment lines. `$`-variables are exempt — the engine reads them.
- **Rationale:** a declared knob the geometry ignores is either dead weight or a
  misrouted parameter — the same family as FAILURE-MODES entry 5, one step earlier.
- **Real example:** `examples/spacer/spacer.scad:10` — `wall = 2;` is never read by
  the geometry. It exists for the *contract's* `requires` arithmetic, which is the
  documented legitimate case: the finding's message says so, and the advisory verdict
  means it costs nothing to accept knowingly.

## `scad-magic-number`

- **Predicate:** a numeric literal with `|value| > 2` on any line that is not a
  top-level assignment or an `include`/`use`, in the noise-stripped source. The
  exemption is deliberate: 0/1/2 are structure, and the `-1`/`+2` boolean-overshoot
  idiom (skills/openscad-authoring rule 3) must not be flagged by the tool whose own
  skills teach it.
- **Rationale:** a magic number is unnameable — by `-D`, by `param`, by a report
  (skills/openscad-authoring rule 1).
- **Real example:** `cube([60, 40, 4]);` — the openscad skill's rule-1-before block,
  three findings; its after-form lints clean.
- **Known noise, owned:** canonical-orientation angles (`rotate([-90, 0, 0])`, `45`,
  `360` in ranges) fire. Accept them knowingly, or name them (`quarter_turn = 90;`) —
  the advisory verdict means acceptance costs nothing. Scientific literals match as
  whole numbers (`1e-3` is 0.001, exempt; `1e6` flags).

## `scad-module-size`

- **Predicate:** a `module` whose body spans more than 40 lines (brace-matched, over
  the noise-stripped source).
- **Rationale:** the LoC symptom head-on — the observed failure is bloat, and a module
  past feature-size has stopped being a feature (skills/openscad-authoring rule 5).
- **Real example:** the corpus's gear library concentrates its geometry in one
  ~100-line body ([corpus]; the fixture in `tests/test_lint.py` reproduces the shape).

## `py-magic-number`

- **Predicate:** a numeric `Constant` with `|value| > 2` inside a `Call`'s arguments —
  positional and keyword alike — within any function body (stdlib `ast`; each call
  reports its own arguments once; lambda bodies are pruned; defaults in the signature
  are exactly where numbers SHOULD live and are never flagged; module-level constants
  likewise; signs are kept, so `-90` reports as -90).
- **Rationale:** skills/build123d-authoring rule 1 — hoist it to a parameter with a
  default.
- **Real example:** `Box(40, 30, 4)` inside a factory — the bd skill's rule-3 block
  carries them deliberately (it is a *before* block).

## `py-function-size`

- **Predicate:** a function whose body spans more than 60 lines.
- **Rationale:** same as `scad-module-size`, Python spelling.
- **Real example:** community models are commonly one monolithic script promoted to a
  function ([corpus], F8).

## Tier 2 — the geometry rules, over the `.csg` tree (#118)

Shipped after the audit-mandated prior-art survey (recorded on #118): nothing exists
to depend on — sca2d is GPLv3 and geometry-blind, FreeCAD's importer is LGPL and
welded to its document model — so the reader is hand-rolled, stdlib-only
(`src/partspec/csg.py`), with FreeCAD's node inventory absorbed as the refusal
checklist. These rules read `openscad`'s constant-folded `.csg` export, so they
**require the engine** — and when it is missing, or the tree contains a node outside
the modelled set (`hull`, `minkowski`, extrudes, imports…), the file block carries an
`unsupported` entry naming the rule and the reason. **A rule that could not run is an
entry, never an absence.**

Tier-2 findings carry **line 0**: the tree is constant-folded, so no source line
exists to name — the message describes the geometry instead.

### `csg-coincident-face`

- **Predicate:** a `difference()` cutter sharing a face plane with its minuend,
  exactly — planes are cube faces and cylinder caps, transformed through the
  accumulated `multmatrix` by the inverse-transpose, canonicalized (unit normal,
  orientation-normalized, rounded at 1e-9 for float representation of the folded
  literals), and compared for set intersection. Zero epsilon on the literals is the
  point: the folded tree has the author's exact numbers.
- **Rationale:** FAILURE-MODES entry 2; skills/openscad-authoring rule 3. OpenSCAD
  itself documents coincident faces as undefined behavior and has no static
  diagnostic — the manual's own remedy is "make the cuts a little bit larger".
- **Real example:** a bore cut with `h = plate_t` from `z = 0` fires twice (both cap
  planes coincide); the taught `-1`/`+2` overshoot lints clean.

### `csg-difference-order`

- **Predicate:** a `difference()` whose first child's analytic volume is smaller than
  a later child's. Volumes are exact for cubes, polyhedra, and ideal
  cylinders/spheres, scaled by `|det M|`; union/group volumes are the **sum** of
  children — an upper bound when children overlap — so the verdict is
  upper-bound-vs-upper-bound and the finding says so.
- **Rationale:** skills/openscad-authoring rule 2 — the first child is the material;
  the wrong order is a different part, sometimes an empty one.
- **Real example:** the skill's rule-2-before block fires; its after-form is clean.
