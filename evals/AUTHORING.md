# Authoring — do the assets change agent output? (#53)

**Date:** 2026-08-08. **Harness:** `evals/run.py` in authoring mode — same vehicle as
the convergence eval (#30), extended with a guidance-present/absent arm rather than a
second harness. Agent `claude -p` with Read/Edit/Write/Glob/Grep only; the contract
and task are frozen and hash-checked. The control arm's prompt carries nothing beyond
`TASK.md` and the contract; the treatment arm additionally receives the repo's
`skills/` directory and one line telling the agent to read it. Evidence:
[`control-results.json`](authoring-20260808/control-results.json),
[`skills-results.json`](authoring-20260808/skills-results.json).

**Arms and a contamination the review caught.** The treatment bundles the skills
(#22/#23/#52); per-asset arms accrue on the same harness (`--arm`, which requires a
code-level arm definition, not just data). The scored tasks mirror the exemplar
*shapes*, and the `examples/` exemplars themselves were withheld to avoid answer
leakage — but the leakage arrived anyway, through the skill: **plate-bore's
dimensions coincide with the openscad skill's own rule-5 worked block, and the
treatment's plate-bore output is a line-for-line copy of it (15/15)**. That task
measures retrieval, not transfer, and is scored separately below. `motor-plate`
(a five-hole pattern appearing in no skill block) and `sealed-box` are genuine
transfer tasks. Future runs should re-dimension plate-bore.

## Result — 3 tasks × 2 trials × 2 arms, 12 trials

| metric | control | skills |
|---|---|---|
| converged (first write, no repair turn) | **6/6** | **6/6** |
| lint findings, all tasks † | 17 | 0 |
| lint findings, **transfer tasks only** (motor-plate, sealed-box) † | **6** | **0** |
| trials lint-clean † | 3/6 | 6/6 |
| model LoC, mean | 8.0 | 16.8 |

Per task (lint, control trials / skills trials): plate-bore 6+5 / 0+0 **[contaminated
— retrieval]**; sealed-box 0+6 / 0+0; motor-plate 0+0 / 0+0.

**† Every lint figure above is a TIER-1 count, and "lint-clean" meant `findings == 0`.**
The numbers are left exactly as they were taken; this note says what they were taken
under. The harness stamped these runs `20260808-133845` and `20260808-134127`, and
lint tier 2 — the rules over the engine's `.csg` export — was not committed until
`1ac5807`, 17:27 the same day. So no tier-2 rule ran, none could refuse, and these
counts cover tier 1 and nothing else. The harness also had no way to notice a refusal
even in principle: `counts.unsupported` is an additive key that did not exist in the
lint payload until #316 (`651ce7a`, 2026-08-22), and `run.py` read `counts.findings`
alone.

The harness now records `findings`, `unsupported` and a three-way `lint_outcome` —
`clean` only when both are zero, `incomplete` when any rule did not run, because a
`findings: 0` beside an `unsupported: 3` is not a clean file but a file three rules
never looked at (#317, and `docs/LINT.md`'s own doctrine). **A figure taken under that
definition is not comparable to one above**, and re-taking these costs real agent
calls — which is why they are annotated rather than restated.

## Findings

**A1 — pass rate does not separate the arms at this difficulty.** Every trial in both
arms produced a contract-green part on the first write, matching the convergence
eval's C2 (these single-feature tasks are easy for a frontier model). That the
contracts *can* fail — that green here is a floor held, not a formality — is
established by the convergence suite's seeded-defect cases, not by this run; a
pass-rate claim about the assets needs harder tasks (multi-feature,
tolerance-bearing, OCCT tier).

**A2 — on the transfer tasks, the assets moved source quality from mixed to uniformly
clean.** Control's sealed-box hardcoded in one of two trials (6 findings); both
treatment trials are clean, and motor-plate's treatment output applies the taught
form — named parameters, module-per-feature, `$fn` as a top-level parameter, the
−1/+2 overshoot — to dimensions no skill block contains
([control](authoring-20260808/exhibit-control-motor-plate.scad) vs
[skills](authoring-20260808/exhibit-skills-motor-plate.scad)). The plate-bore pair
([control](authoring-20260808/exhibit-control-plate-bore.scad) /
[skills](authoring-20260808/exhibit-skills-plate-bore.scad)) is kept as the
**contamination exhibit**: what a verbatim retrieval looks like, and why eval tasks
must not coincide with teaching blocks. All 17 control findings are
`scad-magic-number`.

**A3 — LoC is the wrong metric alone, and this run proves it on purpose.** The
treatment writes *more* lines (16.8 vs 8.0): parameter blocks and named modules —
exactly what the epic's LoC-bloat complaint is NOT about. Junk complexity and
load-bearing structure both add lines; only the lint findings tell them apart.
Recorded so nobody optimises this suite toward short and hardcoded.

**A4 — scope, stated in full.** One agent CLI (the payload records the command string,
not a model id — a gap shared with the convergence record, worth fixing in the
harness), N=12, one date, treatment = the bundled skills. The lint metric is the
treatment's own opinions operationalized — the linter codifies the skills' rules — so
A2 measures *conformance to the taught form*, which is what #53 asks ("does the
guidance change output"), not an independent notion of quality. The agent authoring
the parts is the same model family that wrote the skills and this harness; a
different-model arm is the strongest future extension.

## Acceptance (#53)

- Control arm needs no asset and landed with the harness — any repo state can re-run it.
- Treatment arm runs per asset: first arm (skills bundle) recorded; `--arm` is the
  accrual point.
- Reuses #30's vehicle: `run.py` gained `mode = "authoring"` and `--arm`, nothing else.
- Scoring is partspec's own contracts on exemplar-**shaped** tasks — a recorded
  deviation from the acceptance's literal "on the exemplars from #25", chosen to
  avoid handing the treatment the answers; the plate-bore coincidence shows the
  concern was real and the guard has to cover the skills' own blocks too.
