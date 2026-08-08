# Adversarial review findings — 15 agents, 10 confirmed, 0 dismissed

## W1 [blocks-release] (thesis) `requires()` coerces a non-predicate expression with `bool()`, so a violated claim reports `pass` and exits 0

**File:** `src/partspec/expr.py:127`

**Claim.** `evaluate()` ends with `return bool(result), namespace`, so any `requires` expression that is arithmetic rather than a comparison is truthiness-coerced. A one-character slip (`-` where `<=` was meant) turns a claim that is *violated by the declared parameters* into a green check, and the whole contract into `verdict: "pass"` / exit 0. Every other claim shape in the tool is guarded against claiming nothing — `Limit.__post_init__` ("a limit must constrain something"), `adjudicate()` ("this limit constrains no component…must not report pass"), `Part.topology()` ("a check that claims nothing cannot pass") — `requires` is the one unguarded one, and it is the shape SPEC-contract.md §4.1 calls "the escape hatch for anything relational", i.e. the most-used one.

**Repro.**
```sh
rm -rf /tmp/ps-repro && mkdir -p /tmp/ps-repro
cp /home/cam/repos/partspec/examples/spacer/spacer.scad /tmp/ps-repro/
cat > /tmp/ps-repro/vac.py <<'EOF'
from partspec import Part, openscad

def broken() -> Part:
    p = Part("x", openscad("spacer.scad", plate_x=60.0, plate_y=30.0,
                           plate_z=6.0, bore_d=40.0, wall=2.0))
    p.requires("bore_d + 2 * wall - plate_y")   # meant: <= , typed: -
    return p

def correct() -> Part:
    p = Part("x", openscad("spacer.scad", plate_x=60.0, plate_y=30.0,
                           plate_z=6.0, bore_d=40.0, wall=2.0))
    p.requires("bore_d + 2 * wall <= plate_y")
    return p
EOF
cd /tmp/ps-repro && /home/cam/repos/partspec/.venv/bin/partspec check vac.py:broken; echo "broken exit=$?"
cd /tmp/ps-repro && /home/cam/repos/partspec/.venv/bin/partspec check vac.py:correct; echo "correct exit=$?"
```

**Actual output.**
```
broken:
  ok   bore_d_2_wall_plate_y
  ok   builds

PASS: 2 pass
broken exit=0

correct (identical parameters, claim written as intended):
  FAIL bore_d_2_wall_plate_y — bore_d + 2 * wall <= plate_y is false with bore_d=40.0, wall=2.0, plate_y=30.0
  --   builds — not evaluated: parameter check 'bore_d_2_wall_plate_y' failed

FAIL: 1 fail, 1 skipped
correct exit=1

The report for `broken` records status "pass", operands {bore_d: 40.0, wall: 2.0, plate_y: 30.0}, detail null — the value actually computed was 14 (the violation magnitude), which is truthy. `p.requires("plate_x - 1")` on a 40 mm plate likewise reports pass.
```

**Why it matters.** This is SPEC-report.md §1.1's first named failure mode reached through a check that *looks* declared: a contract asserting nothing useful exits 0. Worse than the vacuous-green case the tool does guard, because here the claim is not merely absent — it is present, disproven by its own operands, and reported green with the operands sitting next to it. `detail` is null so nothing in the report or the human summary hints at it, and the `--quiet` JSON is internally consistent. Two-line fix: reject a non-`bool` result in `evaluate()` (or require the top-level AST node to be `Compare`/`BoolOp`/`UnaryOp(Not)`) and raise `ContractError`, which already maps to `verdict: "error"` / exit 4.

**Verifier.** I reproduced the repro verbatim (in my own scratchpad, since /tmp/ps-repro is being raced by a concurrent reviewer): `partspec check vac.py:broken` prints "PASS: 2 pass" and exits 0, while the identical contract with `<=` instead of `-` fails and exits 1. The JSON confirms status "pass", expr "bore_d + 2 * wall - plate_y", operands {bore_d:40.0, wall:2.0, plate_y:30.0}, detail null, verdict "pass".

Refutation attempts all failed. (a) Not a documented decision or known gap: SPEC-contract.md §5.1 covers only undeclared names and chained comparisons; §4.1/§5 call the shape a "predicate"; DECISIONS.md and POST-V0.md say nothing about truthiness coercion of a non-boolean result; no test covers it (the only bare-expression call in tests/ is a rejection test at tests/test_contract.py:73). (b) The "GIGO / it evaluated what was written" defence is refuted by the codebase's own doctrine: status.py:228 "a limit must constrain something", status.py:313 "a check that claims nothing must not report pass", contract.py:245 "a check that claims nothing cannot pass". requires is the only unguarded shape and is §4.1's "escape hatch for anything relational". (c) Input is plausible — a one-character typo in the tool's primary input.

I also strengthened it beyond the filing: `p.requires("1")` is accepted and yields verdict pass, status pass, operands {}, exit 0 — a check with zero operands asserting a constant, which is precisely the vacuous green status.py:313 exists to refuse. And `p.requires("plate_y - plate_y")` yields fail with the nonsense detail "plate_y - plate_y is false with plate_y=30.0", showing describe() also assumes a predicate that evaluate() never enforces.

Severity stays blocks-release: SPEC-report.md §1.1's first named failure mode, reached through a check that looks declared, in a tool whose thesis is that silence must never read as success, with a trivial fix (reject a non-bool result, or a non-Compare/BoolOp/Not top-level node, as ContractError → verdict "error", exit 4).

---

## W2 [blocks-release] (thesis) OpenSCAD parameters that name no variable in the source are dropped silently; the report's `params` block and every parameter check then describe a part that was never built

**File:** `src/partspec/engines/openscad.py:125`

**Claim.** `_define_args` emits `-D name=value` for every declared parameter without checking that `name` is a top-level variable anywhere in the include closure, and OpenSCAD accepts an unknown `-D` silently (no warning, exit 0). A misnamed parameter therefore never reaches the geometry: the engine renders with the `.scad`'s own default, while `report.params` records the contract's value and every `requires` / `param_range` check adjudicates against it. SPEC-contract.md §3 states the opposite as normative — "`params` are the single source of truth for the build… the contract wins and the report records the contract's value." Here the `.scad` wins and the report records the contract's value: the two halves of the report disagree and nothing says so.

**Repro.**
```sh
rm -rf /tmp/ps-repro && mkdir -p /tmp/ps-repro
cp /home/cam/repos/partspec/examples/spacer/spacer.scad /tmp/ps-repro/
cat > /tmp/ps-repro/ghost.py <<'EOF'
from partspec import Part, openscad

def spacer() -> Part:
    # spacer.scad's bore variable is `bore_d`; this contract calls it `bore_dia`.
    p = Part("g", openscad("spacer.scad", plate_x=40.0, plate_y=30.0,
                           plate_z=6.0, bore_dia=20.0, wall=2.0))
    p.requires("bore_dia >= 20.0")
    p.param("bore_dia", min=19.9, max=20.1)
    p.envelope(max=(40.0, 30.0, 6.0)); p.watertight(); p.solid_count(1); p.genus(1)
    return p
EOF
cd /tmp/ps-repro && /home/cam/repos/partspec/.venv/bin/partspec check ghost.py:spacer; echo "exit=$?"
cd /tmp/ps-repro && /home/cam/repos/partspec/.venv/bin/partspec measure ghost.py:spacer 2>/dev/null | grep -A3 '"volume"'
# and confirm OpenSCAD itself is silent about the unknown -D:
cd /tmp/ps-repro && /usr/bin/openscad --export-format binstl -o /dev/null -D bore_dia=20.0 -D nonsense_zzz=1 spacer.scad; echo "openscad exit=$?"
```

**Actual output.**
```
  ok   bore_dia_20_0
  ok   param:bore_dia
  ok   builds
  ok   envelope
  ok   watertight
  ok   solid_count
  ok   genus

PASS: 7 pass
exit=0

report.json: "verdict": "pass", "params": {..., "bore_dia": 20.0, ...}

measure: "volume": { "value": 6898.891440076026, "unit": "mm3", "exactness": "exact" }
  plate(40x30x6) minus a d=8 bore  = 6898.407 mm3   <-- matches
  plate(40x30x6) minus a d=20 bore = 5315.044 mm3
So the built part has the .scad's default 8 mm bore, not the contracted 20 mm.

openscad -D bore_dia=20.0 -D nonsense_zzz=1 spacer.scad -> no WARNING/ERROR, openscad exit=0
```

**Why it matters.** This is the unsupported-as-pass mode at the input boundary: the parameter phase, which SPEC-report.md §4 calls "the fully engine-neutral core", is evaluated against numbers with zero causal connection to the artifact the geometry phase measured, and the two are stitched into one green report. It lands squarely on the adoption path SPEC-contract.md §7 advertises ("how do I retrofit contracts onto 30 existing OpenSCAD libraries") — guessing a parameter name on an unfamiliar `.scad` is the expected authoring error, and an agent doing it gets exit 0 plus a `params` block that reads as authoritative provenance. No v0 geometry check can catch it (bore diameter is `unsupported` on the mesh tier by design), and OpenSCAD emits no diagnostic, so partspec is the only layer that can. It is not recorded in POST-V0.md or DECISIONS.md. The information needed is already in hand: `include_closure()` (openscad.py:319) resolves every source file, so scanning them for top-level assignments and raising `ContractError` on a `-D` name that matches none would close it; at minimum the report should carry the set of parameters that bound to nothing rather than silently absorbing them.

**Verifier.** I ran the repro verbatim and it reproduces exactly as described.

1. `cd /tmp/ps-repro && /home/cam/repos/partspec/.venv/bin/partspec check ghost.py:spacer` → `ok bore_dia_20_0`, `ok param:bore_dia`, `ok builds`, `ok envelope`, `ok watertight`, `ok solid_count`, `ok genus`; `PASS: 7 pass`; exit=0. report.json has `"verdict": "pass"` and `params: {plate_x:40.0, plate_y:30.0, plate_z:6.0, bore_dia:20.0, wall:2.0}`.
2. `partspec measure ghost.py:spacer` → volume 6898.891440076026 mm3.
3. Control I added (not in the original repro), which nails causality: the same contract with the correct name (`sed 's/bore_dia/bore_d/g' ghost.py > real.py`) measures 5318.071055574132 mm3. So 6898.89 is the .scad's own default d=8 bore — the contract's 20.0 never reached the geometry, while the report records it as the build's parameter.
4. Both engines are silent about the unbound -D: /usr/bin/openscad (2021.01) and ~/Applications/openscad/OpenSCAD-nightly.AppImage (2026.08.01) both exit 0 with `-D nonsense_zzz=1` and emit no WARNING/ERROR. partspec is therefore the only layer that can catch it.

Why I could not refute it:
- Not a recorded decision. I grepped all of docs/ for `unknown param|misnam|-D |typo|no such variable|bind`: the only hits are SPEC-contract.md §3.1, SPEC-backend.md line 153 and DECISIONS.md D12, all of which merely describe the -D mechanism. POST-V0.md §7 "Smaller items" and §8 do not mention it; DECISIONS.md D1-D17 do not.
- It contradicts normative text. SPEC-contract.md §3: "`params` are the single source of truth for the build. They are what parameter checks evaluate against, what is recorded in `report.params` … the contract wins and the report records the contract's value." Here the .scad wins the build and the contract wins the report — the exact inversion.
- Not hypothetical input. A misnamed parameter is the canonical authoring error on the retrofit path SPEC-contract.md §7 advertises, and the sibling engine treats it as fatal: pycad.py:142 catches the `TypeError` from `factory(**source.params)` and returns a `BuildError`. The same mistake is a hard fail on build123d and a silent green on OpenSCAD.
- The stated consequence follows: the parameter phase (SPEC-report.md §4's "fully engine-neutral core") adjudicated `requires("bore_dia >= 20.0")` and `param("bore_dia", min=19.9, max=20.1)` against a number with no causal connection to the measured artifact, and both halves were stitched into one green report with nothing flagging it.

Severity kept at blocks-release: exit 0 plus a `params` block that reads as authoritative provenance for a part that was never built, triggered by a plausible typo, on a tool whose stated thesis is that silence must never read as success — and the information needed is already resolved by `include_closure()` (src/partspec/engines/openscad.py:319).

One scoping caveat that does not change the verdict: the suggested fix (scan the closure for top-level assignments and raise) needs care around variables assigned only inside modules or introduced by `include`, so the safe version may be "record unbound parameters in the report / fail on them" rather than a naive syntactic scan. The defect stands either way.

---

## W3 [blocks-release] (mesh) volume/center_of_mass precondition is necessary but not sufficient: an inward-oriented closed mesh yields a negative (or inflated) "exact" volume that greens a max-bound check

**File:** `src/partspec/backends/mesh.py:354`

**Claim.** `_not_a_solid` gates `volume` and `center_of_mass` on closed + `is_winding_consistent`, but consistent winding does not imply outward winding. A closed mesh wound uniformly inward passes the gate, and the divergence-theorem sum returns a signed number that is not a volume — reported `exactness: exact`, and `p.volume(max=...)` passes on it. trimesh's own `is_volume` predicate (which the backend already surfaces as `is_valid`) returns False on exactly these meshes, so the backend has the correct answer in hand and ignores it.

**Repro.**
```sh
rm -rf /tmp/psA && mkdir -p /tmp/psA && cat > /tmp/psA/inv.scad <<'EOF'
polyhedron(
  points=[[0,0,0],[10,0,0],[10,10,0],[0,10,0],[0,0,10],[10,0,10],[10,10,10],[0,10,10]],
  faces=[[3,2,1,0],[0,1,5,4],[4,5,6,7],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
);
EOF
cat > /tmp/psA/spec.py <<'EOF'
from partspec import Part, openscad

def blk() -> Part:
    p = Part("inverted-block", openscad("inv.scad"))
    p.watertight()
    p.solid_count(1)
    p.volume(max=1200.0)
    return p
EOF
PARTSPEC_OPENSCAD=/usr/bin/openscad /home/cam/repos/partspec/.venv/bin/partspec check /tmp/psA/spec.py:blk; echo "EXIT=$?"
PARTSPEC_OPENSCAD=/usr/bin/openscad /home/cam/repos/partspec/.venv/bin/partspec measure /tmp/psA/spec.py:blk | grep -A4 '"volume"'
# and the plausible-positive variant (true material volume 7000, one polyhedron, cavity shell wound the wrong way):
rm -rf /tmp/psA2 && mkdir -p /tmp/psA2 && cat > /tmp/psA2/mixed.scad <<'EOF'
outer = [[0,0,0],[20,0,0],[20,20,0],[0,20,0],[0,0,20],[20,0,20],[20,20,20],[0,20,20]];
inner = [[5,5,5],[15,5,5],[15,15,5],[5,15,5],[5,5,15],[15,5,15],[15,15,15],[5,15,15]];
polyhedron(points=concat(outer, inner),
  faces=[[0,1,2,3],[4,5,1,0],[7,6,5,4],[5,6,2,1],[6,7,3,2],[7,4,0,3],
         [8,9,10,11],[12,13,9,8],[15,14,13,12],[13,14,10,9],[14,15,11,10],[15,12,8,11]]);
EOF
cat > /tmp/psA2/spec.py <<'EOF'
from partspec import Part, openscad

def enc() -> Part:
    p = Part("cavity-enclosure", openscad("mixed.scad"))
    p.volume(min=6500.0, max=7500.0)
    return p
EOF
PARTSPEC_OPENSCAD=/usr/bin/openscad /home/cam/repos/partspec/.venv/bin/partspec measure /tmp/psA2/spec.py:enc | grep -A4 '"volume"'
```

**Actual output.**
```
  ok   builds
  ok   watertight
  ok   solid_count
  ok   volume

PASS: 4 pass
  /tmp/psA/outputs/spec-blk/report.json
EXIT=0
    "volume": {
      "value": -1000.0,
      "unit": "mm3",
      "exactness": "exact"
    },

(same report also carries "is_valid": false, and center_of_mass is emitted as exact)

Second variant (true volume 7000):
    "volume": {
      "value": 9000.0,
      "unit": "mm3",
      "exactness": "exact"
    },
  with "is_valid": true, "watertight": true

Identical output under PARTSPEC_OPENSCAD=$HOME/Applications/openscad/OpenSCAD-nightly.AppImage (2026.08.01); both engines exit 0 on the source.
```

**Why it matters.** This is failure mode two of SPEC-report.md 1.1 verbatim — a quantity that is not a volume reported as a conclusive volume — and it produces a green exit 0, the outcome the whole tool exists to prevent. SPEC-backend.md 5.1.1 and D17 state the precondition as "closed and consistently wound", which the mesh satisfies; the mathematics needs outward orientation, so spec and code share the same hole. A reversed `polyhedron()` face list is among the most common OpenSCAD authoring mistakes and OpenSCAD exits 0 on it, so this is the exact class of silent breakage partspec advertises catching. The 9000-vs-7000 variant shows it is not limited to obviously-absurd negatives: it yields a plausible positive number that would satisfy a differently-toleranced contract. The fix is one predicate the backend already reads for `is_valid` (`mesh.is_volume`, i.e. add a positive-signed-volume term to `_not_a_solid`).

**Verifier.** I ran the repro verbatim and it reproduces exactly as filed, on both engines.

PRIMARY CLAIM — CONFIRMED.
`PARTSPEC_OPENSCAD=/usr/bin/openscad .venv/bin/partspec check /tmp/psA/spec.py:blk` →
```
  ok   builds
  ok   watertight
  ok   solid_count
  ok   volume

PASS: 4 pass
EXIT=0
```
`measure` on the same part:
```
"volume":  { "value": -1000.0, "unit": "mm3", "exactness": "exact" }
"is_valid": { "value": false,  "unit": "bool", "exactness": "exact" }
"watertight": true, "solid_count": 1, "genus": 0
```
Identical under `PARTSPEC_OPENSCAD=$HOME/Applications/openscad/OpenSCAD-nightly.AppImage` (2026.08.01) — volume -1000.0, is_valid false, exit 0 — so it is not a 2021.01/CGAL quirk; the Manifold backend preserves the inversion too.

The mechanism is exactly as described. Probing the exported STL directly:
`.venv/bin/python -c "import trimesh; m=trimesh.load_mesh('/tmp/psA/outputs/spec-blk/inv.stl'); print(m.volume, m.is_winding_consistent, m.is_watertight, m.is_volume)"`
→ `-1000.0 True True False`
So `_not_a_solid` (src/partspec/backends/mesh.py:354) passes — closed and `is_winding_consistent` — while trimesh's `is_volume`, which the same file already reads at line 173 for the `is_valid` diagnostic, says False. The backend has the correct answer in hand and does not consult it.

THE PREMISE HOLDS. `/usr/bin/openscad -o direct.stl inv.scad` exits 0 with no warning at all (only the facet summary). A reversed `polyhedron()` face list is a real, common hand-authoring mistake that OpenSCAD renders silently — this is not an input the tool never receives nor an environment nobody has.

NOT A RECORDED DECISION. I checked before confirming. `docs/SPEC-backend.md` §5.1.1 line 191 states the precondition as "closed **and** consistently wound"; `docs/DECISIONS.md` D17 (dated 2026-08-05, written to close precisely this class after dogfood F14) enumerates "open, non-manifold or inconsistently wound" and never mentions orientation. `grep -rn -i "orient|inward|outward|is_volume" docs/` returns nothing on point. `docs/POST-V0.md` does not defer it. `tests/test_mesh_backend.py:410` covers *inconsistent* winding only. So spec and code share the hole; the behaviour is neither deliberate nor a documented gap. D17's stated goal is met for three defect classes and missed for the fourth.

WHY BLOCKS-RELEASE (the claimed severity stands). This is `SPEC-report.md` §1.1 failure mode two literally: a quantity that cannot be evaluated reported as conclusive, flagged `exact`, producing a green exit 0. For a tool whose entire and only thesis is "silence must never read as success," a reproducible false green with a one-predicate fix is release-blocking. The `is_valid: false` signal exists but is deliberately excluded from the check vocabulary (mesh.py:162-173), so nothing in `check` output dissents — the operator sees four greens.

WHERE THE FINDING OVERREACHES (does not change the verdict, but the parent should know).
1. The second variant is the weak half. `volume` reports 9000.0 there, but the reporter's "true material volume 7000" is only one of three defensible readings of two nested outward-wound shells: even-odd gives 7000, nonzero-winding gives 8000, the divergence sum gives 9000. 9000 is the volume of no point set, which is arguably its own defect — but it is not the defect described.
2. More importantly, the reporter's proposed one-line fix does not cover variant 2. I checked: `trimesh.load_mesh('/tmp/psA2/outputs/spec-enc/mixed.stl')` gives `volume 9000.0, is_volume True, is_winding_consistent True`. Adding `mesh.is_volume` to `_not_a_solid` closes variant 1 and leaves variant 2 open.
3. The `center_of_mass` sub-claim is technically true (emitted `exact`) but toothless in both repros — (5,5,5) and (10,10,10) are the correct centroids by symmetry.
4. The realistic blast radius is narrower than "any volume check": a uniformly inward-wound closed mesh always yields a *negative* sum, so it greens `volume(max=...)` but loudly fails any `volume(min=...)`. The false green requires a one-sided upper bound — which is still a perfectly ordinary "material budget" contract.

Net: the core defect is real, reproduced by me on both engines, undocumented, and squarely the thing the tool exists to prevent. Refuting it would require me to ignore an exit-0 green on a -1000 mm3 "exact" volume.

---

## W4 [should-fix] (mesh) solid_count counts surface shells, not solids: a sealed internal cavity reports 2 (exact) where the OCCT tier reports 1, and it falsely blocks genus

**File:** `src/partspec/backends/mesh.py:203`

**Claim.** `_face_components`/`_body_count` partitions faces by shared-edge adjacency, which counts boundary *shells*, not bodies. A single solid with an enclosed void has two disjoint shells, so `solid_count` returns 2 flagged `exact` for a one-solid part, and `genus` then refuses with the factually wrong reason "this part has 2 solids" — a quantity that is perfectly well defined (0) on a mesh that is closed, manifold and consistently wound.

**Repro.**
```sh
rm -rf /tmp/psB && mkdir -p /tmp/psB && cat > /tmp/psB/enclosure.scad <<'EOF'
difference() {
  cube([20,20,20], center=true);
  cube([10,10,10], center=true);
}
EOF
cat > /tmp/psB/spec.py <<'EOF'
from partspec import Part, openscad

def enc() -> Part:
    p = Part("sealed-enclosure", openscad("enclosure.scad"))
    p.watertight()
    p.solid_count(1)
    p.genus(0)
    return p
EOF
PARTSPEC_OPENSCAD=/usr/bin/openscad /home/cam/repos/partspec/.venv/bin/partspec check /tmp/psB/spec.py:enc; echo "EXIT=$?"
/home/cam/repos/partspec/.venv/bin/python -c "
from build123d import Box
from partspec.backends.occt import OcctBackend
b=OcctBackend(); s=Box(20,20,20)-Box(10,10,10)
print('OCCT solid_count', b.solid_count(s).value, '| OCCT genus', b.genus(s).value)"
```

**Actual output.**
```
  ok   builds
  ok   watertight
  FAIL solid_count
  n/a  genus — genus is defined per body; this part has 2 solids (check solid_count first, or split the part)

FAIL: 2 pass, 1 fail, 1 unsupported
  /tmp/psB/outputs/spec-enc/report.json
EXIT=1
OCCT solid_count 1 | OCCT genus 0

report.json for the solid_count check:
  "status": "fail", "measurement": {"value": 2, "unit": "count", "exactness": "exact"}, "limit": {"equals": 1}

(volume in the same report is 7000.0, i.e. the mesh is correct — only the count is wrong. Identical under the 2026.08.01 nightly.)
```

**Why it matters.** SPEC-contract.md 4.2 lists `solid_count` and `genus` as available on *both* tiers, and SPEC-backend.md 7 makes tier agreement a normative testing obligation ("one contract, evaluated identically wherever it can be"). Here the same design gives 2 on mesh and 1 on OCCT, so the same contract cannot be ported between engines — and the mesh answer is simply wrong: a sealed enclosure, a potted cavity, a trapped void from any `difference()` is one solid. The number is emitted `exact`, which under SPEC-report.md means conclusive. It also over-refuses `genus` with a false justification, which D17 part 2 explicitly argues against ("Unsupported only means anything if it is reserved for questions that genuinely have no answer") — the genus of this closed one-body surface is well defined and computable. Both an off-by-shell body count and a fabricated refusal reason are in the class of defect the tool positions itself against. Distinguishing shells from bodies needs a containment/orientation test (each shell's signed volume gives it directly: outer shells positive, cavity shells negative), not a change to the component algorithm, which I verified correct against a union-find reference on 400 randomized adjacency graphs with 0 mismatches.

**Verifier.** Ran the finding's repro verbatim and got byte-identical output: `FAIL solid_count` with `{"value": 2, "unit": "count", "exactness": "exact"}` against `equals: 1`, and `genus` refused with "this part has 2 solids", while the OCCT tier on the same design returns solid_count 1 / genus 0.

Verified the mechanism independently at /home/cam/repos/partspec/src/partspec/backends/mesh.py: the exported STL is watertight=True, winding_consistent=True, volume=7000.0, with (0 boundary, 0 non-manifold) edges, so `_bodies_undetermined` passes and `_face_components` partitions the 24 triangles into the outer shell and the cavity shell — `_body_count` returns 2 for a part that is one solid. The number is therefore emitted `exact`, i.e. conclusive under SPEC-report.md, and it is factually wrong.

The cross-tier divergence is structural, not incidental: occt.py:138 returns `len(a.solids())` (bodies) whereas mesh.py:226 returns surface components (shells); occt.py:163 computes `genus = shells - (v-e+2f-w)/2` and so already carries the shell term (2 - 4/2 = 0), while mesh.py:259 uses the single-shell `(2 - chi)/2` which would give -1 here. The reporter's claim that genus is well defined (0) for this closed one-body part is confirmed by the tool's own OCCT formula.

Grounds for refutation I checked and rejected: (1) Not a recorded decision — D17 and SPEC-backend.md 5.1.1 discuss only non-manifold edges and openness as preconditions; neither DECISIONS.md, POST-V0.md nor any spec section mentions shells vs bodies or an enclosed cavity. (2) The specs point the other way — SPEC-contract.md 4.2 lists solid_count and genus on both tiers and SPEC-backend.md 7 makes tier agreement a normative MUST, so the same contract cannot be ported between engines. (3) Not exotic input — a difference() that traps a void is an everyday CAD pattern, reproduced in four lines of SCAD, identical on both OpenSCAD builds. (4) The genus over-refusal with a fabricated reason is precisely what D17 part 2 argues against.

One correction to the reporter's framing that does not change the verdict: manifold3d's decompose() also returns 2 (and genus -1) on this mesh, so the pre-D17 implementation had the same bug — this is long-standing, not a D17 regression. The defect stands on the tier disagreement and the semantics of "solid", not on a library reference.

Severity should-fix rather than blocks-release: it emits a wrong `exact` measurement and an over-refusal, but it fails loudly with exit 1 rather than producing the false green the tool exists to prevent.

---

## W5 [blocks-release] (engines) OpenSCAD engine silently discards parameters the source does not accept — report goes fully green while recording params that never reached the build

**File:** `src/partspec/engines/openscad.py:207`

**Claim.** `render()` throws away OpenSCAD's stderr whenever the exit code is 0, so `WARNING: variable <name> not specified as parameter` — the engine explicitly reporting that a contract parameter was ignored — is dropped; the part builds from its own defaults, every geometry check is evaluated against that part, and the report records the contract's parameters as though they drove the build. The same silence occurs on the default `-D` path, where OpenSCAD emits no warning at all. The Python tier hard-fails on the identical mistake (`pycad.build` turns the `TypeError` into a `BuildError`), so this is an engine-specific hole, not a shared limitation.

**Repro.**
```sh
rm -rf /tmp/psr2 && mkdir -p /tmp/psr2 && cd /tmp/psr2
cat > spacer.scad <<'EOF'
module spacer(plate_x = 40, plate_y = 30, plate_z = 6, bore_d = 8) {
    difference() {
        cube([plate_x, plate_y, plate_z], center = true);
        cylinder(h = plate_z + 2, d = bore_d, center = true, $fn = 64);
    }
}
EOF
cat > spec.py <<'EOF'
from partspec import Part, openscad

def spacer() -> Part:
    # The module's parameter is `bore_d`; the contract misspells it.
    p = Part("typo-spacer", openscad("spacer.scad", method="spacer",
                                     plate_x=40.0, plate_y=30.0, plate_z=6.0,
                                     bore_diameter=20.0))
    p.requires("bore_diameter + 2 * 2.0 <= plate_y")
    p.envelope(max=(40.0, 30.0, 6.0))
    p.watertight(); p.solid_count(1); p.genus(1)
    return p
EOF
/home/cam/repos/partspec/.venv/bin/partspec check spec.py:spacer; echo "EXIT=$?"
/home/cam/repos/partspec/.venv/bin/python -c "
import json;d=json.load(open('outputs/spec-spacer/report.json'))
print('verdict:',d['verdict'],'| params recorded:',d['params'])"
# what OpenSCAD said, and partspec dropped:
cp spacer.scad probe.scad
printf 'spacer(plate_x = 40.0, plate_y = 30.0, plate_z = 6.0, bore_diameter = 20.0);\n' >> probe.scad
/usr/bin/openscad --export-format binstl -o /dev/null probe.scad 2>&1 | grep -i warning
# the real bore, measured:
/home/cam/repos/partspec/.venv/bin/partspec measure spec.py:spacer | grep -A2 '"volume"'
```

**Actual output.**
```
  ok   bore_diameter_2_2_0_plate_y
  ok   builds
  ok   envelope
  ok   watertight
  ok   solid_count
  ok   genus

PASS: 6 pass
  /tmp/psr2/outputs/spec-spacer/report.json
EXIT=0
verdict: pass | params recorded: {'plate_x': 40.0, 'plate_y': 30.0, 'plate_z': 6.0, 'bore_diameter': 20.0}
WARNING: variable bore_diameter not specified as parameter in file probe.scad, line 7
    "volume": {
      "value": 6898.891440076026,

Volume 6898.89 mm3 is a Ø8 bore (7200 - pi*4^2*6); a Ø20 bore would be 5314.7. Both /usr/bin/openscad (2021.01) and the 2026.08.01 nightly emit the same WARNING and both exit 0. The `-D` variant is equally green: same directory, `spec_d.py` + `flat.scad` with top-level `bore_d=8` and contract param `bore_diameter=20.0` -> "PASS: 3 pass / EXIT=0". For contrast, the identical typo on build123d gives "FAIL builds - calling make_part(**params) failed: make_part() got an unexpected keyword argument 'bore_diameter'", EXIT=3.
```

**Why it matters.** SPEC-contract.md 3.1 states params "are the single source of truth for the build ... the contract wins and the report records the contract's value." Here the contract does not win — the source's defaults do — and the report asserts otherwise with `verdict: pass`. Every check in that report is a true statement about a part nobody asked for, presented as verification of the part that was asked for. It is SPEC-report.md 1.1's vacuous green in its most dangerous form: not an empty contract, but a fully-populated one whose inputs were discarded. A renamed parameter in an upstream OpenSCAD library (exactly the F13 drift class the closure work exists to catch) reverts a part to defaults and partspec reports green, while the engine's own diagnosis of the problem sits in a stderr string that `render()` reads and then drops.

**Verifier.** I ran the repro verbatim and it reproduces exactly. `partspec check /tmp/psr2/spec.py:spacer` -> "PASS: 6 pass", EXIT=0; report.json -> `verdict: pass | params: {'plate_x': 40.0, 'plate_y': 30.0, 'plate_z': 6.0, 'bore_diameter': 20.0}`; `partspec measure` -> volume 6898.891440076026, which is 40*30*6 - pi*4^2*6, i.e. the source's default Ø8 bore (a Ø20 bore gives 5315.1). The contract's bore_diameter=20.0 never reached the build. On the throwaway copy partspec itself generates, /usr/bin/openscad prints `WARNING: variable bore_diameter not specified as parameter in file probe.scad, line 7` and the 2026.08.01 nightly prints the quoted-name variant; both exit 0 and both partspec runs are green. The -D variant (flat.scad + spec_d.py) is also green, EXIT=0, with params recording bore_diameter=20.0 and no warning emitted at all. The build123d contrast holds once the target syntax is corrected to build123d("model.py", method="make_part", ...) -- the reporter's "model:make_part" form actually fails at target resolution ("source not found"), but the corrected form yields exactly the claimed `FAIL builds - calling make_part(**params) failed: make_part() got an unexpected keyword argument 'bore_diameter'`, EXIT=1.

Refutation attempts all failed. (1) Not a recorded decision: grep for warning/not specified/unknown param/discard across docs/DECISIONS.md (D1-D17) and docs/POST-V0.md turns up nothing on point; D13 concerns --summary, POST-V0 §8 concerns sys.modules staleness. (2) The code confirms the mechanism: `_first_error_line()` (src/partspec/engines/openscad.py:225) exists precisely to surface OpenSCAD's own ERROR/WARNING lines, but is only called on the two failure branches (lines 210 and 218); on returncode == 0 proc.stderr is read and dropped. (3) The report has no warnings channel -- top-level keys are checks, counts, engine, environment, error, geometry, hint, invocation, params, part, schema_version, tool, verdict, and error/hint are populated only on failure. (4) It does not require exotic input: a misspelled param, or an upstream .scad renaming a parameter while the contract is untouched -- the F13 drift class, uncatchable in v0 since diff is post-v0. (5) The consequence follows: `p.requires("bore_diameter + 2 * 2.0 <= plate_y")` evaluated 24 <= 30 as ok against a value that never entered the geometry, and envelope/watertight/solid_count/genus are true statements about a part nobody asked for, presented as verification of the part that was asked for. That contradicts SPEC-contract.md §3 ("params are the single source of truth for the build ... the contract wins and the report records the contract's value") and instantiates SPEC-report.md §1.1's vacuous green.

Severity blocks-release stands: this is the project's central thesis (silence must never read as success) failing on the engine that is half its engine coverage, with the engine's own diagnosis available in a string the code already reads.

---

## W6 [blocks-release] (engines) CadQuery multi-body result is silently truncated to its first solid — `solid_count(1)` and `envelope` pass, flagged exact, on a two-body part

**File:** `src/partspec/engines/pycad.py:77`

**Claim.** `adopt()` reduces a CadQuery `Workplane` with `.val()`, which returns `self.objects[0]` — the FIRST stack entry, not all of them. The docstring's premise ("a multi-solid stack is already a Compound by then") is false for the standard `combine=False` multi-body idiom, which leaves several `Solid` objects on the stack. Every downstream measurement then describes one body of an N-body part, and the OCCT backend labels all of them `exact=True`.

**Repro.**
```sh
rm -rf /tmp/psr && mkdir -p /tmp/psr && cd /tmp/psr
cat > two_bodies.py <<'PY'
import cadquery as cq

def make_part():
    # Two 10 mm cubes, 30 mm apart. combine=False leaves both on the stack.
    return cq.Workplane("XY").pushPoints([(0, 0), (30, 0)]).box(10, 10, 10, combine=False)
PY
cat > spec_cq.py <<'PY'
from partspec import Part, cadquery

def twobody() -> Part:
    p = Part("two-bodies", cadquery("two_bodies.py"))
    p.solid_count(1)                     # "did it come out in one piece"
    p.envelope(max=(10.0, 10.0, 10.0))   # true envelope is 40 x 10 x 10
    p.watertight()
    return p
PY
/home/cam/repos/partspec/.venv/bin/partspec check spec_cq.py:twobody; echo "EXIT=$?"
/home/cam/repos/partspec/.venv/bin/python -c "
import sys; sys.path.insert(0,'/tmp/psr')
import cadquery as cq
from two_bodies import make_part
v = make_part().vals()
c = cq.Compound.makeCompound(v)
bb = c.BoundingBox()
print('bodies:', len(v), '| volume:', round(c.Volume(),3), '| bbox:', (round(bb.xlen,1), round(bb.ylen,1), round(bb.zlen,1)))
"
```

**Actual output.**
```
  ok   builds
  ok   solid_count
  ok   envelope
  ok   watertight

PASS: 4 pass
  /tmp/psr/outputs/spec_cq-twobody/report.json
EXIT=0
--- ground truth from CadQuery itself:
bodies: 2 | volume: 2000.0 | bbox: (40.0, 10.0, 10.0)

report.json records solid_count {"value": 1, "unit": "count", "exactness": "exact"} and envelope {"value": [10.0, 10.0, 10.0], "exactness": "exact"}. Volume is likewise 1000.0 instead of 2000.0 (a p.volume(min=1900,max=2100) claim fails against the half-part). Direct check: .venv/bin/python -c "import cadquery as cq; from partspec.engines.pycad import adopt; w=cq.Workplane('XY').pushPoints([(0,0),(30,0)]).box(10,10,10,combine=False); print(len(w.objects)); a=adopt(w); print(type(a).__name__, len(a.solids()), a.volume)" -> "2 / Solid 1 999.9999999999998".
```

**Why it matters.** `solid_count` is the check whose entire job is answering "did this part come out as one piece", and here it answers 1 on a part that is two disconnected bodies 30 mm apart — reported as an exact measurement, not `approximate` and not `unsupported`. That is SPEC-report.md 1.1's third failure mode inverted: not a degraded measurement sold as conclusive, but a measurement of a *different, smaller object* sold as conclusive. It also silently defeats D3's premise that adoption is "a handle rewrap ... no conversion, no copy, no loss" (SPEC-backend.md 4) — the loss here is half the part. The existing regression test `tests/test_occt_backend.py:48 test_cadquery_multi_solid_adopts_as_a_compound` misses it because it builds the compound by hand (`adopt(cq.Compound.makeCompound(w.vals()))`) instead of handing `adopt()` the Workplane, and because its `combine=True` workplane happens to carry a single Compound on the stack.

**Verifier.** I ran the repro verbatim and it behaves exactly as filed.

`cd /tmp/psr && /home/cam/repos/partspec/.venv/bin/partspec check spec_cq.py:twobody` →
```
  ok   builds
  ok   solid_count
  ok   envelope
  ok   watertight

PASS: 4 pass
  /tmp/psr/outputs/spec_cq-twobody/report.json
EXIT=0
```
Ground truth from CadQuery on the same model: `bodies: 2 | volume: 2000.0 | bbox: (40.0, 10.0, 10.0)`. The emitted report.json records `solid_count {"value": 1, "unit": "count", "exactness": "exact"}` and `envelope {"value": [10.0,10.0,10.0], ..., "exactness": "exact"}` with `"verdict": "pass"`, `"engine": {"kind":"cadquery", "adopted_via":"wrapped"}`. So the tool asserts, as an *exact* measurement, that a two-body part 40 mm across is one solid inside a 10 mm cube.

Mechanism confirmed directly at src/partspec/engines/pycad.py:77 (`obj = obj.val()`):
```
stack objects: 2
Solid solids: 1 volume: 999.9999999999998
```
The docstring premise "a multi-solid stack is already a Compound by then" is false. I checked the scope of that premise with a second probe: it holds only for the default `combine=True` path (`combine=True stack: 1 ['Compound']` → `adopt` yields 2 solids, volume 250, correct). It fails for at least two ordinary multi-body idioms — `combine=False` (`stack: 2 ['Solid','Solid']` → adopt gives 1 solid) and `.add()` (`add() stack: 2 ['Solid','Solid']` → `adopt add(): Solid 1 124.99…`, half the volume). These are standard CadQuery, not contrived input.

Refutation checks I ran, all negative:
- Not a recorded decision or known gap. `grep -i "val()\|stack\|multi\|compound\|truncat" docs/POST-V0.md` returns only two unrelated hits about the source closure and MCP server. D3 and SPEC-backend.md §4 say the opposite of the behaviour observed — adoption is "lossless", "a handle rewrap … no conversion" — so this is a spec/code divergence, and the spec's own §4 caveat list (volume/center_of_mass on non-solids must be `Unsupported`) does not cover it.
- Not hypothetical or unreachable input: the CLI path is the one users take, and `solid_count` exists precisely to answer "did this come out in one piece".
- The consequence follows: this is not a degraded measurement sold as conclusive (SPEC-report.md 1.1 failure mode 3) but a measurement of a strictly smaller object sold as `exact`, producing exit 0 — worse than the vacuous green the tool's thesis is built to prevent, because the contract *did* assert the right things and was told they held.
- The reporter's account of why the existing regression test misses it is accurate: tests/test_occt_backend.py:48 calls `adopt(cq.Compound.makeCompound(w.vals()))`, pre-compounding by hand, and its workplane is the `combine=True` case that already carries a single Compound.

Severity stands at blocks-release: silent, green, `exact`-labelled, on ordinary input, against the tool's stated core guarantee.

---

## W7 [blocks-release] (contract) A contract that raises writes no report, so the previous run's `verdict: "pass"` stays on disk as the current answer

**File:** `src/partspec/cli.py:93`

**Claim.** `_cmd_check` resolves the target *before* `write_placeholder`, so every contract-level error (import-time raise → exit 64, factory-time raise → exit 4) returns without writing any report — leaving the prior run's report.json, verdict `pass`, at the deterministic path. SPEC-report.md §5.1 makes this a MUST ("A report MUST be written on every terminal outcome, including `error`") and names this exact outcome "the worst failure in the system: the file is stale but reads as current, and both a human and an agent will trust it." §7.1 additionally requires that an error report still list every declared check as `skipped`. `tests/test_cli.py:146` covers the exit code for precisely this scenario (a mistyped keyword argument) but never asserts a report was written, which is why it passes.

**Repro.**
```sh
S=/tmp/ps-f1; rm -rf $S; mkdir -p $S
cp /home/cam/repos/partspec/examples/spacer/spacer.scad $S/
cat > $S/spec.py <<'EOF'
from partspec import Part, openscad

def spacer() -> Part:
    p = Part("f1-spacer", openscad("spacer.scad", plate_x=40.0, plate_y=30.0,
                                   plate_z=6.0, bore_d=8.0, wall=2.0))
    p.envelope(max=(40.0, 30.0, 6.0))
    p.watertight()
    return p
EOF
export PARTSPEC_OPENSCAD=/usr/bin/openscad
cd /home/cam/repos/partspec
.venv/bin/partspec check $S/spec.py:spacer --out $S/out --quiet; echo "run1 exit=$?"
.venv/bin/python -c "import json;print('verdict =',json.load(open('$S/out/report.json'))['verdict'])"
# author mistypes a keyword argument (the scenario in tests/test_cli.py:146)
sed -i 's/max=/maks=/' $S/spec.py
.venv/bin/partspec check $S/spec.py:spacer --out $S/out --quiet; echo "run2 exit=$?"
ls $S/out
.venv/bin/python -c "import json;print('verdict =',json.load(open('$S/out/report.json'))['verdict'])"

# variant: raise at import time instead -> exit 64, also no report
# (add a module-level `Part("", openscad("spacer.scad"))` to $S/spec.py)
```

**Actual output.**
```
run1 exit=0
verdict = pass

partspec: the contract raised TypeError: Part.envelope() got an unexpected keyword argument 'maks'
  the contract is wrong, not the part
run2 exit=4
report.json  spacer.stl
verdict = pass        <-- stale, written by run 1; mtime unchanged

Import-time variant (module-level `Part("", openscad("spacer.scad"))`):
  partspec: contract raised on import: ContractError: a part needs an id
  exit=64
  report.json verdict = pass   (still stale)
Note the import-time variant also exits 64, which SPEC-report.md §6.2 reserves for "usage error: unresolvable target, bad arguments" — target.py:69 wraps every exec_module exception in TargetError, so an identical ContractError exits 64 from module scope and 4 from inside the factory.
```

**Why it matters.** This is the failure the whole write-semantics section exists to prevent, and the one `write_placeholder` was built for — but the placeholder is written after target resolution, so the entire class of contract errors bypasses it. In CI the exit code is non-zero, but the artifact is what downstream consumers read (D5: "the report schema plus the exit code is the contract"), and it says the part passed. An agent in a repair loop, a dashboard, or a human opening report.json after a broken run all get a green answer about a contract that was never evaluated. The report carries no `environment.timestamp` either (§7's schema lists one; `report.py:_environment` never emits it), so nothing in the artifact reveals it is stale.

**Verifier.** I ran the repro verbatim and it reproduces exactly, including on the default (no --out) deterministic path, which is the realistic dogfood case.

Run 1 (`/home/cam/repos/partspec/.venv/bin/partspec check $S/spec.py:spacer --quiet`): exit 0, report at `$S/outputs/spec-spacer/report.json` with `verdict=pass`, `counts={'total':3,'pass':3,...}`.
Run 2 after `sed -i 's/max=/maks=/'`: stderr `partspec: the contract raised TypeError: Part.envelope() got an unexpected keyword argument 'maks'`, exit 4, and report.json is unchanged with `verdict=pass` — mtime identical before and after (`2026-08-05 22:55:03.340659701`) in the --out variant. Import-time variant (module-level `Part("", openscad("spacer.scad"))`): `partspec: contract raised on import: ContractError: a part needs an id`, exit 64, report.json still `verdict = pass`, mtime unchanged.

The mechanism is as claimed: `/home/cam/repos/partspec/src/partspec/cli.py:93` calls `_resolve_or_report` before `write_placeholder` (cli.py:99), so every contract-level raise returns an exit code without ever touching the report path. Exit 4 is `exit_code(Verdict.ERROR)` — a terminal outcome with verdict `error` — and docs/SPEC-report.md §5.1 is unambiguous: "A report MUST be written on every terminal outcome, including `error`. A run that crashes and leaves the previous report in place is the worst failure in the system: the file is stale but reads as current, and both a human and an agent will trust it." §5.2 requires the placeholder before the engine runs, and src/partspec/report.py:265's own docstring restates the rationale. This is a divergence from a normative MUST, not taste.

I checked the escape hatches and none apply. docs/POST-V0.md's deferred items do not include this (§8 is in-process batch model-cache staleness, a different thing). docs/DECISIONS.md records nothing permitting it. `tests/test_cli.py:146` (`test_a_contract_that_raises_does_not_exit_as_a_failing_part`) asserts only the exit code, never that a report was written, which is why the suite is green.

The consequence follows: the out dir is computable without resolving the target (`_out_dir` uses `Target.parse`, not `resolve`), so writing the placeholder first is feasible — this is an ordering bug, not a constraint. D5 makes the report artifact half the contract, and the artifact says the part passed a contract that was never evaluated. I also confirmed the supporting detail: SPEC-report.md:470 lists `environment.timestamp` in the schema, but the emitted `environment` is `{'python','packages','platform','duration_ms'}` — no timestamp — so nothing inside the artifact reveals it is stale.

One honest narrowing that does not change the verdict: the import-time variant's exit 64 is arguably spec-permitted, since §6.2 says "`64` is reserved for failures that produce no reports at all." The clean violation is the exit-4 factory-raise path. (That an identical ContractError exits 64 from module scope and 4 from inside the factory — target.py:69 wrapping every exec_module exception in TargetError — is a real inconsistency but a separate, lesser point.)

Severity: blocks-release stands. The tool's thesis is that silence must never read as success, and this leaves a green artifact at a deterministic path for the single most common authoring error the project has already hit in real use.

---

## W8 [should-fix] (contract) A NaN measurement adjudicates as a conclusive `pass`, and the report it lands in is not valid JSON

**File:** `src/partspec/status.py:236`

**Claim.** `_satisfies_scalar` compares with `<` / `>`, both of which are False for NaN, so a NaN value satisfies any `min`, `max` or range and `adjudicate` returns `Status.PASS` with `exactness: "exact"` — a quantity that could not be evaluated reported as conclusively within bounds, which is SPEC-report.md §1.1's "unsupported-as-pass". It holds per-component for vector limits too. Separately, `report.py:_write_json` calls `json.dump` without `allow_nan=False`, so the emitted file contains the bare token `NaN`, which is not valid JSON per RFC 8259: `JSON.parse` and Go's `encoding/json` reject the report outright (jq and Python accept it).

**Repro.**
```sh
S=/tmp/ps-f2; rm -rf $S; mkdir -p $S
cp /home/cam/repos/partspec/examples/spacer/spacer.scad $S/
cat > $S/spec.py <<'EOF'
import json
from partspec import Part, openscad

# a parameter that arrived as NaN: json.loads accepts the NaN token, and
# pandas yields NaN for a blank cell in a parameter table
CFG = json.loads('{"plate_z": NaN}')

def spacer() -> Part:
    p = Part("f2-spacer", openscad("spacer.scad", plate_x=40.0, plate_y=30.0,
                                   plate_z=CFG["plate_z"], bore_d=8.0, wall=2.0))
    p.param("plate_z", min=1.0, max=6.0)
    return p
EOF
export PARTSPEC_OPENSCAD=/usr/bin/openscad
cd /home/cam/repos/partspec
.venv/bin/partspec check $S/spec.py:spacer --out $S/out; echo "exit=$?"
grep -n -A3 '"value": NaN' $S/out/report.json
node -e "try{JSON.parse(require('fs').readFileSync('$S/out/report.json','utf8'))}catch(e){console.log('node JSON.parse:',e.message)}"

# unit level, including the vector path:
.venv/bin/python -c "
from partspec.status import Measurement, Limit, adjudicate
print('scalar NaN vs [1,6] ->', adjudicate(Measurement(float('nan'),'mm'), Limit(min=1.0,max=6.0)))
print('vector NaN comp     ->', adjudicate(Measurement((40.0,float('nan'),6.0),'mm',axes=('x','y','z')), Limit(max=(40.0,30.0,6.0))))"
```

**Actual output.**
```
  ok   param:plate_z
  ok   builds

PASS: 2 pass
exit=0

51:        "value": NaN,
52-        "unit": "mm",
53-        "exactness": "exact",

node JSON.parse: Unexpected token 'N', ..."plate_z": NaN,\n    ""... is not valid JSON

scalar NaN vs [1,6] -> pass
vector NaN comp     -> pass
```

**Why it matters.** Two independent breaks of the product surface in one run. On the status axis: the tool's entire thesis is that a quantity it cannot evaluate must never read as green, and here a not-a-number is reported as `pass` / `exactness: "exact"` / verdict `pass` / exit 0 — a conclusive claim about a value that does not exist. There is no non-finite guard anywhere in `Measurement.__post_init__`, `adjudicate`, or `param()`. On the schema axis: SPEC-report.md §7 declares the JSON artifact the contract, and any consumer outside Python/jq cannot parse a report containing a non-finite float at all — including the future `diff` if it is ever written in anything else, and any CI step that pipes the report through a strict parser. Note the circularity: a report partspec writes with `NaN` in it feeds straight back into a contract via `json.loads`, which accepts it.

**Verifier.** Ran the reporter's repro verbatim and got an exact match: `partspec check /tmp/ps-f2/spec.py:spacer` printed `ok param:plate_z`, `PASS: 2 pass`, `exit=0`, and report.json line 51 contains `"value": NaN` with `"exactness": "exact"`. Node's JSON.parse rejects the file (`Unexpected token 'N'`). Unit level also matched: `adjudicate(Measurement(nan,'mm'), Limit(min=1.0,max=6.0)) -> pass` and the vector-component case -> pass.

I added three independent confirmations the reporter did not run. (1) Go's encoding/json rejects the report: `invalid character 'N' looking for beginning of value`. (2) `jq -r '.checks[0].measurement.value'` returns `null` — jq does not merely "accept" it, it silently substitutes a different value, which is worse for a consumer. (3) The JSON-validity half has a second trigger that is entirely independent of the NaN-pass half: a contract with `plate_z=float("inf")` adjudicates CORRECTLY as `FAIL ... outside min=1.0, max=6.0`, exit 1, and the emitted report still contains bare `Infinity` at lines 22 and 43 and is rejected by node. So `report.py:254` `json.dump(payload, fh, indent=2)` without `allow_nan=False` is a defect on its own, not a downstream symptom.

Checked for a prior decision as required. `grep -rniE 'nan|non-finite|nonfinite|infinit|allow_nan|isfinite' docs/ src/ tests/` returns nothing about non-finite floats; docs/POST-V0.md does not list it. The nearest recorded decision, D17 (docs/DECISIONS.md:480, dated 2026-08-05, prompted by dogfood F14), argues the opposite way: it is the same failure class the project just fixed for meshes (a quantity with no defined answer reported as `exact`), and its "refusal is as narrow as the mathematics allows" carve-out does not cover this, because comparing NaN to an interval has no mathematical answer at all — `pass` is a claim the tool manufactures rather than a narrow refusal avoided.

Code confirms the claimed absence of any guard: status.py:236 `_satisfies_scalar` uses only `<`/`>`, both False for NaN; `Measurement.__post_init__` validates only bounds-iff-approximate and axes-iff-vector; contract.py:139 `param()` validates the parameter NAME against `source.params` and never the value.

Cannot be refuted as "input the tool never receives": params flow from arbitrary user Python at a trust boundary, and the `Infinity` variant requires no contrived construction. Also worth noting the report's `params` block claims `plate_z: NaN` while `scad_literal` emitted `plate_z=nan` to OpenSCAD, which is an undefined identifier there — so the report additionally misdescribes what was actually rendered, though I am not counting that as part of the finding.

Severity: `should-fix` as filed is correct, not blocks-release. A non-finite has to enter through the contract; the mesh backend itself is well guarded (`_not_a_solid` gates volume and center_of_mass), so this does not fire spontaneously on sound inputs. But SPEC-report.md section 7 makes the JSON artifact the contract, and the emitted artifact is currently unparseable by every strict RFC 8259 consumer while jq quietly coerces the value to null.

---

## W9 [should-fix] (release) A stale STL from a previous run is measured as if it were this run's build — green report, exit 0, on geometry that was never produced

**File:** `src/partspec/engines/openscad.py:214`

**Claim.** `render()` writes to the fixed path `out_dir/<stem>.stl` (line 165) and never removes it before invoking the engine, so its own guard `if not stl.is_file() or stl.stat().st_size == 0` (line 214) — added precisely because "OpenSCAD exits 0 on some degenerate input while writing nothing useful, so the artifact is checked rather than the exit code trusted" — is satisfied by the *previous* run's mesh. OpenSCAD 2021.01 exits 0 when it cannot write the target file, so a run that produced nothing reports `builds: pass` and every geometry check is computed from the old artifact, yielding a fresh, internally consistent, green report describing a part that no longer exists.

**Repro.**
```sh
set -e
rm -rf /tmp/ps-stale && mkdir -p /tmp/ps-stale
printf 'difference(){ cube([40,30,6]); translate([20,15,-1]) cylinder(h=8,d=8,$fn=64); }\n' > /tmp/ps-stale/w.scad
cat > /tmp/ps-stale/spec.py <<'EOF'
from partspec import Part, openscad
def widget() -> Part:
    p = Part("widget", openscad("w.scad"))
    p.envelope(max=(40.0, 30.0, 6.0)); p.genus(1); p.watertight(); p.solid_count(1)
    return p
EOF
cd /home/cam/repos/partspec
.venv/bin/partspec check /tmp/ps-stale/spec.py:widget 2>&1 | tail -3
chmod 444 /tmp/ps-stale/outputs/spec-widget/w.stl
printf 'cube([400,300,60]);\n' > /tmp/ps-stale/w.scad
.venv/bin/partspec check /tmp/ps-stale/spec.py:widget; echo "EXIT=$?"
.venv/bin/python -c "import json;d=json.load(open('/tmp/ps-stale/outputs/spec-widget/report.json'));print(d['verdict'], d['part']['source_digest'][:22]);[print(' ',c['id'],c['status'],c.get('measurement')) for c in d['checks']]"

# minimal variant, no chmod, showing the guard is inoperative on any second run:
#   PARTSPEC_OPENSCAD=/bin/true .venv/bin/partspec check /tmp/ps-stale/spec.py:widget   -> PASS, exit 0
#   PARTSPEC_OPENSCAD=/bin/true .venv/bin/partspec check /tmp/ps-stale/spec.py:widget --out /tmp/fresh -> FAIL builds "openscad exited 0 but produced no geometry", exit 1
```

**Actual output.**
```
Run 1 (correct 40x30x6 part with a bore): `PASS: 5 pass`, exit 0.
Run 2, after the source was replaced by a bare `cube([400,300,60])` (no bore, 10x oversize, grossly violating every declared limit):

```
  ok   builds
  ok   envelope
  ok   genus
  ok   watertight
  ok   solid_count

PASS: 5 pass
  /tmp/ps-stale/outputs/spec-widget/report.json
EXIT=0
```

The freshly written report:

```
pass sha256:60e55c8854c49fe      <- digest of the NEW source
  builds pass None
  envelope pass {'value': [40.0, 30.0, 6.0], 'unit': 'mm', 'exactness': 'exact', 'axes': ['x','y','z']}
  genus pass {'value': 1, 'unit': 'count', 'exactness': 'exact'}
  watertight pass {'value': True, ...}
  solid_count pass {'value': 1, ...}
```

Measurements are of the previous mesh (envelope 40x30x6, genus 1) while `part.source_digest` is the new source's. Direct confirmation that the engine exits 0 here: `openscad --export-format binstl -o <read-only>.stl w.scad` -> `rc=0`, file unchanged.

Also confirmed by the `--out` pair in the repro: identical invocation, fresh directory -> `FAIL builds — openscad exited 0 but produced no geometry`, exit 1; warm directory -> `PASS`, exit 0.
```

**Why it matters.** This is the tool's own thesis failing in the tool. SPEC-report.md 1.1 names "silence must never read as success" as the one property everything else serves, and 5.1 argues at length that "a run that crashes and leaves the previous report in place is the worst failure in the system: the file is stale but reads as current." That reasoning was implemented for the stale *report* (the error placeholder) and not for the stale *mesh* — and the mesh is what every geometry check is computed from, so the failure is strictly worse: the report is genuinely fresh, genuinely internally consistent, and green, while describing an artifact this run never produced. It also defeats the provenance layer that 8.3 builds up: `source_digest` records the new source against the old geometry, so a future `diff` comparing two such reports concludes "the source changed and the geometry did not" — the exact silent-drift class F13 exists to catch. Nothing in POST-V0.md or DECISIONS.md D1-D17 records artifact freshness as a known gap; the code comment at line 213 shows the author believed the case was already handled. Fix is one line: unlink the target before invoking the engine (or render to a fresh temp path and move it into place).

**Verifier.** Ran the filed repro verbatim. Run 2, after replacing the source with cube([400,300,60]), printed "PASS: 5 pass", EXIT=0, and the freshly written report.json carries source_digest sha256:4c9d0e58... (the NEW source) alongside envelope [40.0,30.0,6.0] and genus 1 (the OLD mesh) — green on geometry that run never produced. Verified the engine behaviour directly: /usr/bin/openscad --export-format binstl -o <read-only>.stl w.scad prints "Can't open file ... for export" and exits rc=0 with the file unchanged. Verified the structural claim: grep -rn "unlink" src/partspec/ shows only the scratch .scad is removed (openscad.py:222); the STL target at line 165 is never removed, so the line-214 guard is satisfied by the prior run's artifact on every warm run. The /bin/true variant reproduces with no chmod: warm dir -> PASS exit 0, --out /tmp/ps-fresh -> FAIL builds exit 1.

Refutation angles checked and failed: (1) Not a recorded decision — nothing in DECISIONS.md D1-D17 or POST-V0.md covers artifact freshness, and SPEC-report.md 5.1 argues the opposite. Pointedly, report.py:260 writes the report atomically via tmp+rename while the mesh path gets no such care. (2) Not self-defending in the realistic permission case only partly — chmod-ing the whole output dir read-only fails loudly with PermissionError on the report tmp file, exit 1, so it takes an individually unwritable STL.

Where the finding overreaches is trigger realism, which is why I downgrade severity rather than confirm blocks-release. I probed both installed engines (2021.01 and the 2026.08.01 nightly) for a natural exit-0-without-writing input and found none: square([10,10]), text(), circle(), group(), if(false) cube(1), cube([0,0,0]), and an empty difference() all exit 1 with no file written; degenerate polyhedra and self-intersecting solids exit 0 but do write. So the reachable triggers today are an externally chmod'd artifact or a PARTSPEC_OPENSCAD pin to a binary that isn't OpenSCAD — not something an ordinary contract produces. It is still a genuine defect and not hypothetical: the guard the author wrote specifically because "the exit code is not trusted" is dead on every re-run, which is the tool's normal iterate-and-recheck usage mode, and the deliberate no-validation policy for the engine pin (the OSError comment) explicitly leans on that guard to catch a bogus engine. Fix is one line: unlink the target before invoking, or render to a temp path and move it into place.

---

## W10 [should-fix] (release) The advertised `cadquery` extra cannot work: it omits build123d, and the install crashes with an uncaught traceback exiting 1 (partspec's code for "the part failed its contract")

**File:** `pyproject.toml:28`

**Claim.** `cadquery = ["cadquery>=2.8,<3"]` declares no dependency on build123d, but the CadQuery path runs through the OCCT backend, whose adopt shim does `import build123d as bd` (src/partspec/engines/pycad.py:48). A wheel installed as `partspec[cadquery]` therefore cannot check any CadQuery part: it dies with an unhandled `ModuleNotFoundError` that escapes `runner.run()` (which catches only `ContractError`), printing a raw traceback and exiting **1** — the exit code SPEC-report.md 6.2 reserves for "something asserted was disproven", while the report left on disk says `verdict: "error"`. The other documented route, `partspec[occt,cadquery]`, reproduces the OCP clobber that pyproject.toml's own comment claims to have fixed, because `[tool.uv] override-dependencies` is a workspace setting that is not carried in wheel metadata.

**Repro.**
```sh
# A: the cadquery extra alone
set -e
rm -rf /tmp/ps-dist /tmp/ps-cq /tmp/ps-cqprobe; mkdir -p /tmp/ps-cqprobe
cd /home/cam/repos/partspec && uv build --out-dir /tmp/ps-dist >/dev/null
uv venv --quiet /tmp/ps-cq
cd /tmp/ps-cqprobe && uv pip install -q --no-config --python /tmp/ps-cq/bin/python "/tmp/ps-dist/partspec-0.1.0-py3-none-any.whl[cadquery]"
cat > /tmp/ps-cqprobe/model.py <<'EOF'
import cadquery as cq
def make():
    return cq.Workplane("XY").box(10, 10, 10)
EOF
cat > /tmp/ps-cqprobe/spec.py <<'EOF'
from partspec import Part, cadquery
def part() -> Part:
    p = Part("cqbox", cadquery("model.py", method="make"))
    p.watertight()
    return p
EOF
/tmp/ps-cq/bin/partspec check /tmp/ps-cqprobe/spec.py:part; echo "EXIT=$?"

# B: both OCCT extras together, from the same wheel, outside the repo
uv venv --quiet /tmp/ps-ocp
cd /tmp && uv pip install --no-config --python /tmp/ps-ocp/bin/python "/tmp/ps-dist/partspec-0.1.0-py3-none-any.whl[occt,cadquery]"
/tmp/ps-ocp/bin/python /home/cam/repos/partspec/scripts/check_ocp.py; echo "guard EXIT=$?"
/tmp/ps-ocp/bin/python -c "import cadquery"
```

**Actual output.**
```
A:
```
  File "/tmp/ps-cq/lib/python3.14/site-packages/partspec/engines/pycad.py", line 48, in _shape_map
    import build123d as bd
ModuleNotFoundError: No module named 'build123d'
EXIT=1
```
(`partspec measure` on the same target fails identically. The only artifact left is the pre-engine placeholder: `"verdict": "error"`, `"checks": []`, `"counts.total": 0` — so the exit code says `fail` while the report says `error`.)

B:
```
  cadquery-ocp 7.9.3.1.1
  cadquery-ocp-novtk 7.9.3.1.1
ERROR: multiple OCP providers installed. Both own the top-level OCP/ package, so one has silently clobbered the other.
guard EXIT=1

ImportError: cannot import name 'IVtkOCC_Shape' from 'OCP.IVtkOCC'
VTK not installed
```
Running a CadQuery contract in that env yields `FAIL builds — model raised on import: ImportError: cannot import name 'IVtkOCC_Shape'`, exit 1.

(For contrast, `partspec[mesh]` from the same wheel installs and runs cleanly: `/tmp/.../wheelenv/bin/partspec check examples/spacer/spec.py:spacer` -> `PASS: 8 pass`, exit 0, matching the README transcript exactly.)
```

**Why it matters.** README.md advertises `cadquery` as one of three optional extras and puts CadQuery in its engine table as a supported engine ("adopted into the build123d backend via `.wrapped` — same kernel, no conversion"), and AGENTS.md states the OCP landmine is closed by the uv override plus `just ocp-guard`. Neither holds for anything installed from the distribution: the override is a `[tool.uv]` workspace key absent from wheel metadata, and `scripts/check_ocp.py` is not shipped in the wheel (confirmed via `unzip -l`, 20 files, no `scripts/`), so an installed user has no guard at all. Because `just setup` installs all extras and CI runs only that, no job in the matrix exercises either broken combination — the `mesh-only` job proves exactly one extra works and the OCCT extras are proven nowhere. Minimum fix: add `build123d` to the `cadquery` extra (it is a hard import of the code path), and either fold `cadquery-ocp` into the extras' declared dependencies or run the `check_ocp` assertion at OCCT-backend import time so the clobber surfaces as a named error instead of an upstream ImportError. Separately, `runner.run()` should catch non-`ContractError` exceptions and produce `verdict: error` / exit 4 rather than letting a traceback exit 1 — cli.py's `_resolve_or_report` docstring already spells out why that conflation is unacceptable, but only the target-resolution path implements it.

**Verifier.** Reproduced every claim verbatim. (A) `uv pip install "partspec-0.1.0-py3-none-any.whl[cadquery]"` then `partspec check` on a CadQuery part dies with `ModuleNotFoundError: No module named 'build123d'` at pycad.py:48, EXIT=1 — and critically this is NOT wheel-only: `UV_PROJECT_ENVIRONMENT=/tmp/ps-syncq uv sync --extra cadquery --no-dev` from the clone produces the identical crash, so the README-documented per-engine extra install is broken in the supported clone workflow too. `uv sync --extra occt --extra cadquery` from the clone works (PASS: 2 pass, exit 0), which isolates the missing `build123d` declaration in pyproject.toml:28 as the whole defect. (B) `uv pip install ...whl[occt,cadquery]` reproduces the OCP clobber: check_ocp.py reports both cadquery-ocp and cadquery-ocp-novtk 7.9.3.1.1, and `import cadquery` fails with `ImportError: cannot import name 'IVtkOCC_Shape' from 'OCP.IVtkOCC'` — confirming `[tool.uv] override-dependencies` is not carried in wheel metadata. (C) The exit-code conflation is real and broader than CadQuery: a bare wheel install running the mesh example dies on `import trimesh`, EXIT=1, while the placeholder report on disk says verdict=error, checks=[], counts.total=0. SPEC-report.md 6.2 reserves 1 for `fail` ("something asserted was disproven") and 4 for `error`; cli.py:71-78's docstring names this exact conflation as unacceptable but the guard is only wired into `_resolve_or_report`, never around `runner.run()`, which catches only ContractError. Checked DECISIONS.md, POST-V0.md, PLAN.md and SPEC-backend.md: neither the incomplete extra nor the uncaught-exception exit code is recorded as a decision or known gap — PLAN.md:234 and AGENTS.md:118-121 assert the OCP landmine is closed, which is false for anything installed from the distribution. Severity correction from blocks-release to should-fix: no wheel is published (README: "Not on PyPI yet"), `just setup`/`uv sync --all-extras` (what CI runs) works, and the failure is loud rather than a false green, which is the project's actual release-blocking category. It is a genuine, one-line-fixable packaging defect plus a real spec divergence in the exit code, and becomes release-blocking the moment a wheel ships.

---
