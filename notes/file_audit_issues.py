#!/usr/bin/env python3
"""File the issue mutations from the 2026-08-06 adversarial tracker audit.

Source: notes/audit-synthesis.md (120-agent workflow, 118 findings, 45 upheld).
Idempotent-ish: refuses to create an issue whose exact title already exists.
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "CameronBrooks11/partspec"


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"gh {' '.join(args)}\n{r.stderr}")
    return r.stdout.strip()


def existing_titles() -> dict[str, int]:
    """REST, not `gh issue list` — the latter uses GraphQL, whose quota the audit
    workflow's 120 agents exhausted."""
    out: dict[str, int] = {}
    for page in (1, 2, 3):
        raw = gh("api", f"repos/{REPO}/issues?state=all&per_page=100&page={page}")
        rows = json.loads(raw)
        if not rows:
            break
        for i in rows:
            out[i["title"]] = i["number"]
    return out


def create(title: str, body: str, labels: list[str], seen: dict[str, int]) -> int:
    """REST POST — `gh issue create` goes through GraphQL, which is exhausted."""
    if title in seen:
        print(f"  = #{seen[title]} exists: {title[:70]}")
        return seen[title]
    args = ["api", f"repos/{REPO}/issues", "-X", "POST",
            "-f", f"title={title}", "-f", f"body={body}"]
    for lab in labels:
        args += ["-f", f"labels[]={lab}"]
    num = json.loads(gh(*args))["number"]
    seen[title] = num
    print(f"  + #{num} {title[:70]}")
    return num


# --------------------------------------------------------------------------
# Sub-epic (H8): the exit-code / error-path family, cut out of #1
# --------------------------------------------------------------------------

SUBEPIC = (
    "Epic: every terminal path's exit code must match the report it left",
    """## Overview

A sub-epic of #1, cut out because these share one surface and one sentence.

**The thesis, narrowed:** *no exit code originating anywhere but partspec's own
adjudication may become partspec's verdict.* Today three different things can
supply one — an unhandled Python exception, a `sys.exit()` inside user code, and
an environment fault that never let the build start — and each is reported as a
statement about the part.

## Why it is its own epic

#1 would otherwise carry ~19 unstructured children. These four sit on the same
few functions (`cli.py:69-108`, `runner.py:53-63`, `status.py:97-105`,
`report.py:250`), and fixing any one of them in isolation invites a fix that
moves the hole rather than closing it — #13 already demonstrated that, where
turning a traceback into a clean exit 4 left the previous run's `verdict: "pass"`
undisturbed on disk.

## Done means

Every terminal path — pass, fail, incomplete, empty, error, usage, timeout,
interrupt — leaves a report on disk whose `verdict` agrees with the process exit
code, and a test asserts the agreement path by path.

## Slices

<!--TASKLIST-->

Part of #1.
""",
    ["epic", "blocks-release"],
)

# --------------------------------------------------------------------------
# New issues. (title, body, labels, parent-epic-number)
# --------------------------------------------------------------------------

ISSUES: list[tuple[str, str, list[str], str]] = []


def add(title, body, labels, parent):
    ISSUES.append((title, body, labels, parent))


# ---- error-path family (parent: the sub-epic, filled in at runtime) ----

add(
    "An unexpected exception must never exit as a failing part",
    """## What

Any exception that is not a `ContractError` escaping `run()` leaves `_cmd_check`
(`src/partspec/cli.py:105-106`) and `_cmd_measure` (`cli.py:136,165,185`)
unguarded, so the process exits **1** — the code that means *"the part failed its
contract"* — while the placeholder already written to disk says
`verdict: "error"`. The exit code and the report contradict each other.

## Why

Exit 1 is the one code an agent is most likely to act on by editing the model.
Sending it for a `PermissionError` tells the agent its design is wrong when the
truth is that a directory is not writable. Reproduced four ways, none contrived:

| input | raises | at |
|---|---|---|
| a `str` parameter | `TypeError` | `status.py:237` |
| a `PosixPath` parameter | `TypeError` | `openscad.py:129` |
| `--out` at an unwritable dir | `PermissionError` | `report.py:251` |
| `--out` at an existing file | `FileExistsError` | `report.py:251` |

## Where

`src/partspec/cli.py:246-252` (`main`/`_cmd_*` dispatch) — **not** `runner.run`.
The `--out` repro dies at `cli.py:103 write_placeholder` → `report.py:250`,
*before* `run` is entered, so a guard inside `run` leaves it open.

## Acceptance

- [ ] An unexpected exception on any terminal path exits `exit_code(Verdict.ERROR)` (4), never 1.
- [ ] The report on that path carries the real traceback in `error` (`SPEC-report.md:540`), not the placeholder's false "segfault/OOM" hint.
- [ ] It lists every declared check as `skipped` per `SPEC-report.md:543-545`; the placeholder currently emits `checks: []`, which §7.1 forbids.
- [ ] `KeyboardInterrupt` / `SystemExit` still propagate (see the `sys.exit` slice).
- [ ] A successful `run()` whose `report.write()` *then* fails is covered — the guard wraps both.
- [ ] A parameter whose type cannot be adjudicated (`status.py:237`) or rendered (`openscad.py:90`) becomes a `ContractError` at the contract boundary (`Part.param()` / `openscad()`), not a runtime `TypeError`.
- [ ] The out dir is validated up front in `_cmd_check` as an explicit check if `EXIT_USAGE` (64) is wanted, so the catch-all stays a last resort rather than an `isinstance` ladder.
- [ ] A test asserts exit code and on-disk `verdict` agree on **every** terminal path: pass / fail / incomplete / empty / error / usage.

Note the interaction with #13: the placeholder write is itself a thing that can
raise, so this does not collapse into #13 and #13 does not subsume it.
""",
    ["bug", "blocks-release"],
    "SUBEPIC",
)

add(
    "A BaseException from a model or contract must never produce exit 0",
    """## What

Every guard in the resolve/build path catches `Exception`, never `BaseException`
(`src/partspec/cli.py:86`, `target.py:69`, `pycad.py:148`). So a model containing
`sys.exit(0)` makes `partspec check` exit **0** — green, silent, zero checks
evaluated — while the report says `verdict: "error"`. A contract factory that
exits leaves **no report directory at all**.

## Why

This is the project's named worst case: a vacuous green that an agent will read
as "the part is correct". Worse, user code currently gets to choose partspec's
verdict — `sys.exit(2)` reads as `incomplete`, `sys.exit(3)` as `empty`.

**The rule:** no exit code from user code may be reinterpreted as a partspec
verdict.

## Where

`src/partspec/cli.py:86`, `src/partspec/target.py:69`, `src/partspec/engines/pycad.py:148`.
Placeholder hint to fix: `report.py:286`.

## Acceptance

- [ ] A model or contract that raises `BaseException` (including `SystemExit`) yields `verdict: "error"` and exit 4 — never 0, and never a code the user chose.
- [ ] **Scope the guard.** Do not blanket-wrap `main`: `parser.parse_args` (`cli.py:246`) and `--version` legitimately raise `SystemExit`.
- [ ] `KeyboardInterrupt` → exit 130, still writing a report.
- [ ] `_cmd_measure` is in scope.
- [ ] Tests pin both exit code *and* on-disk report for: model `sys.exit(0)`, model `sys.exit(2)`, contract-factory `sys.exit(0)`, import-time `sys.exit(0)`, and `measure` on the first.
- [ ] `partspec --version` still exits 0, so the guard cannot regress it.

Cross-reference #13: repro B writes no report only because `write_placeholder`
sits at `cli.py:103`, *after* resolve — neither fix alone closes the hole.

Body note, not folded in: argparse usage errors exit 2 rather than the documented
`EXIT_USAGE = 64` (`status.py:105`).
""",
    ["bug", "blocks-release"],
    "SUBEPIC",
)

add(
    "A build that could not be attempted is not a part that failed",
    """## What

`src/partspec/runner.py:97-111` maps every `BuildError` to `builds: fail` →
`Verdict.FAIL` → exit 1. Pure environment conditions land there:

- `openscad not found on PATH` (`openscad.py:157-160`)
- a mistyped `PARTSPEC_OPENSCAD` (`openscad.py:199-205`)
- `openscad timed out after 300s` (`openscad.py:193-194`)
- `source not found` (`openscad.py:161-162`, `pycad.py:121-122`)
- a missing engine package (`pycad.py:48 import build123d`, `mesh.py:96 import trimesh`)

A CI run on a machine with no OpenSCAD installed reports the *design* as
disproven.

## Why

**This is already a spec contradiction, not just a bug.** `SPEC-report.md:319`
and `:337` say a failed build is `verdict: error` / exit 4; `SPEC-contract.md:138`
says `builds` fails. `check` and `measure` also disagree with each other —
`cli.py:137-141` already exits 4 for the same `BuildError`.

## Where

`src/partspec/runner.py:97-111`; construction sites listed above;
`docs/SPEC-report.md:318,:337`; `docs/SPEC-contract.md:138`.

## Acceptance

- [ ] The spec contradiction is resolved **in the docs first**, before any code lands — `SPEC-report.md:318` must lose "the build or" from the `error` row, not only `:337`.
- [ ] `BuildError` carries a machine-readable class, `origin: "environment" | "model"`, set at each construction site.
- [ ] `origin: "environment"` → `report.error`, `verdict: "error"`, exit 4, every declared check `skipped`, `builds` never FAIL.
- [ ] The `hint` names the remedy **and the missing extra** where applicable. (This absorbs the old bullet 2 of #16.)
- [ ] The class is a report field a consumer can branch on — not prose in `detail`, and not `engine.version == "unknown"`, which `openscad.py:372,378,381` returns for three unrelated reasons.
- [ ] A note under `SPEC-report.md` §6.2 records that a *design*-caused build failure exits **1**, or **3** when the contract declares no checks of its own (`report.py:162-164`, reproduced).
- [ ] `measure` takes the same classification.
- [ ] `tests/test_runner.py:325-331` (`test_a_build_failure_fails_builds_and_skips_the_rest`) encodes the disputed behaviour and is split into a design case and an environment case.

**Blocks #28** — the agent contract cannot map exit codes to actions until this
contradiction is resolved.
""",
    ["bug", "blocks-release"],
    "SUBEPIC",
)

# ---- remaining correctness, epic #1 ----

add(
    "A shape containing no geometry must not build, and must not satisfy an envelope, area or watertight claim",
    """## What

On the OCCT tier `bbox` (`src/partspec/backends/occt.py:86-90`), `area`
(`:106-109`) and `watertight` (`:133-135`) are ungated, while `volume` and
`center_of_mass` gate on `a.solids()`. `adopt()` rejects only a *null* TopoDS
(`pycad.py:88-89`), so an empty `TopoDS_Compound` becomes a legitimate artifact.

Reproduced end to end with a plausible slip — `bd.Box(s,s,s) - bd.Box(2s,2s,2s)`,
a cut that consumes its own operand:

```
ok builds / ok envelope / ok area / ok watertight
PASS: 4 pass          exit 0
envelope {'value': [0.0, 0.0, 0.0], 'exactness': 'exact'}
```

Four green checks and an exit 0 on a part that does not exist.

## Why

The mesh tier is already guarded (`mesh.py:99-100`, `openscad.py:214-218`), so
this is an OCCT-only asymmetry — the same class of hole D17 closed for `volume`
and `center_of_mass`, left open for three neighbouring primitives.

## Where

`src/partspec/backends/occt.py:86-90,:106-109,:133-135`; `src/partspec/engines/pycad.py:88-89`.

## Acceptance

- [ ] `adopt()` returns `BuildError("model returned a shape containing no geometry")` for a non-null shape with no sub-shapes.
- [ ] `bbox`, `area` and `watertight` each refuse with `Unsupported` naming the precondition, so the library path is covered independently of the CLI gate.
- [ ] The precondition is **"contains no sub-shapes", NOT "has no faces"**. A `Wire`/`Edge` has zero faces and legitimately answers all three — verified: a circle wire gives bbox (10,10,0), area 0.0, watertight False. D17 part 2 forbids the broader gate.
- [ ] Regression test on the consuming-cut case above.
- [ ] The CadQuery leg of `adopt` (via `.val()`) is covered too.
""",
    ["bug", "blocks-release"],
    "1",
)

add(
    "A failed OpenSCAD build must not report cache statistics as its hint",
    """## What

`_first_error_line` (`src/partspec/engines/openscad.py:225-241`) falls back to
`lines[0]` when no ERROR/WARNING line is present. Both 2021.01 and the 2026.08.01
nightly print cache statistics first, so:

- `cube([10,10,0]);` → `hint: "Geometries in cache: 1"`, dropping the actual
  `Current top level object is empty.`
- `square([10,10]);` → same, dropping `... is not a 3D object.`

## Why

The hint is the one line an agent reads to decide what to change. Handing it a
cache statistic is worse than handing it nothing: it is confidently irrelevant.

## Where

`src/partspec/engines/openscad.py:225-241`.

## Acceptance

- [ ] Known-noise lines are dropped before selection: `Geometries in cache`, `Geometry cache size`, `CGAL Polyhedrons in cache`, `CGAL cache size`, `Total rendering time`, and the success-summary block (`Vertices:` / `Halfedges:` / `Edges:` / `Halffacets:` / `Facets:` / `Simple:`) that can appear on the exit-0-no-geometry branch at `openscad.py:217`.
- [ ] **Keep first-wins.** Do NOT switch to last-wins: verified that `openscad --backend=CGAL` on 2021.01 prints the reason first followed by a long `Allowed options:` dump, and last-wins returns a fragment of that dump — regressing the exact case `openscad.py:227-234` exists to protect.
- [ ] No special-casing of the two messages is needed once noise is filtered.
- [ ] The full stderr is preserved on `BuildError` and reaches the report, so filtering can never lose a diagnosis. **This is a schema addition** — `backend.py:94-98` carries only message/hint; `SPEC-report.md` needs the field. Call it out rather than smuggling it in.
- [ ] Regression tests use recorded stderr fixtures **on 2021.01 only** (the nightly emits only the diagnosis line and is already correct), including the `--backend=CGAL` usage dump so first-wins is pinned.
""",
    ["bug"],
    "1",
)

add(
    "Auto-generated requires() ids collapse every comparison operator to underscore",
    """## What

`_slug` (`src/partspec/contract.py:271-277`) maps `>`, `<`, `>=`, `<=`, `==`,
`!=`, `+` and `-` all to `_`. So `requires("x > 5")` and `requires("x < 5")` both
derive the id `x_5`, and `_add` (`:258-264`) refuses the contract with exit 4.

A bracketing pair of bounds cannot be expressed without hand-authored ids, and
the error blames *"two checks of the same kind"* when the two checks are
opposites.

## Why

This is the default path, not a corner: every contract in the repo omits `id=`
(`examples/spacer/spec.py:34-35`, `README.md:36-37`). Writing an upper and a
lower bound is the most ordinary thing an author does.

Severity framing: this is a loud exit-4 refusal, not a silent green — a
usability and id-layer correctness bug, not a thesis violation.

## Where

`src/partspec/contract.py:271-277`, `:258-264`.

## Acceptance

- [ ] Operators map to distinct readable tokens: `gt` / `lt` / `ge` / `le` / `eq` / `ne`.
- [ ] `requires("x > 5")` and `requires("x < 5")` coexist in one contract.
- [ ] A residual collision (a shared 60-char prefix after truncation) still raises, and names **both** expressions.
- [ ] A regression test pins the slug of each operator, so a future `diff` join key cannot alias two claims.

Out of scope: `id=""` is benign; file separately as a one-line hygiene item if
its inconsistency with `Part("")` (`contract.py:110-111`) matters.

Explicitly **not** claimed: that a future `diff` would be silent about a `>=`→`<=`
edit. `contract_digest` and the per-check `expr` already make that visible.
""",
    ["bug"],
    "1",
)

add(
    "The method= scratch file must not be written into the source tree",
    """## What

`render()` calls `tempfile.mkstemp(suffix=".scad", dir=source.path.parent)`
(`src/partspec/engines/openscad.py:170`) whenever `source.method` is set.

- A `chmod 500` source directory crashes with an uncaught `PermissionError` and
  **exit 1**.
- A writable one gets an anonymous `tmpXXXX.scad` sitting beside the model for
  the duration of the build — a verification tool writing into the tree it is
  verifying.

## Why

Besides the crash, this is a category error: the artifact under inspection and
the inspector's scratch space must not share a directory. A concurrent run, a
file watcher, or a `git add -A` all see the scratch file.

## Where

`src/partspec/engines/openscad.py:169-177`.

## Acceptance

- [ ] The scratch `.scad` is written under the **out dir**, not the source dir.
- [ ] It uses an absolute-path `include <>` of the source plus the appended call, rather than copying the body. Verified working, including when the source itself does `include <sub/lib.scad>`, because OpenSCAD resolves nested includes relative to the file containing the include statement.
- [ ] Do **not** rely on `OPENSCADPATH`: 2021.01 has no `-I`, and it does not cover relative `import()` / `surface()` data-file references.
- [ ] A `method=` render from a `chmod 500` source dir succeeds.
- [ ] Any remaining unwritable-location failure returns a `BuildError` naming the directory and exits 4 — never a traceback.
- [ ] The scratch file uses a `.partspec-` prefix, per the convention at `report.py:251`.
- [ ] Regression tests for (a) the read-only source dir and (b) a `method=` source with a relative `include`.

Note: there is **no test exercising the OpenSCAD `method=` path at all** today.
""",
    ["bug"],
    "1",
)

add(
    "The report never records which callable was invoked, or how OpenSCAD parameters were applied",
    """## What

`Source.method` (`src/partspec/contract.py:63,67-87`) reaches neither the `part`
nor the `engine` block of the report, yet it is load-bearing on both tiers:

- OpenSCAD: it switches `render()` between `-D` defines and appending
  `method(args);` to a throwaway copy (`openscad.py:169-177`, `:133-143`).
- Python tiers: it selects the factory (`pycad.py:129-138`).

## Why

Two runs of the same contract can build different things, and the report does not
say which happened. On the `call` path it is worse than silent: `part.source_digest`
and `source_closure` name a file OpenSCAD was **never given**.

## Where

`src/partspec/runner.py:87-95`; schema block `docs/SPEC-report.md:374-393`.

## Acceptance

- [ ] `engine.method` = `Source.method` when set, `null` otherwise — mirroring `adopted_via` (`runner.py:90`).
- [ ] OpenSCAD-only: `engine.param_mode` = `"define"` or `"call"`.
- [ ] On the `call` path, the report also records that the rendered input was not the digested file — a digest of the scratch content, or an explicit `source_rendered: "derived"` marker.
- [ ] Fields added to the §7 schema block with a §7.1 note in the same terms as `engine.render_backend` (`SPEC-report.md:521-525`).
- [ ] Acceptance is **not** "the two reports differ" — `contract_digest` and `geometry` already differ today. Instead: a `method=` build states the callable name; a plain build states `null`; and a reader of a **single** report can tell which param mode happened.
- [ ] Tests cover both branches of `openscad.py:169-176` and the pycad default-vs-named factory.

Additive under `schema_version: 1`, so this is free before the tag.
""",
    ["bug"],
    "1",
)

add(
    "engine.render_backend must always be present, not only when pinned",
    """## What

`src/partspec/runner.py:92-95` sets `engine.render_backend` only
`if part.source.backend` — and the comment on that branch states the field is
recorded *because it changes the artifact*.

F10 is exactly that: OpenSCAD's default Manifold backend emitted 4 non-manifold
edges where CGAL emitted none, from identical source. An unpinned run silently
takes the engine default (CGAL on 2021.01, Manifold on current builds —
`openscad.py:55-63`) and records nothing about it.

## Why

The field exists to make a run reproducible. Omitting it in exactly the case
where the value was not chosen by the author is backwards: the unpinned run is
the one whose backend a reader cannot infer.

## Where

`src/partspec/runner.py:92-95`; `docs/SPEC-report.md:390-392`, `:519`.

## Acceptance

- [ ] The key is present in both pinned and unpinned reports (`tests/test_runner.py:75-76`).
- [ ] Value is the pinned string, or `null`.
- [ ] `SPEC-report.md:519` states normatively that `null` means "the engine default for the recorded `engine.version`", and names the known mapping.
- [ ] `schema_version` is unchanged — adding or relaxing a field does not bump it (`SPEC-report.md:548`).

Do **not** adopt "always pass `--backend`": it changes the artifact for every
existing unpinned contract, requires a default the project has not chosen, and
the flag does not exist on 2021.01 (`openscad.py:62`).
""",
    ["bug"],
    "1",
)

add(
    "The engine-parity differential test must live in this repo",
    """## What

`docs/SPEC-backend.md:313` declares an engine-parity differential test a **MUST**.
Nothing under `tests/` satisfies it — `grep -rn 'parity|two engines|both engines|differential' tests/`
matches only a docstring at `tests/test_occt_backend.py:1`.

The only implementation is a throwaway at
`/home/cam/repos/partspec-dogfood/differential.py`, in an untracked workspace,
whose own docstring says it lives outside partspec because `diff` is post-v0.

## Why

A normative MUST with no implementation is the tracker's own version of a vacuous
green. It is also the test that would have caught F13 — the same source building a
different part on a different engine — as a test rather than as a dogfood
anecdote.

## Where

`docs/SPEC-backend.md:313`; new test under `tests/`.

## Acceptance

- [ ] A test in this repo builds the same nominal part through OpenSCAD and through build123d and compares the measurements the two tiers can both answer.
- [ ] It is exercised by CI on both engine legs.
- [ ] The dogfood `differential.py` is either promoted or explicitly retired with a note saying so.

Distinct from #11's obligation: this is **engine parity** (OpenSCAD vs build123d).
#11's is **tier parity** (mesh vs OCCT).

Cross-referenced from #25, #18 ("differential test extended"), #1's Done means,
and #11's cross-tier parity box.
""",
    ["bug"],
    "1",
)

# ---- pre-tag schema fidelity, epic #7 ----

add(
    "engine.backend means the measurement tier in check and engine.tier in measure",
    """## What

One block, two names for the same thing, plus a third name for something else:

| emitted by | key | value |
|---|---|---|
| `runner.py:89` (`check`) | `engine.backend` | the measurement tier |
| `cli.py:182` (`measure`) | `engine.tier` | the same value |
| `runner.py:95` | `engine.render_backend` | the OpenSCAD kernel |

## Why

A consumer reading both verbs has to know that `backend` and `tier` are synonyms
while `backend` and `render_backend` are not. Rename the `check` field to
`engine.tier`.

**This removes a field**, so `SPEC-report.md:548` requires bumping
`SCHEMA_VERSION` (`report.py:31`, currently 1). That is free only while
unreleased — there are no git tags and #7 is open. It must land before v0.1.0 or
not at all.

## Where

`src/partspec/runner.py:89`; `src/partspec/cli.py:182`; `src/partspec/report.py:31`;
`docs/SPEC-report.md:390`.

## Acceptance

- [ ] Both verbs emit the same key for `backend.kind`.
- [ ] `SPEC-report.md:390` updated.
- [ ] `SCHEMA_VERSION` bumped, with a changelog line.
- [ ] `tests/test_runner.py:76` and `:370` updated.

Blocked by nothing; blocks the tag.
""",
    ["bug", "blocks-release"],
    "7",
)

add(
    "A parameter's unit is inferred from its Python literal type",
    """## What

`_unit_for` (`src/partspec/runner.py:262-265`) returns `"count"` for `bool`,
`"mm"` for `float`, and `"count"` for everything else **including `int`** — then
feeds that into the `Measurement` for every `param_range` check (`runner.py:149`).

Reproduced: `plate_x=40` gives `unit: "count"` and `plate_y=30.0` gives
`unit: "mm"`, in the same report, on the same plate.

## Why

No verdict is wrong today — `adjudicate()` (`status.py:273`) never reads `unit`.
What makes it urgent is timing: `schema_version: 1` freezes `measurement.unit` as
a compatibility surface at the tag. **Gate on #7, not #1.**

## Where

`src/partspec/runner.py:262-265`, `:149`.

## Acceptance

- [ ] Stop inferring. A `param_range` measurement defaults to `mm` — v0's only length unit (`SPEC-report.md:110`).
- [ ] An optional `p.param(name, ..., unit="count")` covers genuine counts, and stays optional so `examples/spacer/spec.py:38` still works.
- [ ] The dead `isinstance(value, bool)` branch at `runner.py:263` is deleted.
- [ ] The rule is recorded in `SPEC-contract.md` §5.
- [ ] `40` and `40.0` produce identical `unit`.
- [ ] Editing a declared param int↔float between runs changes no `unit` — the §7.2 drift-stability case.
- [ ] `unit="count"` round-trips.
- [ ] A regression test for the int/float pair. None exists today.
""",
    ["bug", "blocks-release"],
    "7",
)

add(
    "The part block leaks an absolute machine path, violating SPEC-report.md section 8 rule 4",
    """## What

`part.contract` is the CWD-relative string the user typed (`runner.py:43`,
`report.py:184`), while `part.source` is **absolute** after `_anchor` resolves it
(`target.py:145-147`, `runner.py:47`).

Verified in the committed `examples/spacer/outputs/spec-spacer/report.json`,
which leaks a developer home directory into the repository.

## Why

This undoes at the path layer the machine-independence `source_closure` was
deliberately built to have — `runner.py:336-341`: *"A comparator's whole purpose
is comparing runs from CI and a laptop."* Two checkouts of the same tree at
different locations produce different reports.

Frame as a **conformance fix**, not a new schema design.

## Where

`src/partspec/runner.py:43,:47`; `src/partspec/report.py:184`;
`src/partspec/target.py:145-147`; `docs/SPEC-report.md:585`.

## Acceptance

- [ ] `part.source` is emitted relative to the contract's directory — the frame `_anchor` already uses, so it round-trips with no new concepts.
- [ ] `part.contract` is normalized to the same frame rather than echoing argv.
- [ ] Both are POSIX-separated.
- [ ] Two checkouts of the same tree at different locations yield **byte-identical** `part` blocks. This test fails today on `source`.
- [ ] No emitted path in `part` is absolute or contains a backslash.
- [ ] A source outside the contract's subtree stays absolute, and the spec says so — rather than emitting a `../../..` chain.

Do **not** invent `part.root`: `SPEC-report.md:585` says "project-relative", but
the word "project" appears nowhere else in `docs/`, `src/` or `tests/`.
Do **not** touch `invocation.argv` (`report.py:207`) — it is the literal record of
what was typed.
""",
    ["bug", "blocks-release"],
    "7",
)

# ---- agent loop / interface, epic #4 ----

add(
    "Every build must be bounded, and a blown budget must not read as a failing part",
    """## What

The mesh tier's 300 s bound (`src/partspec/engines/openscad.py:41`) is
**unreachable from the CLI**: `mesh.py:83` calls `openscad.render(source, out_dir)`
with no override, and `cli.py:38-58` offers only `--out` and `--quiet`.

The Python tier has **no bound at all**: `pycad.py:141` calls
`factory(**source.params)` in-process, so a non-terminating build123d or CadQuery
model hangs `partspec check` forever. Reproduced: exit 124 only when killed
externally.

## Why

#29 (batch), #28 (bounded repair loop) and #30 (convergence) all assume a run
terminates. An agent-driven loop that can hang has no bounded repair loop, it has
a stall. And when a build *is* killed, `runner.py:98-107` currently reports it as
`builds` FAIL — the design disproven by a stopwatch.

## Where

`src/partspec/engines/openscad.py:41`; `src/partspec/backends/mesh.py:83`;
`src/partspec/engines/pycad.py:141`; `src/partspec/cli.py:38-58`.

## Acceptance

- [ ] `--timeout SECONDS` on `check` and `measure`, defaulting from `PARTSPEC_TIMEOUT`, recorded in `invocation`.
- [ ] A test asserts the CLI value — not `DEFAULT_TIMEOUT_S` — is what applies.
- [ ] The Python tier gets a real bound (subprocess or watchdog), proven by a sleeping-factory test.
- [ ] A timeout yields `verdict: "error"` (exit 4) naming the elapsed budget, never the `builds` FAIL produced today.
- [ ] #29's batch verb applies the budget per target, and one timeout does not stop the rest.
""",
    ["enhancement"],
    "4",
)

add(
    "measure output must be as identifiable as a report",
    """## What

The `measure` payload (`src/partspec/cli.py:178-201`) carries only `part`,
`engine`, `geometry`, `measurements`, `refused` and `unavailable`. It has:

- no `schema_version` (contrast `report.py:31,195`)
- no `source` / `source_digest` / `source_closure` / `contract_digest` (contrast `report.py:184-192`)
- no `params`

## Why

A consumer cannot tell which file, which revision, or which parameter set
produced the numbers it is about to turn into checks — in the verb whose stated
purpose is bootstrapping contracts. Failure paths print plain text to stderr and
return bare ints (`cli.py:132`, `:138-141`), so a caller parsing stdout gets an
empty string and no machine-readable reason.

## Where

`src/partspec/cli.py:178-201`, `:132`, `:138-141`; `src/partspec/report.py:183-192`;
`src/partspec/runner.py:45-48`, `:120`.

## Acceptance

- [ ] An identity builder is **extracted** and called by both `runner.py:44-49` and `cli.py:178`. There is no existing shared builder to "reuse" — the part block is inline at `report.py:183-192` and the digest/closure helpers are runner-private (`_digest`/`_closure`, `_python_closure`).
- [ ] `measure` output carries `schema_version` and the identity block.
- [ ] `params` is emitted **with a caveat**: #9 documents that a misnamed OpenSCAD parameter reaches no variable and is silently dropped. Either land this after #9, or require that `measure`'s `params` carries the same honesty guarantee the report's does.
- [ ] Failure paths emit a JSON object on stdout with `schema_version`, the identity block, and `error` / `hint`.
- [ ] `cli.py:141`'s bare `4` routes through `exit_code(Verdict.ERROR)`.
- [ ] A test asserts the identity fields present in a report for a target are present, with equal values, in `measure` output for the same target.
""",
    ["enhancement"],
    "4",
)

add(
    "The MCP server must be launchable from an install",
    """## What

#27's Where is `src/partspec/mcp.py`, but:

- `pyproject.toml:22-28` lists only `mesh` / `occt` / `cadquery` extras
- `[project.scripts]` (`:30-31`) has a single `partspec` entry
- there is no MCP dependency declared anywhere

A server nobody can start is not a server.

## Why

#27 is epic #4's first real slice and the whole path to partspec being inside an
agent's tool list. It currently has no install story, so "MCP is ~100 lines"
(D5) is being measured against a surface that excludes every part of shipping it.

## Where

`pyproject.toml:22-31`.

## Acceptance

- [ ] An `mcp` extra declaring the MCP SDK.
- [ ] A launch surface: a `partspec-mcp` console script, or a `partspec mcp` subcommand.
- [ ] A clean-venv smoke test that an MCP client can connect and list the check / measure / render tools — extending the pattern #16's acceptance establishes.
- [ ] One acceptance bullet added to #27: *"an MCP client can start the server from a clean `pip install partspec[mcp]` and list its tools."*

Explicitly **not** in scope: packaging `skills/` as wheel package data. A
repo-root `skills/` is the correct plugin-conventional home, and site-packages is
not a discovery path any agent harness reads. For #22 / #23 / #28, add instead a
discovery bullet: *"a consumer can load this skill without hand-copying files —
the discovery path (repo checkout or plugin manifest) is documented in the README
and exercised by a test."*
""",
    ["enhancement", "agent-harness"],
    "4",
)

# ---- verification depth, epic #6 ----

add(
    "keep-out / keep-in regions: declare where material must and must not be",
    """## What

Let a contract declare a region of space and assert the part is **empty** there
(keep-out) or **solid** there (keep-in).

- **KOR** — a bolt hole, a slot, a wrench clearance. Material here blocks the
  mating part.
- **KIR** — a locating boss, a pin, a bearing seat. Missing material leaves
  nothing to mate against.

## Why

This is the check that expresses mechanical intent *without* a reference model and
*without* a second body. It subsumes much of what `min_wall`, bolt-circle
clearance and mounting-interface checks reach for, and unlike the relational
checks in POST-V0 §1 it needs no assembly support.

It is also externally validated: CADGenBench scores "interface match" exactly this
way, via authored keep-in / keep-out sub-volumes, as one of its four axes
alongside validity, shape similarity and Betti-number topology match.

**The boolean is already implemented on both tiers and has zero callers** —
`backends/mesh.py:286-292` and `backends/occt.py:182-183`, declared at
`mesh.py:50` and `occt.py:39`.

## Where

`src/partspec/contract.py:154-256` (authoring surface);
`src/partspec/backends/mesh.py:286-292`; `src/partspec/backends/occt.py:182-183`.

## Acceptance

- [ ] **The verification shell is mandatory.** A naive `keep_out` — intersection volume == 0 — is satisfied by a part with the material deleted, which is the exact vacuous green this repo exists to prevent. Each region is adjudicated together with a thin shell of the *opposite* material, so both an oversize and an undersize feature fail.
- [ ] The region is declared as **data on `Part`**, and materialized as a primitive inside each backend — `pyproject.toml:16-20` keeps the core stdlib-only, so no geometry library may be imported at the contract layer.
- [ ] Works on both tiers, with the same meaning.
- [ ] A part that satisfies the region and one that violates it are both covered by tests, on both tiers.

Note: the remaining work is the **authoring surface**, not the geometry.

Not framed as higher-leverage than epic #2 — #2 is re-scoped, not deprioritized.
""",
    ["enhancement"],
    "6",
)

# ---- provenance, epic #5 ----

add(
    "An unattributed dimensional limit is not evidence",
    """## What

Nothing detects a contract that was **circular when authored** — a limit derived
from the model's own constants, so the check cannot fail however the design
moves.

Reproduced (`notes/repros/circular-contract/`): every bound recomputed from the
same constants the model is built from.

| `plate_y` | exit |
|---|---|
| 30.0 | **0 — pass** |
| 25.0 | **0 — pass** |
| 5.0 | 1 — fail |

An agent that shrinks the plate to make something else fit gets a green run and
no signal that the part no longer meets its purpose.

## Why

#31's acceptance is entirely about a pinned digest or check-count **drifting
between runs**. A contract that was circular from its first commit never trips it.
No issue body in the tracker mentions circularity, self-reference, or the
provenance of a limit.

**The nuance that makes this tractable.** It is not fully vacuous — at
`plate_y=5.0` it *does* fail, because `bore_d=8` breaches the plate and
`genus`/`solid_count`/`watertight` catch it. That splits the vocabulary cleanly:

- **Topological checks are naturally non-circular.** `genus(1)` is an absolute
  claim; it cannot be re-derived from the parameters.
- **Dimensional checks are trivially circularizable.** `volume`, `envelope` and
  `param` are only as good as where their numbers came from — and nothing records
  where that was.

This is why epic #5 is the anti-circularity mechanism rather than a convenience:
the dogfood `bearing_608` takes `OD = 22.0` from ISO 15, not from the `.scad`.

## Where

`notes/repros/circular-contract/`; `src/partspec/contract.py`; report schema.

## Acceptance

- [ ] `notes/repros/circular-contract` is committed as a test fixture (currently excluded via `.git/info/exclude`), and its `plate_y = 30.0 / 25.0 / 5.0 → exit 0 / 0 / 1` table is pinned as the regression case.
- [ ] Provenance is recorded for the **dimensional** kinds only (volume, envelope, param). The topological kinds are absolute claims and are excluded by construction.
- [ ] The axis is **attributed vs unattributed**, not literal vs model-derived — a literal copied out of `partspec measure` is equally circular.
- [ ] A limit obtained through the reference tables epic #5 ships records its source; everything else records "unattributed".
- [ ] A run in which every dimensional check is unattributed emits a distinct warning, on the same channel as the empty-contract warning (`SPEC-contract.md` §6).
- [ ] **NOT a sixth status.** The five-member `Status` set (`status.py:40-60`) is closed; adding to it is a schema break.

Cross-reference #31: the pin catches a contract that *shrank*; this catches one
that never had external footing.
""",
    ["enhancement"],
    "5",
)

# ---- authoring, epic #3 ----

add(
    "Resolve the status of the untracked notes/ workspace",
    """## What

`git check-ignore -v notes/FINDINGS.md` → `.git/info/exclude:7`.

Because the exclusion lives in `.git/info/exclude` rather than `.gitignore`,
`git status` reports clean and **nothing in the repo records that `notes/`
exists** — it is invisible to review as well as to clones.

It currently holds:

- `notes/GAPS.md` — the capability gap inventory, source of all six epics
- `notes/FINDINGS.md` — 760 lines, W1–W10, source of #8–#16
- `notes/RESEARCH.md` — external research on agent CAD benchmarks and prior art
- `notes/audit-synthesis.md` — the 2026-08-06 tracker audit
- `notes/repros/circular-contract/` — a live reproduction
- `notes/upstream/` — vendored reference clones (each carries its own `.git`)

## Why

Original analysis authored for this project is reachable only from a path that no
clone, no reviewer and no CI run can see. That is the same class of loss #24
exists to prevent, one directory over.

## Where

`.git/info/exclude:7`; `notes/`.

## Acceptance

- [ ] Each artifact is decided per-item: promoted to `docs/`, moved to a real repo, or deleted with the reason written down.
- [ ] Whatever stays untracked (`notes/upstream/` vendored clones, regenerable `notes/issues-snapshot-*`) moves from `.git/info/exclude` into a **committed `.gitignore`** rule with a comment. Do not simply delete the exclude entry — `notes/upstream/cadgenbench` carries its own `.git`.
- [ ] `git check-ignore -v` on anything remaining under `notes/` points at `.gitignore`, not `.git/info/exclude`.
- [ ] No original analysis authored for this project is reachable only from an untracked path.

Do **not** broaden #24 to cover this — #24 is scoped to the CAD-failure
catalogue, and folding in partspec's own self-review plus an external research
memo makes it a grab-bag.
""",
    ["documentation"],
    "3",
)

add(
    "Ship a contract-authoring skill",
    """## What

Nothing teaches a *user of partspec* how to write a contract. #22 and #23 teach
CAD authoring; #28 teaches the repair loop; and the only contract-authoring
material is 331 lines of normative spec plus the README's single spacer example.

## Why

The contract is the whole interface. An agent that writes good OpenSCAD and then
declares `p.volume(min=v*0.99, max=v*1.01)` with `v` recomputed from its own
constants has learned nothing — see the circular-contract issue under epic #5.

## Where

`skills/` (repo root); references `docs/SPEC-contract.md`.

## Acceptance

- [ ] The closed v0 kind vocabulary is presented as a **decision table an author navigates**, pointing at `SPEC-contract.md:114-140` rather than restating it.
- [ ] `requires` vs `param` vs geometry checks, with the "structured form SHOULD be preferred" rule (`:118-123`) as a worked before/after.
- [ ] The load-bearing lesson is promoted out of the survey document: `PLAN.md:288-304` — *only against a reference the model does not contain* — paired with the auto-generation ban (`SPEC-contract.md:281-284`) and the retrofit path (`:293-299`).
- [ ] A test in the style of `tests/test_docs.py:50-88` asserts every contract in the skill builds and yields the verdict it claims.
- [ ] The skill **references** SPEC-contract.md sections and never paraphrases them — `AGENTS.md:67-69` makes `docs/` normative, so a second prose copy of the kind vocabulary is a drift hazard.

Explicitly out of scope, cross-reference only:

- status / exit-code → agent action (#28 owns it)
- sourcing a claim from a standard or datasheet (epic #5's goal)
- exemplar contracts at real complexity (#25)

**Nuance to get right:** the spec does *not* say measure output must never be
transcribed — §7 says the opposite (measure, read, decide which numbers are
intent, write those). What is forbidden is the **tool** generating them.
""",
    ["documentation", "agent-harness"],
    "3",
)

add(
    "Measure whether the authoring assets change agent output",
    """## What

A control/treatment run over N tasks, recording build success, contract pass rate
and lines of code, with and without each of #22 / #23 / #25 / #26.

## Why

Epic #3 ships five opinions with test coverage on their examples and none on
their effect. The external evidence says the effect is real but unevenly
distributed — few-shot examples move code generation about +21.5pp while
documentation prose moves it about +5pp — which, if it holds here, means #25
(worked exemplars) matters more than #22/#23 and is currently filed as though it
matters less.

## Where

`evals/` — shared with #30.

## Acceptance

- [ ] The un-guided **control arm** lands early; it needs no asset to exist.
- [ ] The treatment arm runs per asset as each ships.
- [ ] It **reuses #30's vehicle** — #30 already proposes `evals/` and per-run recording across seeded defect classes. Extend it with a guidance-present/absent dimension rather than standing up a second harness, and cross-link.
- [ ] Scoring uses partspec's own contracts on the exemplars from #25.

**Not a blocker.** A dependency on an asset that must exist to be A/B'd cannot
gate that asset. Blocked-by #22 for its first treatment arm only.

Do **not** use cadgenbench as the scorer: its ground truth is private and
evaluation runs server-side on the HF Space; only the validity gate runs locally.

Also not the highest-leverage item in epic #3 — #24 is, since the catalogue is one
`rm -rf` from gone and is the input every other sub-issue cross-references.
""",
    ["enhancement", "agent-harness"],
    "3",
)


def main() -> None:
    seen = existing_titles()
    print("== sub-epic ==")
    sub = create(SUBEPIC[0], SUBEPIC[1], SUBEPIC[2], seen)

    print("== new issues ==")
    created: dict[str, list[int]] = {}
    for title, body, labels, parent in ISSUES:
        pnum = sub if parent == "SUBEPIC" else int(parent)
        body = body.rstrip() + f"\n\nPart of #{pnum}.\n"
        n = create(title, body, labels, seen)
        created.setdefault(str(pnum), []).append(n)

    print("\n== children by parent ==")
    for p, kids in sorted(created.items(), key=lambda kv: int(kv[0])):
        print(f"  #{p}: {', '.join('#' + str(k) for k in kids)}")
    print(f"\nsub-epic = #{sub}")


if __name__ == "__main__":
    main()
