#!/usr/bin/env python3
"""Apply the body revisions from the 2026-08-06 adversarial tracker audit.

Two kinds of mutation:

  REPLACE  — a statement in the body is factually FALSE and is corrected in place.
  APPEND   — a clearly-headed revision section, so the correction is auditable
             rather than silently rewriting an issue someone may have read.

Epic checklists gain their new children. All REST (GraphQL quota is exhausted).
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "CameronBrooks11/partspec"
HDR = "\n\n---\n\n## Audit revision — 2026-08-06\n\n_From the adversarial tracker audit (120 agents, 118 findings, 45 upheld after refutation). See `notes/audit-synthesis.md`._\n\n"


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])}\n{r.stderr}")
    return r.stdout.strip()


def body(n: int) -> str:
    return json.loads(gh("api", f"repos/{REPO}/issues/{n}"))["body"] or ""


def patch(n: int, new: str) -> None:
    gh("api", f"repos/{REPO}/issues/{n}", "-X", "PATCH", "-f", f"body={new}")


# (issue, old, new) — corrections of statements that are false as written.
REPLACE: list[tuple[int, str, str]] = [
    (
        17,
        "and both binaries in the CI matrix render headless with no display — already verified.",
        "**PNG rendering headless is *not* verified — measured, it is broken on one leg.** "
        "OpenSCAD 2026.08.01 renders PNG headless (exit 0); 2021.01 cannot — "
        "`Unable to open a connection to the X server.` / `Can't create OpenGL OffscreenView. Code: -1.`, "
        "then a segfault (exit 139) leaving a 0-byte PNG. Headless *STL* export works on both, "
        "which is all `ci.yml:105-108` ever claimed. Note the apt leg does not lack a graphics stack "
        "(`apt-cache depends openscad` shows libgl1/libglu1-mesa/libqt5gui5t64); what is missing is a **display**.",
    ),
    (
        26,
        "(coincident faces yield non-manifold edges — F10's root cause)",
        "(coincident faces yield non-manifold edges)",
    ),
    (
        28,
        "`SPEC-report.md` calls an empty contract",
        "`SPEC-contract.md:276` calls an empty contract",
    ),
]


APPEND: dict[int, str] = {}

APPEND[8] = """**The acceptance criteria as written still admit a truthiness coercion.** Bullet 1's
top-level-AST-node rule is not enough: `ast.parse("a <= b and c")` is a `BoolOp` and
`ast.parse("not (a - b)")` is a `UnaryOp(Not)`, so both clear it. Bullet 2 (non-bool result
raises) catches the first only when the left operand happens to be true, and never catches
the second — `not X` always returns a genuine `bool`. A literal implementation of all five
bullets would still green `requires("not (bore_d + 2*wall - plate_y)")`.

Replace bullet 1 with a **recursive** rule:

> An expression is a *predicate* iff it is a `Compare`, a `BoolOp` whose every value is a
> predicate, a `UnaryOp(Not)` whose operand is a predicate, or a bare `Name`. Anything else
> raises `ContractError` (→ `verdict: "error"`, exit 4). The rule applies recursively, not
> only at the top level.

The bare-`Name` leaf is deliberate: bool params are supported (`openscad.py:69-73`,
`runner.py:262-265`), so `requires("is_threaded and pitch > 0")` is an honest predicate and
must not be rejected.

Generalize bullet 2 from the final result to **every boolean position, as a pre-eval check**:
each `Name` in predicate position must be `isinstance(params[name], bool)` before `eval`, else
`ContractError`. It cannot be a post-eval check — `a <= b and c` short-circuits, so a runtime
result check cannot see `c` when the left operand is false. Keep the existing post-eval `bool`
guard as the backstop.

Two further acceptance bullets:

- [ ] A `requires` expression that reads no declared parameter (`operands_of(expr) == ()`, `expr.py:82`) raises `ContractError` — matching `Limit.__post_init__` (`status.py:228`) and the fold guard (`status.py:308-315`).
- [ ] A comparison whose two sides are the syntactically identical operand (`x == x`, `x >= x`) raises `ContractError`. Broader semantic tautology detection (`x - x >= 0`, `x < x + 1`) is explicitly out of scope, recorded as such in `SPEC-contract.md` §5.1.

Extend the test list to reject `1`, `a - b`, `1 > 0`, `a == a`, `not (a - b)`, and
`a <= b and c` — the last asserted at **both** `{a:1,b:2,c:3}` and `{a:3,b:2,c:3}`, so the
test pins value-independence. Accept `a <= b`, `0 < x < 10`, and `is_threaded and pitch > 0`
with a genuine bool param.

`SPEC-contract.md` §5.1 must state the **recursive grammar and the bool-leaf requirement**,
not a top-level node list. It currently documents neither (`:258-270` covers only the
namespace restriction and chained comparisons).
"""

APPEND[12] = """**The acceptance leaves a green test asserting the broken guarantee.**

- [ ] `tests/test_occt_backend.py:48` (`test_cadquery_multi_solid_adopts_as_a_compound`) is **replaced**, not just re-pointed. Its `.box(5,5,5).moveTo(20,0).box(5,5,5)` fixture uses the default `combine=True`, so `adopt(w)` already returns a 2-solid Compound at volume 250 today and stays green against the bug. The replacement must leave multiple Solids on the Workplane stack and pass the Workplane to `adopt()`.
- [ ] The regression is asserted end to end as well as at `adopt()`: a contract declaring `solid_count(1)` on a 4-body CadQuery model must not exit 0.

Reword existing box 2 — "a two-body CadQuery model" is satisfied by the already-working
`combine=True` case. Name a **stack of separate solids**.

Verified, cadquery 2.8.0:

```python
w = cq.Workplane('XY').rect(20, 20, forConstruction=True).vertices().box(5, 5, 5, combine=False)
len(w.vals())          # 4  -> ['Solid', 'Solid', 'Solid', 'Solid']
adopt(w).volume        # 125.0, not 500.0
len(adopt(w).solids()) # 1,     not 4
```

Scope note: the default `combine=True` path is unaffected, so the fix is narrow — compound
`obj.vals()` when the stack is >1, rather than `obj.val()` — not a rewrite of adoption.
Correct the stale comment at `pycad.py:75-76`, which asserts the false premise.
"""

APPEND[17] = """**Two further acceptance items, and one scope extension.**

Split "Works headless on both engines in the CI matrix" into an explicit choice — see the
Why correction above:

- **(a)** add `xvfb` to the apt install at `ci.yml:92` and wrap the PNG invocation in `xvfb-run -a`; **or**
- **(b)** declare 2021.01 render-unsupported and emit a first-class `unsupported`, never a crash.

Extend coverage to the **`mesh-only` job** (`ci.yml:143-162`) — a second apt-2021.01 leg with
no display. #17 is scoped "on the mesh tier", so its render path runs there too.

Add the failure that actually escapes today:

- [ ] A model that resolves to no geometry is a `BuildError`, not four blank views — a render must be shown to *contain the part*, not merely to have been written.

Repro: `difference(){cube(10); translate([-1,-1,-1])cube(12);}` exits 0 and writes a valid
3448-byte PNG with 1 unique colour, on **both** binaries. Prefer refusing before rasterising
(the mesh tier already detects empty output, `openscad.py:212-215`) over image forensics; fall
back to "the raster contains a colour other than the background" only if the render path stays
image-only, and exempt #19's section cuts from any whole-frame uniformity heuristic.

Sharpen the BuildError line: *"never a silent missing file"* does not cover a present, 0-byte
file — require the size check the STL path already has (`openscad.py:213-218`). Require the
hint to name the real cause: `_first_error_line` (`openscad.py:224-243`) matches only
ERROR/WARNING and here falls back to `Compiling design (CSG Products normalization)...`, so a
headless segfault reports `openscad exited -11` with a hint that says nothing about X.

**Keep criterion 2 (bbox-derived framing) unchanged.** Do not add a byte floor — the 0-byte
case is already a `BuildError` via the returncode check at `openscad.py:207`.

**#17 unblocks #27.** It is currently the only thing between epic #4's first sub-issue and
being startable.
"""

APPEND[21] = """**Two missing criteria.** Keep all three existing ones — including "differing image sizes →
refuse", which is validation at a trust boundary on files read from disk, and silent rescaling
is this project's canonical failure mode.

- [ ] A change in the part produces a non-empty diff **and a nonzero magnitude** — including a uniform scale change (a 20 mm vs a 20.4 mm cube), which bbox-derived framing (#17) renders byte-identical. Either the diff pairs pixels with a scale-invariance escape (a fixed world-scale camera, or the bbox recorded alongside the image and compared), or the issue states outright that pure scale is invisible to visual diff and refers it to `measure`. Regression: the F16 case at `docs/PLAN.md:281` must not diff to zero.
- [ ] The diff carries the engine kind and version of both inputs and **refuses a cross-version pair** rather than reporting renderer noise as change. Measured: 7.68% of pixels differ, max channel delta 85, for *identical geometry* across 2021.01 and 2026.08.01. `report.engine["version"]` (`runner.py:87-88`) supplies this; #20 already routes image paths through the report.

Do **not** replace "identical geometry produces an empty diff" — it is measurably true within
an engine version (0 px, including xvfb vs headless) and is the determinism guard the CI
matrix exercises.
"""

APPEND[24] = """**Box 4 revisits a deliberate prior decision, not a chore.** `docs/PLAN.md:37` records the
dogfood workspace's untracked status as an intentional call, so "the dogfood workspace's
status as scratch is resolved" means reopening that decision.

Related but **not** blocking: #51 (the untracked `notes/` workspace). Keep #24 scoped to the
CAD-failure catalogue — folding in partspec's own self-review and an external research memo
would make it a grab-bag.
"""

APPEND[25] = """**Both verification criteria currently point at untracked infrastructure.**

- Sharpen box 2 from "Each is in the dogfood batch and stays green" to: **each is exercised by something in this repo** — a pytest case or a justfile recipe over `examples/` — and stays green.
- Box 3's "the differential test" currently means `/home/cam/repos/partspec-dogfood/differential.py`, which is untracked. See #42, which brings the engine-parity differential test into this repo, and cross-reference **D18**.

#24 is related, not blocking. Do not split these criteria out — they are the only executable
acceptance this issue has.
"""

APPEND[26] = """**Resolve the internal contradiction, and name the shipping slice.** Keep all five rules.

1. **Split acceptance bullet 4** ("Runs without an engine installed"), which contradicts the coincident-face and `difference()`-ordering rules in this issue's own What. Source-only rules (magic numbers, unused top-level variable, module size/nesting, `$fn` policy) MUST run engine-free; geometry-dependent rules MAY require the engine and MUST return `unsupported` — never silent absence — when it is missing.
2. **Name the shipping slice.** Tier 1 (engine-free): unused top-level variable (`examples/spacer/spacer.scad:10` `wall = 2;` is the in-repo example), magic numbers, module size/nesting. The Python tier needs no new machinery — stdlib `ast` is already used in the core (`expr.py:18,65-90`). Tier 2 (engine-assisted): coincident-face epsilon and `difference()` ordering, over `openscad --export-format csg`, which emits a fully constant-folded tree (verified on `examples/spacer/spacer.scad`).
3. **Define "suspicious"** — the word appears nowhere else in the repo. Either state the predicate (e.g. a `difference()` whose first child is not the largest-volume child, or whose subtrahend shares a face plane with the minuend to within 0 epsilon) or delete the word.
4. **Do not list the `-D`-binds-no-variable rule here.** #9 owns it as a `blocks-release` `BuildError`; #26 reuses #9's closure resolution rather than restating it as advisory.
5. **Add a prior-art survey requirement** to acceptance, attached to the `.csg` reader: *does an existing OpenSCAD static analyser or `.csg` reader beat hand-rolling one?* D7 (`DECISIONS.md:15,123`) and D12 (`:20,250`) are both absorb-vs-depend decisions, and `README.md:147` carries a Prior art section — the repo's own standard applies.
6. **Keep bullet 3 verbatim** ("advisory and never a verdict on the part").

Code-reuse note (not acceptance): OpenSCAD-side lint should reuse `_strip_noise`
(`engines/openscad.py:284`) and `include_closure` (`:322`) rather than re-implementing a
tokenizer.

**F10 attribution struck from the Why above.** `DECISIONS.md:357-358` contradicts it — the
same source under `--backend CGAL` renders clean, so F10 is a meshing artifact, not a design
error (echoed at `SPEC-report.md:521-523`). No source lint can catch F10.
"""

APPEND[27] = """**Dependencies, a shared hazard, and a scope-drift flag.**

Depends on #17 (mesh-tier render) and #18 (OCCT-tier render); the report-side handle is #20.
See also #48 — the server currently has no extra, no entry point, and no declared dependency.

- [ ] `docs/POST-V0.md:82-84` scopes MCP to "~100 lines over check / measure" — **two** verbs. Exposing a third means the ~100-line honesty check is being measured against a surface D5 never sized. Record which number the ~100 lines is compared to.
- [ ] A helper edited between two tool calls is picked up — the model's directory subtree is invalidated from `sys.modules` before **each build**, with a test asserting the second `check` on the *same* target sees the edit. (Shared hazard with #29 — POST-V0 §8; whichever lands first implements it. #29's box scopes invalidation "between targets", which does not cover MCP's repeat calls on one target, so invalidation must key on every build.)

Do **not** add a hard blocked-by edge to #29 — `POST-V0.md:171` deliberately says "whichever
lands first owns" it. This is not a #30 correctness blocker.

**Keep `render` in the title and acceptance.**
"""

APPEND[28] = """**The exit-code→action mapping is not derivable from the current spec.** Rewrite the
acceptance bullet to:

> maps each **(exit code, `verdict`, presence of a report at the deterministic path)** triple
> to an action.

The document must state:

- exit 4 **with no report on disk** = the contract failed to *load* (`cli.py:94-96` returns before `write_placeholder` at `:103`); exit 4 **with a report** = it raised mid-run (`runner.py:55-62`);
- exit 2 must be disambiguated by reading `checks[].status` for `skipped` (fix your parameter) vs `unsupported` (wrong tier — `POST-V0.md:146`);
- exit 1 must be disambiguated by whether the failing check `id` is `builds` (the source does not compile) or a declared check (the geometry is wrong).

**Blocked by #35.** `SPEC-report.md:319,:337` and `SPEC-contract.md:138` currently disagree
about whether a failed build is `error`/exit 4 or `builds: fail`/exit 1. Land that spec
correction first, or this document inherits the error and hard-codes it into agent behaviour.
"""

APPEND[29] = """**Three acceptance defects.**

**(a) Placeholders must be hoisted out of the loop.**

- [ ] Placeholders for **all** N targets are written before the first engine runs, not per-iteration — a native fault on target 3 must leave targets 4..N with a report saying the run died, never the previous run's `verdict: "pass"`. See #13; `write_placeholder` needs only the out dir and argv, so this is N cheap writes and requires no resolved `Part`.

Do **not** offer "run OCCT targets in a subprocess pool" as the alternative — it forfeits the
import-cost saving that is this issue's entire justification (D5, `DECISIONS.md:102-104`).
This is *not* the existing "one part erroring does not prevent the rest" bullet being
unmeetable; that bullet is about the catchable `error` verdict (`status.py:94`,
`SPEC-report.md:319`) and a per-target try/except satisfies it. State it as a separate hazard:
batching removes the per-target **process** boundary `POST-V0.md:167` relies on.

Test: a subprocess-level CLI test where target 2's model calls `os._exit()`, asserting target
3's on-disk `report.json` is the error placeholder and not a stale `pass`. Existing placeholder
tests (`tests/test_report.py:180-192`) call `write_placeholder` directly and `tests/test_cli.py`
runs in-process — this one test needs a real subprocess. Also amend `docs/SPEC-report.md:303-307`,
which has the same hole: "a failure in one MUST NOT prevent the others" does not cover the
process dying.

**(b) Batch exit code.** Replace "Batch exit code is the worst individual verdict" with:

- [ ] Batch exit code is the highest-precedence verdict across all parts per `SPEC-report.md` §6.2 — `error > empty > fail > incomplete > pass`. Note `empty` outranks `fail`, and this order is **NOT** `max()` over the numeric exit codes; `64` never participates.
- [ ] A test covers the two pairs the numeric order gets wrong: a batch of {fail, incomplete} exits `1`, and a batch of {empty, fail} exits `3`.

Implementation notes (not acceptance): `status.py` has no helper ranking `Verdict` — `worst()`
(`status.py:82-85`) ranks `Status`, and `_SEVERITY` lacks INCOMPLETE/EMPTY/ERROR keys. While
there, fix the comment at `status.py:71-72`, which claims `_SEVERITY` is used "to pick a
batch's overall verdict" — it never has been, and because both enums are `StrEnum`,
`_SEVERITY[Verdict.FAIL]` silently returns 4 while `_SEVERITY[Verdict.INCOMPLETE]` raises
`KeyError`. Consequence: `max()` does not produce a green exit, it reports a batch containing a
*disproven* part as `2` = "nothing disproven".

**(c) `sys.modules` invalidation scope.** Widen the bullet to: the model's **and the
contract's** directory subtrees are invalidated from `sys.modules` **before every build**, not
merely "between targets".

Tests must cover both failure modes: an edited contract-side helper in a directory separate
from the model is picked up by the next target; **and** two contracts in different directories
that each import a same-named helper (`limits.py`) each get their own — the no-edit collision
case, which an "edited helper is picked up" test would pass while broken. Also amend
`docs/POST-V0.md:171`, the origin of the model-only scoping.
"""

APPEND[2] = """**The Why cites none of this repo's own counter-evidence, and one claim is unsupported.**

1. Strike the leverage superlative. Renders being *cheap* is defensible (OpenSCAD `--camera`/`--imgsize`, and #17 is a small slice). "The highest-leverage missing layer" is not supported by anything in the repo.
2. **Re-scope the Goal: renders are evidence attached to a report for failure triage and human review — not the agent's primary perception channel.** The primary channel is numeric: cross-sections, feature inventories, and keep-out/keep-in regions (#49). The omitted counter-evidence, with citations:
   - `PLAN.md:283-284` and `:322-324` — four of five dogfood findings were **invisible** to visual review.
   - BenchCAD: Vision QA underperforms Code QA by **15–20pp on identical questions** — models read the code better than a picture of it.
   - build123d-mcp's own validation protocol orders *deterministic checks before visual*, and says outright: "do not render after a simple boolean that `measure()` already confirmed."

   Keep the `PLAN.md:278` citation — F13 is the honest case *for* renders. State it as one-of-five, not as the pattern.
3. Add the boundary line (also going into `DECISIONS.md`): **partspec is a stateless declarative contract checker; build123d-mcp is a stateful authoring session.** Without it, this epic and epic #4 drift into a niche that is already occupied by a tool with published benchmark gains.
4. Sequencing: **#17 → #20 are prerequisites of #27, not competitors** — #27's acceptance requires a render tool. Hold #18 and #21 until a render has demonstrably triaged a real failure. #19 stays here as a render slice, sequenced ahead of #18/#21.

**Epic #2 is re-scoped, not demoted.** All five sub-issues stay open.
"""

APPEND[6] = """**Non-goals.**

- **`min_wall` is not a slice here, but is unblocked by one.** `POST-V0.md` §5 says it ships when the BREP tier makes a different method available — which is what `hole_diameter` / `fillet_radius` build. Revisit when those land.
- **Printability / DFM** (`overhang`, trapped volume) is out of scope by `SPEC-contract.md` §4.3 — a separate concern from dimensional intent — and has no issue yet.
- **`clearance` / `interference` is not this epic's.** It needs two bodies; `_run_geometry_check` (`runner.py:166`) takes one artifact, and `SPEC-contract.md:197-201` assigns it to assemblies under D11 / `POST-V0` §1.

Newly added slice: **#49 keep-out / keep-in regions** — the one form of interface intent that
needs no second body and no assembly support, and whose boolean primitive is already
implemented on both tiers with zero callers.
"""

APPEND[3] = """**Add to Done means:** *…and we have a recorded before/after on agent output.* (#53)

Efficacy is currently unmeasured across all five sub-issues. External ablation evidence says
the effect is real but unevenly distributed — few-shot **examples** move code generation
roughly **+21.5pp** while documentation **prose** moves it roughly **+5pp**, and removing code
examples collapses accuracy from 0.66–0.82 to 0.22–0.39. If that holds here, **#25 (worked
exemplars) is the high-value slice and #22/#23 are the supplement** — the reverse of the order
they are filed in.

BenchCAD also says what the skills must *contain*: models default to sketch-and-extrude and
recall revolve/loft/sweep/fillet only 25–35% of the time untrained. So an **operation-selection
guide**, not a style guide — which is also the direct cause of the "way too much LoC" symptom
that motivated this epic.

New slices: #51 (resolve the untracked `notes/` workspace), #52 (contract-authoring skill —
nothing currently teaches a *user* of partspec how to write a contract), #53 (measure the
effect).
"""

APPEND[7] = """**The "PyPI publish" slice has no acceptance criteria. Give it these:**

- [ ] Every internal link in `README.md` is an absolute `https://github.com/CameronBrooks11/partspec/blob/main/...` URL. Today 8 links are repo-relative (`README.md:7, :17, :138, :140, :142, :143, :144, :145`) and all 8 would 404 on PyPI, because `pyproject.toml:6` embeds README.md verbatim as the `text/markdown` long_description (confirmed in the built wheel's METADATA line 21).
- [ ] A test in `tests/test_docs.py` asserts no `](docs/` or `](examples/` survives in README.md. That file already pins README claims mechanically (`tests/test_docs.py:50-101`), so this is one more assertion in the same style — not a manual pre-publish checklist item.
- [ ] The release checklist flips `README.md:5` ("pre-alpha, and unreleased") and `README.md:120-127` ("Not on PyPI yet. From a clone:") to the published install.

Keep the "README states the agent purpose" slice **exactly as titled** — it is the
highest-signal item in this epic and the public face currently never says "agent" or "MCP".

New slices, all of which must land **before** the tag because they change or freeze
`schema_version: 1`: #43 (`engine.backend` vs `engine.tier` — removes a field, needs a schema
bump), #44 (parameter unit inferred from Python literal type — freezes `measurement.unit` as a
compatibility surface), #45 (`part.source` leaks an absolute machine path).
"""


CHILDREN: dict[int, list[int]] = {
    1: [36, 37, 38, 39, 40, 41, 42],
    3: [51, 52, 53],
    4: [46, 47, 48],
    5: [50],
    6: [49],
    7: [43, 44, 45],
    32: [33, 34, 35],
}


def title_of(n: int) -> str:
    return json.loads(gh("api", f"repos/{REPO}/issues/{n}"))["title"]


def main() -> None:
    print("== replacements (false statements) ==")
    for n, old, new in REPLACE:
        b = body(n)
        if old not in b:
            print(f"  ! #{n} target string not found — skipped")
            continue
        patch(n, b.replace(old, new, 1))
        print(f"  ~ #{n} corrected")

    print("== epic checklists ==")
    for epic, kids in CHILDREN.items():
        b = body(epic)
        lines = []
        for k in kids:
            if f"#{k} " in b:
                continue
            lines.append(f"- [ ] #{k} {title_of(k)}")
        if not lines:
            print(f"  = #{epic} already lists its children")
            continue
        if "<!--TASKLIST-->" in b:
            b = b.replace("<!--TASKLIST-->", "\n".join(lines))
        else:
            b = b.rstrip() + "\n" + "\n".join(lines) + "\n"
        patch(epic, b)
        print(f"  + #{epic} gained {len(lines)} children")

    print("== appended revisions ==")
    for n, text in APPEND.items():
        b = body(n)
        if "## Audit revision — 2026-08-06" in b:
            print(f"  = #{n} already revised")
            continue
        patch(n, b.rstrip() + HDR + text)
        print(f"  + #{n} revision appended")


if __name__ == "__main__":
    main()
