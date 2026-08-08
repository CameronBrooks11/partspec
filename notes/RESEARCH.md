# External research — AI agents doing CAD-as-code (2025–2026)

Gathered 2026-08-05 to check partspec's direction against published work.

---

## 1. The failure cascade — external validation of partspec's thesis

Two independent 2026 benchmarks find the *same* three-stage cascade, and both find each
stage degrades sharply from the last.

**Text2CAD-Bench** (arXiv 2605.18430):
- Invalidity Rate (code fails to execute / times out / degenerate output) rises from
  ~11–20% at complexity L1 to **68–70% at L3** for GPT-5.2, Claude-4.5-Sonnet, DeepSeek-V3.2.
- Among the code that *does* run, Chamfer Distance worsens 2.1×, IoU falls 0.59 → 0.23.
- **The load-bearing finding:** *"Executability and design quality are largely independent."*
  Gemini3-Flash has the best invalidity rate (17%) by a wide margin and among the *worst*
  feature-level scores.

**MUSE** (arXiv 2605.28579) staged the same way, on assemblies:
- closed-source leaders: code executes ~65–77% → geometrically valid ~59–71% →
  design-intent aligned **~39–54%**.
- open-source average: 21% → 13% → **5%**.
- Even the best models score 40–55% on fine-grained manufacturability/assemblability.

**What this means for partspec.** The cascade is exactly partspec's status ladder —
`error`/`empty` (didn't build), `incomplete`/`unsupported` (couldn't be proven),
`fail`/`pass` (intent). The independence result is the important one: **a tool that only
proves the model built and is watertight proves almost nothing about whether it is the
right part.** partspec's value is concentrated in stage 3, and stage 3 is precisely where
its vocabulary is thinnest — seven mostly-global scalars. This *raises* the priority of
epic #6, which currently sits below the agent-harness epics.

## 2. What the benchmarks actually check — and the one idea partspec is missing

**CADGenBench** (HuggingFace, huggingface/cadgenbench) scores with a hard validity gate
followed by a weighted mean of three orthogonal metrics:

| CADGenBench component | partspec equivalent |
|---|---|
| validity gate — BREP well-formed, meshes to a closed manifold; **failure zeroes the whole score** | `watertight`, and the `empty`/`incomplete` statuses ✅ |
| topology match via **Betti numbers b0, b1, b2** | `solid_count` (b0), `genus` (b1) ✅ — **b2 (enclosed voids) absent** ❌ |
| shape similarity — Surface Distance F1, Volume IoU | `volume`, `area`, `envelope` — weak global proxies ⚠️ |
| interface match — **authored keep-in / keep-out sub-volumes** | **nothing** ❌ |

Two concrete consequences:

**(a) b2 is the missing Betti number, and it is the same bug as issue #11.** A sealed
cavity is b0=1, b2=1; partspec's `solid_count` counts surface shells and returns 2. The
fix to #11 and a new `cavities(n)` check are the same piece of work — the shell/solid
distinction *is* the void count. Filing them separately would fix the number and throw
away the quantity.

**(b) keep-in / keep-out is the highest-value check partspec does not have.** It expresses
mechanical intent *without needing a reference model or a second body*: "this bore region
must contain no material", "material must be present across this mounting face". It
subsumes a large share of what `min_wall`, bolt-circle clearance and mounting-interface
checks are reaching for, it needs no assembly support (unlike POST-V0 §1's relational
checks, which take two bodies and are deferred whole), and it is implementable on **both**
tiers as a boolean intersection against an authored primitive — `manifold3d`/`trimesh` on
mesh, `BRepAlgoAPI_Common` on OCCT. POST-V0 does not contain this idea in any form.

**BenchCAD** (arXiv 2605.10865) adds a third failure mode worth naming:
- *Holistic spatial deficit*: Vision QA underperforms Code QA by 15–20pp on identical
  questions. **Models read the code better than they read a render of it.**
- *Industrial parametric abstraction gap*: models recognise the part family but not the
  standard-driven parameterisation (a DIN 2095 spring generated with uniform helix instead
  of the specified pitch variation).
- *CAD operational blindspot*: models default to sketch-and-extrude; recall of
  revolve/fillet/loft/sweep is **25–35%** untrained, ~84% fine-tuned.

## 3. Prior art that already exists — build123d-mcp

`pzfreo/build123d-mcp` is a shipped MCP server for build123d. On the CADGenBench
leaderboard (June 2026) it raised the same model's score **0.360 → 0.457 and CAD validity
88% → 100%**.

Its tools: persistent CAD session code execution · PNG/SVG/DXF preview · volume, area,
bbox, topology, centre of mass · **feature detection (holes, bosses, countersinks, hole
patterns)** · printability and fit/alignment validation · STEP/STL comparison · session
snapshots · 2D engineering drawings.

**This is the single most important external fact for the roadmap.** Read three ways:

1. **The MCP path is empirically validated.** D5's "MCP later, it's ~100 lines" defers the
   one thing with published evidence of moving the metric. Validity 88% → 100% is the
   *validity gate* — the cheapest, most mechanical part of the cascade — reached by giving
   the model a render-and-measure loop.
2. **partspec must not accidentally rebuild it, worse.** build123d-mcp is a *stateful,
   interactive authoring session*. partspec is a *stateless declarative contract checker*
   that emits a signed artifact and an exit code. Those are complementary: one helps the
   agent author, the other proves the result meets intent and gates CI. Nothing in the repo
   states this boundary, and epics #2 (renders) and #4 (MCP) drift straight toward the
   overlap.
3. **Feature detection is the tool partspec lacks and build123d-mcp has.** "Find the holes
   and their diameters" is what makes `hole_diameter` and bolt-circle checks writable at
   all — that is POST-V0 §4, currently coarse under epic #6.

## 4. Does shipping a "skill" actually help? — yes, but not as prose

Ablation evidence on in-context guidance for code generation against unfamiliar APIs:
- **few-shot examples: +21.5pp** (5-shot vs 0-shot, both with documentation)
- **documentation alone: +5pp** (with vs without, both 5-shot)
- removing code examples drops accuracy from **0.66–0.82 to 0.22–0.39** — examples are the
  critical component, not the prose.
- Grammar prompting (arXiv 2305.19234) finds DSL output spaces are not adequately captured
  by a handful of demonstrations — structure has to be given explicitly.

**Consequence for epic #3.** The ordering as filed is wrong. #25 (worked exemplars) is the
high-value item and #22/#23 (skill documents) are the +5pp supplement, yet #25 is filed
last and reads as optional. And BenchCAD's operational-blindspot result says what the skill
must *contain*: an operation-selection guide (when revolve/loft/sweep/fillet beats
primitive-boolean spam), not a style guide. That is also the direct cause of the owner's
"way too much LoC" complaint — models bolt primitives together because they do not recall
the right operation.

## 5. The circularity problem — nothing in the tracker addresses it

Every benchmark above keeps its ground truth **private**, on purpose: CADGenBench releases
inputs publicly and holds ground truth server-side precisely so the leaderboard cannot be
gamed. Reward-hacking work (ImpossibleBench; arXiv 2605.02964) measures how often agents
exploit a verifier rather than solve the task, and finds a phase transition in behaviour
between steps an agent *can* self-verify and steps checked against criteria it cannot see.

partspec's contract is written by whoever writes it. If an agent authors both `spec.py` and
the model, `p.volume(min=X*0.99, max=X*1.01)` with `X` derived from the model's own
constants is **vacuously true and passes green**. That is the project's own named failure
mode — vacuous green — arriving through the front door.

Issue #31 covers an agent *weakening* a contract mid-run. It does not cover a contract that
was circular when authored. The defence is external reference values: the dogfood
`bearing_608` is the model of the good pattern — `OD = 22.0` comes from ISO 15, not from
the `.scad`. **That reframes epic #5 (reference data) from a convenience into the
anti-circularity mechanism**, and it means "where did this number come from?" is
provenance the report should carry.

## 6. build123d-mcp, read closely — the competitive picture

Cloned to `notes/upstream/build123d-mcp` (v0.3.10, 20 MCP tools, 198 tests). Its
`default_prompt.md` is the shipped agent skill; `research.md` is an architecture write-up.
Read both before writing anything for epics #2, #3 or #4.

**What it has that partspec does not, and should absorb:**

- **`design_audit()`** — surfaces the program's named numeric parameters, nudges each ±10%,
  and re-runs the validity gate, flagging any parameter as `brittle` where a small change
  collapses the solid. The stated goal: *"you ship an editable design and not just a valid
  shape."* This is metamorphic testing for CAD and it is the strongest single idea in the
  repo. **It fits partspec better than it fits build123d-mcp**, because partspec already
  has a declared parameter set *and* a declared contract — it can re-run the whole contract
  at perturbed parameters and report "passes at `bore_d=8.0`, fails at `8.1`: this design
  is on a cliff edge." build123d-mcp can only re-run a validity gate.
- **Feature recognition** — `find_holes`, `find_bosses`, `find_hole_patterns`, with the
  note that on curved/BSpline faces you must use the returned bore axis because face and
  bbox centres are off-axis. This is the prerequisite for POST-V0 §4's `hole_diameter` and
  bolt-circle checks (epic #6), and it is a solved problem to borrow rather than derive.
- **`cross_sections()`** and `clip_plane` renders as the *recommended* way to inspect
  interiors — with the explicit warning to prefer them over renders on large models. See §7.
- **`compare(kind="fit")` → `touching` / `apart` / `interpenetrating`** — a three-valued
  fit status, not a boolean.
- **Two-tier validation** — `validate()` as a fast in-loop screen, `export()` as the
  stricter authoritative gate that "can still reject rare coincident-face or near-tangent
  cases that passed validation." partspec has one gate.
- **A real sandbox** — three layers (AST check before `exec`, restricted builtins,
  SIGALRM timeout) plus subprocess isolation, so the parent never loads OCCT and a worker
  crash cannot take down the server; per-operation timeouts (execute 30s, render 120s,
  export 60s, measure 10s). partspec's **OpenSCAD** tier is fine here — `engines/openscad.py`
  shells out with `subprocess.run(..., timeout=timeout_s)`. But the **Python tier and the
  contract itself** are not: `target.py:53` and `engines/pycad.py:99` both load user code
  with `importlib.util.spec_from_file_location` and execute it **in-process, unsandboxed,
  with no timeout**. A `spec.py` that loops forever hangs the run with no diagnostic; one
  that calls `sys.exit()` or mutates `sys.modules` corrupts it. For a tool whose intended
  caller is an autonomous agent building files it wrote itself, that asymmetry between the
  two tiers is worth a decision either way.

**What partspec has that build123d-mcp does not:** the OpenSCAD tier (b123d only); a
persisted schema'd report artifact; adjudication semantics where `unsupported` ≠ pass; exit
codes for CI; and the engine-version determinism finding (F13).

**The boundary that needs stating in the repo.** build123d-mcp is a *stateful interactive
authoring session* — execute, render, measure, snapshot, restore. partspec is a *stateless
declarative contract checker* that emits an artifact and an exit code. Its own prompt says
the two roles should not duplicate: *"let MCP own the geometry loop and the skill own
visual review and manufacturing handoff."* Epics #2 (renders) and #4 (MCP) as filed drift
straight into the authoring-loop niche, where partspec would be a worse build123d-mcp.
Nothing in the repo currently draws this line.

## 7. Renders may be the wrong instrument

Three independent signals point the same way, against epic #2 as scoped:

1. **BenchCAD**: Vision QA underperforms Code QA by **15–20pp on identical questions**.
   Models read the code better than they read a picture of it.
2. **build123d-mcp's own validation protocol** orders it *deterministic checks before
   visual*: measure after every execute, fit-compare after positioning, and **"only after
   (1) and (2) pass"** render. It explicitly says *"do not render after a simple boolean
   that `measure()` already confirmed."*
3. Its geometry-gotchas section steers interior inspection to `cross_sections()` over
   renders, and warns high-quality/clipped renders hit the operation timeout on large models.

This does not kill the epic — a render is still the only artifact that catches "it built
fine and is the wrong shape," and the CADGenBench interface report leans on overlay images
for human review. But it re-scopes it: renders as **evidence attached to a report** for a
human or a failure triage, not as the agent's primary perception channel. The primary
channel should be numeric — cross-sections, feature inventories, and the keep-out/keep-in
regions in §2.

## 8. Keep-in / keep-out, specified

From `notes/upstream/cadgenbench/docs/metrics/interface_match.md` — worth copying almost
verbatim, minus the ground-truth machinery partspec does not need (the author declares the
region in the part's own frame, so there is no pose search and no private GT):

- **KOR (keep-out region):** the candidate must be **empty** here. A bolt hole, a slot, a
  wrench clearance. Material here blocks the mating part.
- **KIR (keep-in region):** the candidate must be **solid** here. A locating boss, a pin, a
  bearing seat. Missing material leaves nothing to mate against.
- **The verification shell is the load-bearing detail.** Each region is scored *together
  with a thin shell of the opposite material around it*, "so both an oversize and an
  undersize feature lower the score, and a candidate cannot pass by leaving out the
  surrounding material." A naive `keep_out` — intersection volume == 0 — is satisfied by a
  part with the material deleted. That is vacuous green again, and the shell is the fix.
- Scoring uses a hard ramp: IoU ≥ 0.95 → 1, ≤ 0.80 → 0, linear between, "so a sloppy fit
  scores 0 instead of banking partial credit." partspec would use pass/fail rather than a
  score, but the same intolerance for partial credit applies.
- A group scores as its **worst** feature; the part as the **mean over groups**.

## Sources

- [Text2CAD-Bench](https://arxiv.org/html/2605.18430v1) · [MUSE](https://arxiv.org/html/2605.28579) · [BenchCAD](https://arxiv.org/html/2605.10865v1) · [CadBench](https://arxiv.org/html/2605.10873v1)
- [CADGenBench](https://github.com/huggingface/cadgenbench) · [leaderboard](https://huggingface.co/spaces/HuggingAI4Engineering/CADGenBench)
- [build123d-mcp](https://github.com/pzfreo/build123d-mcp) · [openscad-mcp](https://github.com/quellant/openscad-mcp) · [freecad-mcp](https://github.com/contextform/freecad-mcp)
- [Grammar Prompting for DSL generation](https://arxiv.org/pdf/2305.19234) · [Compositional API Recommendation](https://arxiv.org/html/2402.19431v1)
- [Reward Hacking Benchmark](https://arxiv.org/html/2605.02964v1) · [Self-Improving CAD Generation with FEA feedback](https://arxiv.org/pdf/2605.17448) · [Seek-CAD](https://arxiv.org/pdf/2505.17702)

---

## Applied — 2026-08-06

The audit in `notes/audit-synthesis.md` was executed against the tracker:

- **Labels** — `blocks-release` added to #11/#14/#15/#16 (E1), #27 (E4), #30 (E2, plus `enhancement`); `agent-harness` added to #20/#21 (E3). 21 issues now carry `blocks-release`.
- **New sub-epic #32** (H8) — the exit-code/error-path family cut out of #1, which would otherwise have carried ~19 unstructured children.
- **22 new issues #33–#54** across epics #1, #3, #4, #5, #6, #7 and #32.
- **Three false statements corrected in place** — #17's "already verified" headless render claim, #26's F10 attribution, #28's misattributed quote.
- **14 issues gained an "Audit revision — 2026-08-06" section** rather than a silent rewrite, so the correction is auditable.
- **Epics #5 and #6 are no longer childless**; #7 gained its three pre-tag schema slices.

Scripts: `notes/file_audit_issues.py`, `notes/revise_audit_issues.py` (both REST — the audit's
120 agents exhausted the GraphQL quota, and `gh issue create`/`list`/`edit` all route through it).
