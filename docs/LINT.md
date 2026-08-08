# partspec lint — the tier-1 rules

**Status:** v1 · 2026-08-08 · closes #26 (tier 1)
**Scope:** `partspec lint <source>…` over `.scad` and `.py` model sources. Findings are
**advisory and never a verdict on the part — it is about the source** (#26, verbatim):
exit 0 says the lint ran, the findings are data in the JSON payload, and 64 is reserved
for inputs that cannot be linted at all. Tier 1 runs **without an engine installed**.

Each rule states its exact predicate — a lint whose rules are vibes teaches nothing —
plus the rationale and a real example. The rule registry in `src/partspec/lint.py` and
this document are held together by test (`tests/test_lint.py`).

## `scad-unused-top-level`

- **Predicate:** a top-level variable (per the same `top_level_variables` walk the
  `-D` guard uses, `include`s included) whose name appears nowhere in the
  noise-stripped source outside its own assignment lines. `$`-variables are exempt —
  the engine reads them.
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

## `scad-module-size`

- **Predicate:** a `module` whose body spans more than 40 lines (brace-matched, over
  the noise-stripped source).
- **Rationale:** the LoC symptom head-on — the observed failure is bloat, and a module
  past feature-size has stopped being a feature (skills/openscad-authoring rule 5).
- **Real example:** the corpus's gear library concentrates its geometry in one
  ~100-line body ([corpus]; the fixture in `tests/test_lint.py` reproduces the shape).

## `py-magic-number`

- **Predicate:** a numeric `Constant` with `|value| > 2` inside a `Call`'s arguments
  within any function body (stdlib `ast`; defaults in the signature are exactly where
  numbers SHOULD live and are never flagged; module-level constants likewise).
- **Rationale:** skills/build123d-authoring rule 1 — hoist it to a parameter with a
  default.
- **Real example:** `Box(40, 30, 4)` inside a factory — the bd skill's rule-3 block
  carries them deliberately (it is a *before* block).

## `py-function-size`

- **Predicate:** a function whose body spans more than 60 lines.
- **Rationale:** same as `scad-module-size`, Python spelling.
- **Real example:** community models are commonly one monolithic script promoted to a
  function ([corpus], F8).

## Tier 2 — deferred, with its survey obligation

The geometry-dependent rules (`coincident-face epsilon`, `difference()` ordering over
the engine's constant-folded `.csg` tree) are NOT half-present: nothing in the
registry claims them, so their absence cannot read as a clean bill. They land as a
separate slice (#118) that MUST first answer the audit's prior-art question — *does an
existing OpenSCAD static analyser or `.csg` reader beat hand-rolling one?* — per the
repo's own absorb-vs-depend standard (D7, D12), and whose rules MUST report
`unsupported` rather than silence when the engine is missing.
