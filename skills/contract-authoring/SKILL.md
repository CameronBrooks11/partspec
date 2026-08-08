---
name: contract-authoring
description: Write a partspec contract that proves something — how to choose checks, where limits may come from, and the retrofit path for an existing part.
---

# Writing a contract that proves something

A contract is the whole interface: `partspec` evaluates exactly what you declare, and a
run is only as meaningful as the claims are. The one rule everything below serves —
promoted from the dogfood evidence (`docs/PLAN.md`, "the load-bearing qualification"):

> **Geometry is verifiable, but only against a reference the model does not contain** —
> a standard, a datasheet, a derivation, or an invariant. Every payoff in the dogfood
> record came from such a claim; a "unit test" asserting what the model produced last
> time would have passed on every broken part in `docs/FAILURE-MODES.md`, because each
> was a faithful render of its own source.

This is also why `partspec measure` will never write checks for you
(`SPEC-contract.md` §6): a check generated from the part's own output is a check nobody
decided, asserting that the model matches itself.

## 1. Choosing checks — the decision table

Navigate by what you need to prove; the kind vocabulary itself is normative in
`SPEC-contract.md` §4.1–4.7 (do not learn it from here — this table only routes you).

| you need to prove | reach for | notes |
|---|---|---|
| the declared inputs are mutually sane | `p.param` / `p.requires` (§4.1) | runs before any engine; milliseconds |
| the part fits / fills a space | `p.envelope`, `p.keep_out`, `p.keep_in` (§4.2, §4.4) | both tiers, exact |
| the part is one sound solid | `p.watertight`, `p.solid_count` (§4.2) | both tiers |
| holes exist — and stay holes | `p.genus` (§4.2) | a hole reaching the boundary is a notch — FAILURE-MODES entry 3 |
| a cavity is sealed | `p.cavities` (§4.2) | an open tray is also watertight, 1 solid, genus 0 |
| a drawing callout (bore Ø, bolt circle, fillet) | `p.hole_diameter`, `p.bolt_circle`, `p.fillet_radius` (§4.5–4.7) | OCCT tier; the mesh tier refuses honestly |
| a whole interface standard | a fragment — `nema17.mount(p)`, `iso15.seat(p, n)` (§11) | one call, cited |
| material amount / wall drift over time | `p.volume`, `p.area` (§4.2) | drift shows in `diff` even while both runs pass |

## 2. `param` vs `requires` vs geometry — a worked before/after

The spec's rule (§4.1): the structured form SHOULD be preferred when the claim is a
simple bound on one named parameter, because it produces a real measurement `diff` can
track drift on. `requires` is the escape hatch for anything relational.

```python
# Before — everything crammed into requires: no measurements, nothing for diff
p.requires("wall >= 0.8")
p.requires("bore_d > 0")
p.requires("bore_d + 2 * wall <= plate_y")

# After — structured where one parameter is bounded, relational where it is not
p.param("wall", min=0.8)          # a measurement: diff sees wall drift 2.4 -> 0.9
p.param("bore_d", min=0.1)
p.requires("bore_d + 2 * wall <= plate_y")   # genuinely relational: stays requires
```

And know when NOT to reach for the parameter phase at all: a parameter claim proves the
*inputs*, never the geometry — F18 in `docs/FAILURE-MODES.md` (entry 5) is a green
report whose parameter never reached the geometry, which is why the unbound-`-D` guard
exists and why geometry claims must carry the weight.

## 3. Where may a limit come from?

In descending order of strength — and the report's `attribution` block discloses which
you used:

1. **A published standard, cited** — `iso15.bearing(608).od`, `nema17.mount(p)`. The
   number arrives as a `Referenced` value and the citation lands in
   `checks[].source`. Never retype a standard's number; even the exemplar that
   preaches this shipped a transcription error until review computed it
   (`examples/stepper-bracket/bracket.py`).
2. **A derivation from theory** — the involute-gear envelope that caught F13 was
   `teeth × pitch / 180`, derived, not measured. Write the derivation in the contract.
3. **An invariant** — topology (`genus`, `solid_count`, `cavities`) needs no numbers at
   all and catches what visual review is worst at.
4. **The design's own parameters** — legitimate ONLY as a change-detector, and say so
   in a comment (`examples/stepper-bracket/spec.py` is the worked form). A contract
   with nothing but these proves the model matches itself; the console and the
   report's `attribution` block will tell you so (`SPEC-contract.md` §6, §10).

Arithmetic on a `Referenced` value sheds the citation deliberately — a derived number
is yours. Cite the un-derived bound.

## 4. The retrofit path — contracting a part you did not model

`partspec measure` exists for exactly this (`SPEC-contract.md` §6): it dumps every
quantity the backend can honestly produce, with no verdict, so you can see the numbers
*before* deciding which are intent.

1. `partspec measure model.py:factory` — read what the part is.
2. For each number, ask: **what fixes this?** A standard → cite it (path 1 above). A
   datasheet or drawing → its number, in a comment naming the source. Nothing → do not
   assert it yet; `examples/enclosure/` shows the honest topology-only position.
3. Declare the topology you know the design requires (the invariants survive
   re-parameterisation; the numbers often do not).
4. Only then bound dimensions — from the references you found in step 2, never by
   copying step 1's output into a limit. That copy is the auto-generation the tool
   refuses to do for you, done by hand.

## 5. Keep the loop honest

- Commit a claims pin (`partspec check spec.py:part --pin claims.lock`) so a contract
  that shrinks fails with no baseline needed; re-pin only with review
  (`docs/AGENT-CONTRACT.md` §4).
- Shared claims across implementations assert **only what the requirement fixes**
  (FAILURE-MODES entry 6; `examples/bearing-block/claims.py` is the worked form).
- The worked exemplars under `examples/` are the imitation set: each README says what
  to copy and why.
