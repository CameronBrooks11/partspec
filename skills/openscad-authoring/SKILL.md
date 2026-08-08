---
name: openscad-authoring
description: Write OpenSCAD an agent loop can verify — parameterise, build from datums, decompose, pin $fn, overshoot booleans, and know the traps the dogfood corpus actually hit.
---

# Writing OpenSCAD that survives verification

The observed symptom this skill attacks (`notes/GAPS.md` A1–A7): agent-written OpenSCAD
is bloated, hardcoded, and structurally broken in ways that render fine. Every rule
below is concrete and checkable, carries a worked before/after, and cites the failure
it prevents in `docs/FAILURE-MODES.md`. The fenced examples are executed by
`tests/test_docs.py` — they build, and the after-forms satisfy what they claim.

## Rule 1 — Parameterise at the top; a magic number in geometry is unnameable

A `-D` override can only bind a **top-level variable** (a module-local assignment
shadows it). A `-D` whose name the file never declares is accepted without a whisper —
OpenSCAD just injects a top-level value that matters only if something happens to read
it — which is why partspec refuses any `-D` matching no declared top-level variable
(FAILURE-MODES entry 5).
A number buried in a call can never be overridden, checked by a `param` claim, or
named in a report.

```scad
// rule-1-before — nothing here can be driven or checked from outside
cube([60, 40, 4]);
```

```scad
// rule-1-after — every design decision has a name a contract can reach
plate_w = 60;
plate_d = 40;
plate_t = 4;

cube([plate_w, plate_d, plate_t]);
```

A parameter's *meaning* must match its name: `od_608 = 22.5` — a fit allowance baked
into a constant named for a nominal dimension — is entry 4 in the catalogue, found
twice in the corpus from two different authors.

## Rule 2 — First child of `difference()` is the material; everything after is removed

The single most destructive ordering trap, because the wrong order is not an error —
it is a *different part*. When anything at all survives the backwards subtraction,
OpenSCAD renders it happily at exit 0: a plausible mesh of the wrong thing. The one
variant the engine itself catches is the fully-empty result ("Current top level
object is empty.", exit 1, no STL) — do not count on being that lucky.

```scad
// rule-2-before — the cutter is the first child, so the PLATE is subtracted
// from the CUTTER. Fully empty here, which OpenSCAD refuses at export
// (exit 1); leave any sliver surviving and it renders fine, exit 0
difference() {
    translate([20, 15, 1]) cylinder(d = 6, h = 2, $fn = 48);
    cube([40, 30, 4]);
}
```

```scad
// rule-2-after — material first, removals after
plate_w = 40;
plate_d = 30;
plate_t = 4;
bore_d = 6;
facets = 48;  // rule 4: $fn is a named top-level parameter, like everything else

difference() {
    cube([plate_w, plate_d, plate_t]);
    translate([plate_w / 2, plate_d / 2, -1])
        cylinder(d = bore_d, h = plate_t + 2, $fn = facets);
}
```

partspec relays the empty-result refusal as a build failure; for the exit-0 variants —
a sliver of cutter rendered as if it were the part — only a `genus` / `solid_count` /
`envelope` claim proves the *right* subtraction happened.

## Rule 3 — Overshoot every cutter; never end a boolean on a coincident face

A cutter that stops exactly at a surface leaves coincident faces, and coincident
geometry is where render backends disagree: the corpus's 2,212-star library produced
**4 non-manifold edges under the default backend while OpenSCAD reported
`Status: NoError`** (FAILURE-MODES entry 2 — two shells touching along one plane). The
idiom is `-1` under, `+2` over, as in rule 2's after-form: start the cutter below the
material and end it above. The same rule applies to `union()`: solids that meet at a
face — and entry 2's evidence IS two shells touching under union — should overlap by a
small epsilon, not merely touch. Zero cost, removes the entire failure class from your
own booleans. (It cannot fix a library's internal coincidences — that is what
`p.watertight()` under both render backends is for.)

## Rule 4 — Pin `$fn` where curvature meets a claim

Under D15 the measurand is the artifact as exported: a `cylinder($fn=16)` **is** a
16-gon prism, and its bolt clearance is the apothem, not the radius
(`docs/SPEC-report.md` §1.1 — error always in the unsafe direction). Left unpinned,
tessellation follows the `$fa`/`$fs` defaults — so it varies with feature SIZE and
with the engine version, and a claim written against one part quietly measures
another. Pin it at the top, as a named parameter, sized to the claim:

```scad
// rule-4-before — facet count is whatever $fa/$fs resolve to for this size
cylinder(d = 6, h = 4);
```

```scad
// rule-4-after — the facet count is a named, driveable design decision
facets = 48;

cylinder(d = 6, h = 4, $fn = facets);
```

The claim-sizing precedent: the Ø22.5-seat finding (entry 4) pinned
`$fn=180` so a 0.003 mm polygon error could not be confused with the 0.5 mm
divergence under test.

## Rule 5 — Decompose into modules at feature boundaries, and locate from datums

A module per feature keeps every feature's parameters adjacent to its geometry, and
locating features from a named datum — not from accumulated `translate` chains —
means one design change moves one number.

```scad
// rule-5-after — features are modules, located from the plate's own frame
plate_w = 40;
plate_d = 30;
plate_t = 4;
bore_d = 6;
facets = 48;

module plate() {
    cube([plate_w, plate_d, plate_t]);
}

module bore(x, y) {
    translate([x, y, -1]) cylinder(d = bore_d, h = plate_t + 2, $fn = facets);
}

difference() {
    plate();
    bore(plate_w / 2, plate_d / 2);
}
```

Split a **file** when a module acquires its own parameter block that the rest of the
file never reads — and know that `include <>` files join the part's identity:
partspec's `source_closure` digests every file the render reads, because editing a
helper three levels down changes the part while the entry file's hash does not.

## Rule 6 — Prefer explicit geometry to `hull()` / `minkowski()` where a claim exists

Both are legitimate; both *manufacture* surfaces no parameter names, which makes the
result hard to claim (what is the envelope of a hull? whatever it turned out to be —
which is entry-4 territory the moment you measure it and assert the answer). Use them
for genuinely emergent shapes; for fillets and rounded plates whose radius is a
design parameter, model the radius explicitly so the number exists to check —
`minkowski` against a sphere also multiplies facet counts, which is a render-time
cost, not a correctness one.

## The language moves — pin the binary, avoid removed constructs

`assign()` was removed, and modern OpenSCAD *ignores* unknown modules — their children
never render. A gear library lost its teeth to exactly this, both versions exiting 0
with clean watertight meshes (FAILURE-MODES entry 1, the catalogue's opening case).
Never use deprecated constructs; pin the engine with `PARTSPEC_OPENSCAD`; and write
the envelope claim from theory so the version that breaks the part fails the check.

---

Contract-side guidance is `skills/contract-authoring/SKILL.md`; the evidence base is
`docs/FAILURE-MODES.md`; worked parts are under `examples/` (the `enclosure` and
`bearing-block` exemplars are OpenSCAD).
