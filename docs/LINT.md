# partspec lint — the rules

**Status:** v2 · 2026-08-09 · closes #26 (tier 1) and #118 (tier 2)
**Scope:** `partspec lint <source>…` over `.scad` and `.py` model sources. Findings are
**advisory and never a verdict on the part — it is about the source** (#26, verbatim):
exit 0 says the lint ran, the findings are data in the JSON payload, and 64 is reserved
for inputs that cannot be linted at all. The payload (schema 2) is per-file
blocks — `{file, digest, findings[, unsupported]}` — so a clean file is a visible entry with the
sha256 of the bytes that were linted, not an absence; duplicate arguments are deduped
(#120). **Tier 1** runs without an engine installed; **tier 2** (the two `csg-*` rules)
reads OpenSCAD's constant-folded `.csg` export and refuses by name when the binary is
absent.

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

- **Predicate:** a numeric literal with `|value| > 2` on any line that is not an
  assignment or an `include`/`use`, in the noise-stripped source. (Any assignment, at
  any depth — not only top-level ones, which is what this said until v2; `x = 50;`
  inside a module body is exempt.) Two further positions are exempt because the
  literal is already named or is not a dimension at all: a **parameter default** in a
  `function`/`module` signature, scalar or vector (`module post(h = 40)`,
  `module plate(size = [60, 40, 4])`), and an **integer subscript index**
  (`type[3][0]`). The
  exemption is deliberate: 0/1/2 are structure, and the `-1`/`+2` boolean-overshoot
  idiom (skills/openscad-authoring rule 3) must not be flagged by the tool whose own
  skills teach it.
- **Rationale:** a magic number is unnameable — by `-D`, by `param`, by a report
  (skills/openscad-authoring rule 1).
- **Real example:** `cube([60, 40, 4]);` — the openscad skill's rule-1-before block,
  three findings; its after-form lints clean.
- **Wrapping does not change the answer.** The exemption belongs to the statement, not
  to one line of it, so `plate = [60, 40, 4];` and the same assignment spread over four
  lines both lint clean. Until v0.7.0 the rule matched a line-leading `name =`, so a
  wrapped lookup table — ordinary formatting — was exempt on its first line and flagged
  on every other, three findings on a constant that has a name. The rule's own rationale
  is that a magic number is *unnameable*; the code was the defect.
- **A signature default is named by its parameter.** `function radius(i, r_min = 100)`
  and the same signature wrapped over three lines both lint clean. Until #205 only the
  wrapped form did, and for a reason worth stating exactly, because the plausible one is
  wrong: the exemption was keyed on a **line-leading `name =`**, and a declaration line
  never is one — it leads with `module` or `function`. A wrapped signature's continuation
  line *is* (`    r_min = 100`), which is the whole of why the rare form escaped and the
  common one was flagged. Paren depth was not the cause: it fed only the multi-line
  assignment opener, never the exemption, so advancing it earlier changes nothing
  (measured, byte-identical output — #205's suggested remedy, recorded on the issue). **A vector default is the whole bracket group** —
  `module plate(size = [60, 40, 4])` is clean, because a size, a position and a range
  are all spelled `[...]` in OpenSCAD. The exemption covers the DEFAULTS, not the line:
  the walk stops at the parameter list's closing paren, so a one-line module's body
  literals still fire.
- **A subscript index is structure, not a dimension.** `type[3][0]` reads field 3 of a
  registry row: no unit, unreachable by `-D`, never a `param` or a report (#206). A `[`
  following an identifier or a `]` is a subscript; a `[` opening a vector literal
  (`size = [3, 4]`) is not, and the rule applies there as before. A keyword before the
  bracket is not an identifier — `each [100, 200]` splats a vector and its literals are
  flagged. Integers only, so `v[3.5]` — a bug either way — stays visible.
- **Known noise, owned:** canonical-orientation angles (`rotate([-90, 0, 0])`, `45`,
  `360` in ranges) fire. Accept them knowingly, or name them (`quarter_turn = 90;`) —
  the advisory verdict means acceptance costs nothing. Scientific literals match as
  whole numbers (`1e-3` is 0.001, exempt; `1e6` flags).

## `scad-module-size`

- **Predicate:** a `module` whose reported span exceeds 40 lines (brace-matched, over the
  noise-stripped source). The span is counted from the `module` line, so **a body of 40
  lines reports 41 and fires** — the effective body limit is 39.
- **Known asymmetry with `py-function-size`:** that rule counts from the *first statement
  of the body*, excluding the `def` (`lint.py`'s `fn.body[0].lineno`), so a 60-line body
  reports 60 and stays **silent**. The same-sized body therefore fires here and not there.
  The limits differing (40 vs 60) is deliberate; the counting frames differing is not.
  Aligning them changes behaviour, so it is tracked separately rather than fixed in a
  documentation pass. Both boundaries are pinned by tests.
- **Rationale:** the LoC symptom head-on — the observed failure is bloat, and a module
  past feature-size has stopped being a feature (skills/openscad-authoring rule 5).
- **Real example:** the corpus's gear library concentrates its geometry in one
  ~100-line body ([corpus]; the fixture in `tests/test_lint.py` reproduces the shape).

## `py-magic-number`

- **Predicate:** a numeric `Constant` with `|value| > 2` inside a `Call`'s arguments —
  positional and keyword alike — within any `def` body (stdlib `ast`. **`async def` is not
  seen by this rule OR by `py-function-size`**: both walk for `ast.FunctionDef`, and
  `ast.AsyncFunctionDef` is not a subclass, so an async factory is silently unlinted
  however long or magic it is — a rule staying quiet about code it cannot evaluate, which
  is the failure this tool's own refusal policy forbids. Tracked. A call inside a nested
  `def` reports twice; lambda bodies are pruned; defaults in the signature
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
**require the engine** — and when it is missing, or a rule's evaluation must cross a
node outside the modelled set (`hull`, `minkowski`, extrudes, imports…), the file block
carries an `unsupported` entry naming the rule and the reason. (A node the rules never
needed to evaluate — a `hull` outside any `difference` — produces no entry: the rules
ran, and ran vacuously.) **A rule that could not run is an
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
- **Known noise, owned:** the comparison is **plane-level, not face-level** — a cutter
  cap on the right plane but outside the material's footprint, or on an interior
  joint plane of a union, fires too. Advisory means accepting those knowingly costs
  nothing; checking face overlap is a heavier geometry problem deliberately not
  taken on here.

### `csg-difference-order`

- **Predicate:** a `difference()` whose first child's analytic volume is smaller than
  a later child's. Volumes are exact for cubes, **closed** polyhedra, and ideal
  cylinders/spheres, scaled by `|det M|`; union/group volumes are the **sum** of
  children — an upper bound when children overlap — so the verdict is
  upper-bound-vs-upper-bound and the finding says so.
  A `polyhedron()` whose faces do not bound a volume — an edge with no reverse,
  or one traversed twice the same way — is **refused, not estimated** (#289):
  the divergence sum returns a number for any surface, and a number computed
  over a surface that encloses nothing is a finding invented out of nothing.
  The rule goes to `unsupported` with the edge named. Edges are matched by
  vertex **coordinate**, because the engine welds coincident vertices and a
  mesh converted from STL/OBJ shares none of its indices.
  Two limits of "exact", stated because the rule leans on the number: a closed
  but **self-intersecting** polyhedron measures the sum of its shells rather
  than the solid — an upper bound, which is all `csg-difference-order` needs,
  and the finding already says it compares upper bounds. And a **globally
  inverted** surface (every face reversed) is closed and coherently wound, so
  it is measured; the magnitude is right and the sign is discarded.
- **Rationale:** skills/openscad-authoring rule 2 — the first child is the material;
  the wrong order is a different part, sometimes an empty one.
- **Real example:** the skill's rule-2-before block fires; its after-form is clean.
- **Known noise, owned:** an idiomatic oversized cutter ("remove everything above
  z = h" as a giant box) can out-measure the material and fire on correct code; and
  a polygonized minuend (a coarse `$fn` sphere) measures below its ideal bound, so a
  true wrong order can fail to fire. Both directions follow from the stated
  upper-bound convention.
