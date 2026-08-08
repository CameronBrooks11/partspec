# Authoring — do the assets change agent output? (#53)

**Date:** 2026-08-08. **Harness:** `evals/run.py` in authoring mode — same vehicle as
the convergence eval (#30), extended with a guidance-present/absent arm rather than a
second harness. Agent `claude -p` with Read/Edit/Write/Glob/Grep only, contract and
task frozen and hash-checked, no hints beyond TASK.md and the contract. Evidence:
[`control-results.json`](authoring-20260808/control-results.json),
[`skills-results.json`](authoring-20260808/skills-results.json).

**Arms.** *control*: task + contract only. *skills*: the same, plus the repo's
`skills/` directory copied into the workspace with one line telling the agent to read
it. This first treatment arm bundles the skills (#22/#23/#52); per-asset arms
(exemplars alone, lint feedback in the loop) accrue on the same harness, per the
issue's own design. The scored tasks **mirror the exemplar shapes** (plate-with-bore,
sealed enclosure, motor plate) but are not the exemplars themselves — a treatment
containing worked solutions of the exact scored tasks would be answer leakage, not
guidance.

## Result — 3 tasks × 2 trials × 2 arms, 12 trials

| metric | control | skills |
|---|---|---|
| converged (first write, no repair turn) | **6/6** | **6/6** |
| lint findings, total | **17** | **0** |
| trials lint-clean | 3/6 | 6/6 |
| model LoC, mean | 8.0 | 16.8 |

## Findings

**A1 — pass rate does not separate the arms at this difficulty.** Every trial in both
arms produced a contract-green part on the first write. This matches the convergence
eval's C2: these single-feature tasks are easy for a frontier model, and a pass-rate
claim about the assets needs harder tasks (multi-feature, tolerance-bearing, OCCT
tier). What the contracts *did* do is hold the floor: every green is a real
envelope/topology proof, not a build-succeeded shrug.

**A2 — the assets moved source quality from mixed to uniformly clean.** Control trials
hardcoded half the time (17 magic-number/unused findings across 6 trials, three trials
clean, three not); every skills trial lints clean. The exhibit pair says it plainly:
[control](authoring-20260808/exhibit-control-plate-bore.scad) is four hardcoded lines;
[skills](authoring-20260808/exhibit-skills-plate-bore.scad) is the taught form —
named parameters, module-per-feature, `$fn` as a top-level parameter, the −1/+2
overshoot — reproduced without being shown the exemplar.

**A3 — LoC is the wrong metric alone, and this run proves it on purpose.** The skills
arm writes *more* lines (16.8 vs 8.0): the increase is parameter blocks and named
modules — exactly what the epic's LoC-bloat complaint is NOT about. Junk complexity
and load-bearing structure both add lines; only the lint findings tell them apart.
Recorded so nobody optimises this suite toward short and hardcoded.

**A4 — scope, stated.** One model, one date, N=12, treatment = the bundled skills.
This is an indicative first arm, not the ablation: the external evidence's prediction
(worked exemplars > prose) is untested here because the exemplars were deliberately
withheld from the treatment (see Arms). The harness records `arm` per trial so later
runs extend the same record.

## Acceptance (#53)

- Control arm needs no asset and landed with the harness — any repo state can re-run it.
- Treatment arm runs per asset: first arm (skills bundle) recorded; the `--arm`
  dimension is the accrual point.
- Reuses #30's vehicle: `run.py` gained `mode = "authoring"` and `--arm`, nothing else.
- Scoring is partspec's own contracts (envelope, watertightness, topology, cavities)
  on exemplar-shaped tasks, plus `partspec lint` as the source-quality metric.
