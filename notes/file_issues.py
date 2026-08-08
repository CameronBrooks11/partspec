#!/usr/bin/env python3
"""File the partspec epic tree. Idempotent-ish: prints numbers, does not re-run safely."""

import json
import subprocess
import sys

REPO = "CameronBrooks11/partspec"


def gh(*args: str, body: str | None = None) -> str:
    proc = subprocess.run(
        ["gh", *args], input=body, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        sys.exit(f"FAILED: gh {' '.join(args)}\n{proc.stderr}")
    return proc.stdout.strip()


def create(title: str, body: str, labels: list[str]) -> int:
    url = gh(
        "issue", "create", "-R", REPO, "--title", title,
        "--label", ",".join(labels), "--body-file", "-", body=body,
    )
    num = int(url.rstrip("/").split("/")[-1])
    print(f"  #{num}  {title}")
    return num


def slice_body(what: str, why: str, where: str, acceptance: list[str]) -> str:
    checks = "\n".join(f"- [ ] {a}" for a in acceptance)
    return f"## What\n\n{what}\n\n## Why\n\n{why}\n\n## Where\n\n{where}\n\n## Acceptance\n\n{checks}\n"


# ---------------------------------------------------------------- epics

EPICS: dict[str, dict] = {}

EPICS["correctness"] = dict(
    title="Epic: the checker must never report green on something it has not proven",
    labels=["epic", "blocks-release"],
    body="""## Goal

Make partspec's own thesis true of partspec. An adversarial review (15 agents, 10 confirmed
findings, 0 dismissed) found that **nine of the ten defects are the tool reporting green on
something it has not proven** — the first of the three failure modes `docs/SPEC-report.md`
§1.1 exists to prevent, committed by the project against itself.

## Why it matters

This blocks every other epic, and not as ceremony. A harness for AI agents built on a checker
that greens nine different wrong things is *worse than no harness*: it manufactures false
confidence at machine speed, across every part an agent touches. The thesis is right; the
implementation of the thesis is not yet trustworthy. Nothing else is worth building until it
is.

## Done means

- Every finding below has a fix **and a regression test that fails without it**.
- No new path can green an unproven result: each fix names the precondition it enforces.
- `just check && just test` green on both OpenSCAD legs; dogfood batch unchanged except where
  a finding legitimately changes a verdict.

## Sub-issues
""",
)

EPICS["perception"] = dict(
    title="Epic: an agent can see the part it made",
    labels=["epic", "agent-harness"],
    body="""## Goal

Give partspec eyes. Canonical multi-view renders, section cuts, and visual diffs, emitted as
files the report references — so a multimodal agent can *look at the part* instead of
reasoning only about numbers it declared itself.

## Why it matters

`grep -rn 'png\\|camera' src/` currently returns nothing. `docs/PLAN.md` §5 lists renders as
deliberately out of scope — a defensible call for a human-facing checker, because the human
opens the GUI. An agent has no GUI. It is designing blind.

The project already knows this: `PLAN.md` line 278 records that F13 was *"visible on
re-render, if anyone re-renders that part."* The need was written down and the capability was
excluded anyway.

This is the highest-leverage missing layer and the cheapest to build — OpenSCAD gives it away
via `--camera` / `--imgsize` / `-o out.png`, and the OCCT tier can tessellate and rasterise.

## Done means

An agent can ask for a part's appearance and get images back, from either tier, without
knowing which tier it is on.

## Sub-issues
""",
)

EPICS["authoring"] = dict(
    title="Epic: an agent can learn to write good CAD-as-code from this repo",
    labels=["epic", "agent-harness"],
    body="""## Goal

Ship the craft, not just the audit. Skills, idioms, worked exemplars and a source linter that
attack the actual observed symptom: agents produce CAD-as-code that is bloated, unparameterised
and structurally broken.

## Why it matters

The project ships **zero** agent-facing authoring assets. `AGENTS.md` is instructions for
agents editing *partspec's own code*, not for agents *using* partspec to design a part — a
conflation that let this gap sit unnoticed.

Worse: the empirical failure catalogue this project spent its whole dogfood phase building —
the Manifold backend emitting non-manifold edges while reporting `Status: NoError`, `assign()`
removal silently deleting gear teeth, clearance allowances baked into constants named for
nominal dimensions — lives in `results.md` in a **non-git scratch workspace** and ships
nowhere. We found the knowledge an agent needs and left it in a temp directory.

## Done means

An agent handed this repo has concrete, tested guidance on how to write a part well, and a
linter that catches the common structural mistakes before a render is ever attempted.

## Sub-issues
""",
)

EPICS["harness"] = dict(
    title="Epic: an agent can drive the full design loop",
    labels=["epic", "agent-harness"],
    body="""## Goal

The product, as originally briefed: a harness an AI agent uses to do mechanical design in
CAD-as-code. MCP surface, a bounded repair-loop contract, batch evaluation, a guard against the
agent weakening its own contract — and evidence that a real loop converges.

## Why it matters

D5's load-bearing claim is *"if the report is right, an MCP server is a thin adapter"* — about
100 lines. **That has never been tested.** Tagging v0.1.0 would freeze `schema_version: 1` as
a compatibility surface before its primary consumer has ever consumed it. If the report is
missing a field an agent loop needs, that is free to fix today and breaking after the tag.

The most important slice here is the convergence test. Every dogfood finding so far tested the
*measurement*. None tested the *loop*, which is the product.

## Done means

An agent, given only this tool's output, can take a deliberately broken part to green — or
escalate honestly when it cannot — and we have the transcript proving which.

## Sub-issues
""",
)

EPICS["reference"] = dict(
    title="Epic: an agent can know what correct is without inventing it",
    labels=["epic", "agent-harness"],
    body="""## Goal

Ship reference data and reusable contract fragments, so `p.conforms(iso.bearing_608)` is an
import rather than a recollection.

## Why it matters

**The deepest gap in the project.** Every payoff in the dogfood came from a *human* supplying
the external reference — ISO 15's 22 mm, Gridfinity's `42n − 0.5`, the NEMA 17 bolt pattern,
involute gear theory. An agent that does not already know what a correct part looks like cannot
write the contract that would catch it being wrong.

As built, partspec helps a knowledgeable author catch their own mistakes. It does not make an
ignorant agent competent. Closing that is what turns a checker into a design aid.

F16 is the worked example of what this buys: `bearing(608)` measures 22.5 mm where ISO 15 says
22.0, and finding that required knowing the standard.

## Done means

Common mechanical interfaces resolve to real numbers from an importable source, with provenance
recorded in the report.

## Status

Coarse by design (`plan-epic`: decompose to the first shippable slices, not the whole tree).
Sub-issues to be cut when this epic is next.

Candidate slices: fastener/bearing/NEMA reference tables · reusable contract fragments ·
provenance for a referenced standard in the report · a policy for what is in scope to vendor.
""",
)

EPICS["depth"] = dict(
    title="Epic: verification deep enough for real mechanical intent",
    labels=["epic"],
    body="""## Goal

The checks mechanical design actually makes: hole diameters, bolt circles, fillet radii — plus
`diff`, which is the only thing that detects an agent silently weakening its own contract.

## Why it matters

The v0 vocabulary (`envelope`, `watertight`, `solid_count`, `genus`, `topology`) is what could
be measured honestly on both tiers, not what a mechanical engineer asserts. `hole_diameter`,
`bolt_circle` and `fillet_radius` are all recorded in `docs/POST-V0.md` §4 as BREP-tier and
irreducibly `unsupported` on mesh.

`diff` (POST-V0 §2) closes the one gap `SPEC-report.md` §7.1 names as undetected in v0: an
agent that deletes a check produces an internally consistent green report. `counts.total` and
`contract_digest` make that detectable *on comparison* — and the comparator does not exist.

## Done means

A contract can state the things a drawing would, and two reports can be compared semantically.

## Status

Coarse by design. Sub-issues to be cut when this epic is next.

Candidate slices: `hole_diameter` · `bolt_circle` / hole pattern · `fillet_radius` · `diff` ·
per-component vector statuses (POST-V0 §7, an agent needs the failing axis to act) ·
first real exercise of the `approximate` machinery.
""",
)

EPICS["release"] = dict(
    title="Epic: release v0.1.0",
    labels=["epic"],
    body="""## Goal

Packaging that installs from a clean machine, a published artifact, branch protection, and a
tag.

## Why it matters

Deliberately **gated**, and the gate is the point.

- Gated on the correctness epic: tagging a checker that greens nine unproven things would put
  a false-confidence machine in front of agents.
- Gated on the harness epic's convergence slice: `schema_version: 1` becomes a compatibility
  surface at the tag, and it should not freeze before its primary consumer has used it.

Branch protection is OFF deliberately (`docs/PLAN.md` §4) with "before v0.1.0 is tagged" as the
recorded trigger — squash-only merges are already locked; what remains is requiring the `ok`
status check and linear history.

## Done means

`pip install partspec[mesh]` works from a clean machine, `main` is protected, `v0.1.0` is
tagged, and every claim in the README is true of the tagged artifact.

## Status

Coarse by design. Sub-issues to be cut when this epic is next.

Candidate slices: build + install-test the wheel in CI · README states the agent purpose ·
PyPI publish · branch protection (`ok` + linear history) · tag and release notes from
CHANGELOG.
""",
)

# ---------------------------------------------------------------- slices

SLICES: dict[str, list[tuple[str, list[str], str]]] = {}

SLICES["correctness"] = [
    (
        "requires() must reject a non-predicate expression instead of coercing it with bool()",
        ["bug", "blocks-release"],
        slice_body(
            what="`evaluate()` ends with `return bool(result), namespace`, so a `requires` "
            "expression that is arithmetic rather than a comparison is truthiness-coerced. "
            "A one-character slip turns a claim **violated by its own declared parameters** "
            "into a green check.\n\n"
            "```python\n"
            "p.requires(\"bore_d + 2 * wall - plate_y\")   # meant <=, typed -\n"
            "# bore_d=40, wall=2, plate_y=30  ->  evaluates to 14  ->  truthy  ->  PASS, exit 0\n"
            "p.requires(\"1\")                              # PASS, zero operands\n"
            "```\n\n"
            "Both reproduce today. `detail` is `null`, so nothing in the report or the console "
            "summary hints at it, and the JSON is internally consistent.",
            why="`SPEC-report.md` §1.1's first named failure mode, reached through a check that "
            "*looks* declared — worse than the vacuous-green case the tool already guards, "
            "because the claim is present, disproven by the operands printed beside it, and "
            "green.\n\n"
            "Every other claim shape in the tool is guarded against claiming nothing: "
            "`Limit.__post_init__` (\"a limit must constrain something\"), `adjudicate()` "
            "(\"a check that claims nothing must not report pass\"), `Part.topology()`. "
            "`requires` is the single unguarded one, and `SPEC-contract.md` §4.1 calls it "
            "\"the escape hatch for anything relational\" — i.e. the most-used shape.\n\n"
            "`describe()` has the same latent assumption: `requires(\"plate_y - plate_y\")` "
            "fails with the nonsense detail *\"plate_y - plate_y is false with plate_y=30.0\"*.",
            where="`src/partspec/expr.py:127`",
            acceptance=[
                "A `requires` expression whose top-level AST node is not `Compare`/`BoolOp`/"
                "`UnaryOp(Not)` raises `ContractError` (→ `verdict: \"error\"`, exit 4)",
                "A non-`bool` evaluation result raises rather than coercing",
                "`requires(\"1\")` and `requires(\"a - b\")` both error; `requires(\"a <= b\")` "
                "and `requires(\"0 < x < 10\")` still work",
                "`SPEC-contract.md` §5 documents the accepted expression shapes",
                "Regression tests for each rejected shape",
            ],
        ),
    ),
    (
        "An OpenSCAD parameter that reaches no variable must be an error, not a silent drop",
        ["bug", "blocks-release"],
        slice_body(
            what="`_define_args` emits `-D name=value` for every declared parameter without "
            "checking that `name` is a top-level variable in the include closure, and OpenSCAD "
            "accepts an unknown `-D` silently — no warning, exit 0.\n\n"
            "A misnamed parameter therefore never reaches the geometry. The engine renders the "
            "`.scad`'s own defaults while `report.params` records the contract's values, and "
            "every `requires` / `param_range` check adjudicates against values that built "
            "nothing. Reproduced: a spacer contract naming `bore_dia` where the source says "
            "`bore_d` scores **7 green checks, exit 0**, on a part measured to contain the "
            "default d=8 bore rather than the declared d=20.",
            why="`SPEC-contract.md` §3 states the opposite as normative: *\"`params` are the "
            "single source of truth for the build… the contract wins and the report records the "
            "contract's value.\"* Here the `.scad` wins and the report records the contract's "
            "value — the two halves of the report describe different parts and nothing says so.\n\n"
            "For an agent this is severe: a hallucinated or drifted parameter name produces a "
            "fully green report on an unchanged part, which reads as \"my edit worked\".",
            where="`src/partspec/engines/openscad.py:125` (`_define_args`), "
            "`src/partspec/engines/openscad.py:207` (render)",
            acceptance=[
                "Every `-D` name is resolved against top-level assignments in the include "
                "closure before rendering",
                "A parameter matching no variable is a `BuildError` naming it, and suggesting "
                "near-misses where one exists",
                "The `method=` path is covered too (parameters become call arguments there)",
                "A parameter that legitimately cannot be resolved statically (computed include) "
                "degrades to a recorded warning rather than a false error — the closure already "
                "reports `partial`",
                "Regression test: the `bore_dia`/`bore_d` case fails instead of scoring 7 green",
            ],
        ),
    ),
    (
        "Orientation is a measurement precondition: an inward-wound closed mesh must refuse, not return a negative volume",
        ["bug", "blocks-release"],
        slice_body(
            what="`_not_a_solid`'s winding check accepts a *consistently inward* mesh, because "
            "consistency is not orientation. An inverted cube reports:\n\n"
            "```\n"
            "volume         -> Measurement(value=-1000.0, unit='mm3', exact=True)\n"
            "center_of_mass -> Measurement(value=(-0.0, -0.0, -0.0), exact=True)\n"
            "watertight     -> True\n"
            "```\n\n"
            "A negative volume, flagged `exact`. Any `volume(max=…)` bound passes trivially.",
            why="D17 made preconditions per-quantity and narrow, which was right, but this one "
            "is necessary and not sufficient. A signed integral over an inward-oriented surface "
            "is not a volume, and reporting it as `exact` is the unsupported-as-pass mode with "
            "extra steps.\n\n"
            "Inverted normals are a routine real-world defect — mirrored geometry, a "
            "hand-written `polyhedron` with reversed face order, some STL exporters.",
            where="`src/partspec/backends/mesh.py:354`",
            acceptance=[
                "Orientation is checked separately from winding consistency",
                "An inward-oriented closed mesh refuses `volume` and `center_of_mass`, naming "
                "the defect (\"the surface is oriented inward\")",
                "A correctly-oriented mesh is unaffected — no over-refusal (D17)",
                "`genus` and `solid_count` are considered independently: orientation may not "
                "block them",
                "Regression test built with trimesh `.invert()`, plus a partially-inverted mesh",
            ],
        ),
    ),
    (
        "solid_count must count solids, not surface shells — a sealed cavity is one solid on both tiers",
        ["bug"],
        slice_body(
            what="`_face_components` counts connected surface shells. A solid with a sealed "
            "internal void is two shells and one solid:\n\n"
            "```\n"
            "hollow (20mm cube with a sealed 5mm void)\n"
            "  solid_count -> 2   (exact)\n"
            "  genus       -> Unsupported: 'defined per body; this part has 2 solids'\n"
            "  volume      -> 7875.0   (correct: 8000 - 125)\n"
            "```\n\n"
            "OCCT reports 1 for the same shape. `volume` is right while `solid_count` is wrong, "
            "so the report is internally inconsistent, and the wrong count then **blocks genus** "
            "via the multi-body guard.",
            why="Breaks the one-contract property that the whole tier design rests on: the same "
            "contract must evaluate identically wherever it can be evaluated. A shape both tiers "
            "can represent must not get two different answers.\n\n"
            "Also a false `incomplete`: over-refusal is its own way of not answering (D17), and "
            "here it is caused by a wrong number rather than a real ambiguity. Sealed voids are "
            "ordinary in printed parts.",
            where="`src/partspec/backends/mesh.py:203`",
            acceptance=[
                "A shell fully enclosed by another is attributed to its parent solid, not "
                "counted separately",
                "`solid_count` agrees with the OCCT tier on: a sealed cavity, nested cavities, "
                "two disjoint solids, and a solid with a through-hole",
                "`genus` is no longer blocked by a cavity, and is correct for a hollow solid",
                "Cross-tier parity test asserting the two backends agree on each shape",
            ],
        ),
    ),
    (
        "A multi-body Python model must not be silently truncated to its first solid",
        ["bug", "blocks-release"],
        slice_body(
            what="The CadQuery adopt path takes the first solid of a multi-body result and "
            "discards the rest. A two-body part then passes `solid_count(1)` and an `envelope` "
            "measured over one body — all flagged `exact`.",
            why="Same class as W2: the report describes a part that was not built. Here the tool "
            "silently redefines the subject of every subsequent measurement, so a contract "
            "asserting \"this is one solid\" is confirmed *by the act of discarding the "
            "evidence*.\n\n"
            "`solid_count` exists precisely to catch a part that fell apart. This makes it "
            "structurally incapable of doing so on the CadQuery tier.",
            where="`src/partspec/engines/pycad.py:77`",
            acceptance=[
                "A multi-solid result is adopted whole, as a compound",
                "`solid_count` reports the true count for a two-body CadQuery model",
                "If a primitive genuinely cannot operate on a compound, it refuses (naming why) "
                "rather than silently narrowing its subject",
                "build123d multi-body results are covered by the same test",
            ],
        ),
    ),
    (
        "Every run must leave a report describing that run — no previous verdict may survive",
        ["bug", "blocks-release"],
        slice_body(
            what="A contract that raises during `resolve()` writes no report, so the previous "
            "run's file stays on disk at the deterministic path:\n\n"
            "```sh\n"
            "partspec check s.py:part   # run 1, valid contract   -> exit 0, report verdict=pass\n"
            "# edit the contract so it raises\n"
            "partspec check s.py:part   # run 2                   -> exit 4\n"
            "cat outputs/s-part/report.json                       -> verdict: \"pass\"\n"
            "```\n\n"
            "**Self-inflicted, today.** Before commit `36a7b49` this path produced a traceback "
            "and exit 1. That fix made it exit 4 cleanly — and quieter, because the stale green "
            "report now sits undisturbed.",
            why="`write_placeholder` exists for exactly this and is called *after* `resolve()`, "
            "so it never runs on this path. `report.py`'s own comment: *\"a stale "
            "`verdict:\"pass\"` left at a deterministic path is the worst failure this tool "
            "has.\"*\n\n"
            "Any consumer reading the artifact rather than the exit code — which is what D5 says "
            "the artifact is *for* — sees green.",
            where="`src/partspec/cli.py:93`, `src/partspec/report.py` (`write_placeholder`)",
            acceptance=[
                "The placeholder is written before anything that can fail, including contract "
                "resolution — it needs only the out dir and argv, not a resolved `Part`",
                "After a raising contract, the report on disk describes the failed run "
                "(`verdict: \"error\"`), never the previous one",
                "Same for an unresolvable target, a usage error, and a native crash mid-run",
                "Test asserts the on-disk artifact after a failed run, not just the exit code",
            ],
        ),
    ),
    (
        "A non-finite measurement must never adjudicate as pass, and must never reach the JSON",
        ["bug"],
        slice_body(
            what="A `NaN` measurement adjudicates as a conclusive `pass`, and the report it "
            "lands in is not valid JSON (Python's `json` emits bare `NaN`, which no conforming "
            "parser accepts).",
            why="Two failures at once: the verdict is wrong, and the artifact that records it is "
            "unparseable — so a consumer either trusts a false pass or cannot read the file at "
            "all. `NaN` propagates from degenerate geometry (zero-area faces, a centroid of an "
            "empty set), which is exactly when a checker must be most careful.\n\n"
            "The comparison semantics are the root cause: every `NaN` comparison is false, so "
            "\"not outside the bounds\" reads as \"inside\".",
            where="`src/partspec/status.py:236`",
            acceptance=[
                "A non-finite measurement (`NaN`, `±inf`) never yields `pass` — it is a refusal "
                "naming the quantity",
                "`Report.write` refuses to emit non-conforming JSON (`allow_nan=False`) and "
                "fails loudly rather than writing an unparseable artifact",
                "Vector measurements with one non-finite component are covered",
                "The schema conformance test rejects a document containing `NaN`",
            ],
        ),
    ),
    (
        "A build artifact must never be reused across runs",
        ["bug"],
        slice_body(
            what="A stale STL left in the out dir from a previous run is measured as if it were "
            "this run's build — green report, exit 0, on geometry this run never produced.",
            why="Same family as the stale report, one layer down, and it defeats the provenance "
            "work outright: `source_digest`, the include closure and `engine.version` all "
            "describe a build whose *output was not the thing measured*.\n\n"
            "It bites hardest in the loop this project is for. An agent edits a model, the "
            "render fails for an unrelated reason, and the previous geometry passes — so the "
            "agent concludes its edit worked.",
            where="`src/partspec/engines/openscad.py:214`",
            acceptance=[
                "The target artifact is removed (or written to a fresh path) before the engine "
                "runs, so a failed render cannot leave a previous success in place",
                "Existing guard (`exited 0 but produced no geometry`) still holds",
                "The Python tiers are checked for the same hazard",
                "Regression test: plant a stale STL, make the render fail, assert the run does "
                "not report on it",
            ],
        ),
    ),
    (
        "partspec[cadquery] must install a tier that actually works",
        ["bug"],
        slice_body(
            what="The advertised `cadquery` extra is `[\"cadquery>=2.8,<3\"]` and omits "
            "build123d — but the OCCT backend adopts CadQuery shapes *through* build123d "
            "(`engines/pycad.py` does `import build123d as bd`). Installing the extra alone and "
            "running the CLI crashes with an uncaught traceback, exiting **1** — partspec's code "
            "for \"the part failed its contract\".",
            why="A documented install path that cannot work, failing with the exit code that "
            "means something else entirely. `pyproject.toml` advertises `cadquery` in its "
            "keywords and extras, and `README.md` lists CadQuery as a supported engine.\n\n"
            "It is also the second instance of a missing dependency surfacing as exit 1; the "
            "general lesson belongs with the import-error handling.",
            where="`pyproject.toml:28`",
            acceptance=[
                "`cadquery` extra pulls whatever the tier genuinely needs (or is documented as "
                "requiring `occt` alongside it)",
                "A missing engine dependency produces a clear message and the error exit code, "
                "never a traceback and never exit 1",
                "CI install-tests each advertised extra in a clean venv, the way "
                "`test-mesh-only` does for `mesh`",
            ],
        ),
    ),
]

SLICES["perception"] = [
    (
        "partspec render: canonical multi-view PNGs on the mesh tier",
        ["enhancement", "agent-harness"],
        slice_body(
            what="A `render` verb that produces a fixed set of views — isometric, front, top, "
            "right — as PNGs at a known size, for an OpenSCAD source. Deterministic camera "
            "framing so two runs of the same part are pixel-comparable.",
            why="The thinnest end-to-end slice that gives an agent eyes. OpenSCAD supplies it "
            "directly (`--camera`, `--imgsize`, `-o out.png`), and both binaries in the CI "
            "matrix render headless with no display — already verified.\n\n"
            "Canonical rather than arbitrary views because an agent needs to compare across "
            "iterations, and a camera that moves makes every comparison ambiguous.",
            where="`src/partspec/engines/openscad.py`, `src/partspec/cli.py`",
            acceptance=[
                "`partspec render <target>` writes a named PNG per canonical view",
                "Camera framing is derived from the part's bounding box and is stable across "
                "runs of identical geometry",
                "Works headless on both engines in the CI matrix",
                "A render failure is a `BuildError`, never a silent missing file",
                "Rendering never substitutes for measurement — the images carry no verdict",
            ],
        ),
    ),
    (
        "Renders on the OCCT tier, from the same verb",
        ["enhancement", "agent-harness"],
        slice_body(
            what="The same `render` verb and the same canonical views for build123d and CadQuery "
            "parts.",
            why="Tier-transparency is the property the whole backend design exists to protect: "
            "an agent should ask for the part's appearance without knowing which engine built "
            "it. A render verb that works on one tier only would reintroduce exactly the "
            "asymmetry `SPEC-backend.md` is written to prevent.",
            where="`src/partspec/backends/occt.py`, `src/partspec/engines/pycad.py`",
            acceptance=[
                "Identical view names and framing rules across tiers",
                "Tessellation quality is recorded, since under D15 it is part of what is shown",
                "A part expressed in both engines produces comparable images (differential test "
                "extended)",
            ],
        ),
    ),
    (
        "Section cuts, so internal features are visible at all",
        ["enhancement", "agent-harness"],
        slice_body(
            what="Render a cut through a named plane (`xy`/`xz`/`yz` at an offset), so bores, "
            "cavities, wall thicknesses and internal ribs can be seen.",
            why="External views cannot show the features most often wrong. F16's bore is "
            "invisible from outside; F15's failure was topological. An agent looking only at "
            "exteriors is blind to most of what it gets wrong, and \"looks fine\" is precisely "
            "the failure this project documented.",
            where="render pipeline",
            acceptance=[
                "A cut plane and offset are selectable, with a sane default derived from the "
                "bounding box centre",
                "Cut faces are visually distinct from surfaces",
                "Works on both tiers",
            ],
        ),
    ),
    (
        "The report references the renders it produced",
        ["enhancement"],
        slice_body(
            what="Record produced image paths in the report, so one artifact points to "
            "everything a run generated.",
            why="`SPEC-report.md` §9 already fixes the shape: *\"No embedded renders. Images are "
            "files on disk referenced by path, never inline.\"* This makes the report the single "
            "handle an MCP layer returns, rather than the agent having to guess filenames.",
            where="`src/partspec/report.py`, `docs/SPEC-report.md`",
            acceptance=[
                "Report carries the image paths with their view names",
                "Spec section added and the schema example updated",
                "Absent renders are absent, never an empty-string path that reads as a file",
            ],
        ),
    ),
    (
        "Visual diff between two runs",
        ["enhancement"],
        slice_body(
            what="Given two runs of the same part, produce a per-view image diff highlighting "
            "what moved.",
            why="Pairs with the semantic `diff` in the verification-depth epic: one shows *what "
            "changed in the claims*, this shows *what changed in the part*. Together they are "
            "the review an agent cannot otherwise perform on its own work.",
            where="new module; consumes the render outputs",
            acceptance=[
                "Identical geometry produces an empty diff (which is what canonical framing "
                "buys)",
                "Output is an image plus a scalar change magnitude",
                "Handles differing image sizes by refusing rather than rescaling silently",
            ],
        ),
    ),
]

SLICES["authoring"] = [
    (
        "Ship an OpenSCAD authoring skill in the repo",
        ["documentation", "agent-harness"],
        slice_body(
            what="A skill directory shipped by partspec — not on one machine — teaching an agent "
            "to write OpenSCAD well: parameterise instead of hardcoding, build from datums, "
            "decompose into modules, a `$fn` policy, epsilon overlap on coincident faces in "
            "booleans, `difference()` ordering traps, and when `hull`/`minkowski` cost more than "
            "they save.",
            why="Directly attacks the observed symptom: agent-written OpenSCAD is bloated and "
            "structurally broken. The project currently ships nothing of the kind — `AGENTS.md` "
            "is for agents editing partspec's own code, which is a different audience "
            "entirely.\n\n"
            "It also pays back into verification: a part written from datums with named "
            "parameters is a part whose contract is obvious to write.",
            where="new `skills/openscad-authoring/`",
            acceptance=[
                "Guidance is concrete and checkable, not platitudes — each rule has a worked "
                "before/after",
                "Complexity discipline is explicit (module decomposition, when a part should be "
                "split)",
                "Cross-references the failure catalogue",
                "A test asserts the examples in the skill actually build and satisfy what they "
                "claim, the way `tests/test_docs.py` does for the README",
            ],
        ),
    ),
    (
        "Ship a build123d / CadQuery authoring skill",
        ["documentation", "agent-harness"],
        slice_body(
            what="The same for the Python tiers: builder-vs-algebra mode, sketch-then-extrude "
            "discipline, selector fragility, joints and locations, and the version-pinning "
            "hazard.",
            why="The Python engines fail differently from OpenSCAD, and F8 already recorded two "
            "of the hazards the hard way: community build123d libraries are pinned to the "
            "build123d of their writing, and community models are scripts rather than "
            "parameterised callables. Selector-based code is the classic silent breaker — a "
            "selector that matches the wrong face still builds.",
            where="new `skills/build123d-authoring/`",
            acceptance=[
                "Covers both build123d and CadQuery, and where the adopt shim makes them "
                "interchangeable",
                "Documents the adapter pattern for scripts-not-callables (F8)",
                "Examples build and are asserted in CI",
            ],
        ),
    ),
    (
        "Promote the empirical failure catalogue into the repo",
        ["documentation", "agent-harness"],
        slice_body(
            what="Move the dogfood findings from the non-git scratch workspace into shipped "
            "documentation, as a catalogue of *observed* CAD-as-code failure modes with repros: "
            "the Manifold backend emitting non-manifold edges while reporting `Status: NoError`, "
            "`assign()` removal deleting gear teeth, allowances baked into constants named for "
            "nominal dimensions, holes breaching a boundary and becoming notches.",
            why="This is the most valuable thing the project produced and it ships nowhere. "
            "`~/repos/partspec-dogfood/results.md` is **not a git repo** — one `rm -rf` from "
            "gone, and invisible to anyone using the tool.\n\n"
            "It is also the highest-signal input an agent could have: real failures, with "
            "reproductions, from real libraries.",
            where="new `docs/FAILURE-MODES.md`, sourced from `partspec-dogfood/results.md`",
            acceptance=[
                "Each entry: symptom, root cause, how it was detected, what it looks like when "
                "green",
                "Findings are reproducible from the repo or clearly marked as needing an "
                "external corpus",
                "Cross-referenced from both authoring skills",
                "The dogfood workspace's status as scratch is resolved — either it is a repo, or "
                "everything load-bearing lives here",
            ],
        ),
    ),
    (
        "Worked exemplars at real complexity",
        ["documentation", "agent-harness"],
        slice_body(
            what="Two or three complete, well-written parts with their contracts — a bracket "
            "with a bolt pattern, a housing with a sealed cavity, a parametric family — beyond "
            "the trivial `examples/spacer`.",
            why="An agent imitates what it is shown. One trivial example teaches nothing about "
            "structuring a real part, and the corpus we have been checking is third-party code "
            "we do not control and would not hold up as exemplary.\n\n"
            "These double as fixtures for the tier-parity and cavity tests the correctness epic "
            "needs.",
            where="`examples/`",
            acceptance=[
                "Each exemplar is parameterised, decomposed, and has a contract asserting "
                "external references rather than its own output",
                "Each is in the dogfood batch and stays green",
                "At least one exists in two engines, extending the differential test",
            ],
        ),
    ),
    (
        "partspec lint: catch structural mistakes in CAD source before rendering",
        ["enhancement", "agent-harness"],
        slice_body(
            what="A linter over CAD source: unnamed magic numbers in geometry, absent `$fn` "
            "policy on curved features, coincident-face booleans without epsilon overlap, "
            "suspicious `difference()` ordering, and module size/nesting thresholds.",
            why="Fast feedback at authoring time, before an engine runs — the loop an agent needs "
            "most, since a render costs seconds and a lint costs nothing.\n\n"
            "It attacks the LoC symptom head-on, and catches the class of defect that produces "
            "*valid* geometry that is wrong (coincident faces yield non-manifold edges — F10's "
            "root cause).",
            where="new `src/partspec/lint/`",
            acceptance=[
                "Rules are individually documented with a rationale and a real example",
                "Findings carry file:line and are machine-readable, same discipline as the "
                "report",
                "A lint finding is advisory and never a verdict on the part — it is about the "
                "source",
                "Runs without an engine installed",
            ],
        ),
    ),
]

SLICES["harness"] = [
    (
        "MCP server over check / measure / render — the spike that tests D5",
        ["enhancement", "agent-harness"],
        slice_body(
            what="A real MCP server exposing the existing primitives. Not a stub: enough for an "
            "agent to build, measure, look at and check a part through tools alone.",
            why="D5's load-bearing claim is *\"if the report is right, an MCP server is a thin "
            "adapter\"* — about 100 lines. **Never tested.** Either it holds and the architecture "
            "is vindicated, or it does not and we learn which fields the report is missing.\n\n"
            "Timing is the point: tagging v0.1.0 freezes `schema_version: 1` as a compatibility "
            "surface. A schema gap found now is free; found after the tag it is breaking. This "
            "is `SPEC-report.md`'s own report-before-verbs argument applied one level up.",
            where="new `src/partspec/mcp.py`",
            acceptance=[
                "Tools for check, measure and render, returning the report artifact rather than "
                "prose",
                "Library modules stay free of MCP imports (D5)",
                "Any report-schema change the adapter forces is recorded as a finding against "
                "D5 in `DECISIONS.md`",
                "The line count is reported honestly against the ~100-line claim",
            ],
        ),
    ),
    (
        "The agent contract: bounded repair loop, honest escalation",
        ["documentation", "agent-harness"],
        slice_body(
            what="A shipped document telling an agent how to *use* partspec: a bounded 3–5 "
            "attempt repair loop, machine-greppable escalation "
            "(`HUMAN_REVIEW: <why> — last failure: <assertion>`), feeding the previous failure "
            "forward rather than restarting, and the explicit vacuous-green warning — check the "
            "contract is non-empty before believing a green run on an unfamiliar file.",
            why="Recorded in `POST-V0.md` §3 as the strongest artifact in cad-khana and never "
            "built. Without a bound, an agent loops; without escalation, it fakes success; "
            "without feed-forward, it rediscovers the same failure repeatedly.\n\n"
            "The vacuous-green warning matters most: `SPEC-report.md` calls an empty contract "
            "*\"the single most likely output when an agent does not know what to assert.\"*",
            where="new `skills/using-partspec/` or `docs/AGENT-CONTRACT.md`",
            acceptance=[
                "Attempt bound and escalation format are specified exactly, and greppable",
                "Explicitly forbids weakening the contract to reach green, and names the guard "
                "that detects it",
                "Maps each exit code to the action an agent should take",
                "Distinguishes `incomplete` from `fail` in what it tells the agent to do",
            ],
        ),
    ),
    (
        "Multi-target check, so a batch costs one interpreter start",
        ["enhancement", "agent-harness"],
        slice_body(
            what="`partspec check` accepts several targets and evaluates them in one process, "
            "emitting one report per part plus a batch summary.",
            why="D5 answers OCP's multi-second import cost with batching rather than a daemon, "
            "and the batch verb was never built — `run-batch.sh` in the scratch workspace stands "
            "in. An agent iterating over a set of parts currently pays the import cost every "
            "time.\n\n"
            "**Carries a known hazard** (`POST-V0.md` §8): `sys.modules` caches a model's helper "
            "modules, so a second contract in the same process that imports an edited helper "
            "gets the previous version — a stale build reported as fresh. This slice owns fixing "
            "that.",
            where="`src/partspec/cli.py`, `src/partspec/runner.py`",
            acceptance=[
                "One process, N targets, N reports plus a summary",
                "The model's directory subtree is invalidated from `sys.modules` between targets, "
                "with a test proving an edited helper is picked up",
                "Batch exit code is the worst individual verdict",
                "One part erroring does not prevent the rest from being evaluated",
            ],
        ),
    ),
    (
        "Prove an agent loop actually converges",
        ["agent-harness"],
        slice_body(
            what="Point a real agent at a deliberately broken part with **only** partspec's "
            "output to work from — no human hints — and record whether it reaches green, how "
            "many attempts it takes, and where it thrashes. Repeat across a handful of seeded "
            "defect classes: wrong dimension, breached hole (F15), non-manifold geometry, "
            "missing feature.",
            why="**The dogfood for the actual product.** Every finding so far tested the "
            "*measurement*; none tested the *loop*. The project's stated purpose is a harness "
            "for agents doing CAD, and there is currently no evidence that an agent can use it "
            "to get anywhere.\n\n"
            "This is also the honest gate on release. If an agent cannot drive a broken part to "
            "green from the tool's output alone, the tool has not delivered what it exists for, "
            "however correct its geometry is.",
            where="new `evals/` or the dogfood workspace",
            acceptance=[
                "At least four seeded defect classes, each run repeatedly",
                "Recorded per run: converged or not, attempts used, whether it tried to weaken "
                "the contract, whether it escalated honestly when stuck",
                "Written up in the dogfood house style — numbered findings, root cause",
                "Failures here become issues, not excuses; a non-converging class is a product "
                "defect",
            ],
        ),
    ),
    (
        "Detect the agent weakening its own contract, within a single run",
        ["enhancement", "agent-harness"],
        slice_body(
            what="A way to pin what a contract is expected to assert — `--expect-digest` / "
            "`--expect-checks N`, or a committed lockfile — so a run fails when the contract has "
            "silently shrunk.",
            why="**The central agent threat.** \"Make the check pass\" and \"delete the check\" "
            "are the same action from where a model sits, and the result is an internally "
            "consistent green report. `SPEC-report.md` §7.1 names this as the one known "
            "undetected gap in v0.\n\n"
            "`counts.total` and `contract_digest` already make it detectable *on comparison* — "
            "but the comparator is `diff`, which is post-v0. A single-run guard is the cheap "
            "80%, and unlike `diff` it works in CI with no previous artifact to hand.",
            where="`src/partspec/cli.py`, `src/partspec/report.py`",
            acceptance=[
                "A run whose contract digest or check count differs from the pinned value fails "
                "with a distinct, unambiguous message",
                "The pin is easy to update deliberately and hard to update accidentally",
                "Covers the check *set*, not just the count — swapping a strict check for a lax "
                "one must not slip through",
                "The agent contract document tells agents this exists and that defeating it is "
                "out of bounds",
            ],
        ),
    ),
]

# ---------------------------------------------------------------- file

order = ["correctness", "perception", "authoring", "harness", "reference", "depth", "release"]
epic_nums: dict[str, int] = {}

print("Creating epics…")
for key in order:
    e = EPICS[key]
    epic_nums[key] = create(e["title"], e["body"], e["labels"])

for key in order:
    if key not in SLICES:
        continue
    print(f"\nSlices for #{epic_nums[key]} ({key})…")
    children = []
    for title, labels, body in SLICES[key]:
        full = f"{body}\n---\nPart of #{epic_nums[key]}\n"
        children.append((create(title, full, labels), title))
    body = EPICS[key]["body"] + "\n" + "\n".join(f"- [ ] #{n} {t}" for n, t in children) + "\n"
    gh("issue", "edit", str(epic_nums[key]), "-R", REPO, "--body-file", "-", body=body)

print("\nEpics:", json.dumps(epic_nums))
