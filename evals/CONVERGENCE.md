# Convergence — the loop, proven (#30)

**Date:** 2026-08-07. **Harness:** `evals/run.py`, agent `claude -p` with Read/Edit/Write/
Glob/Grep only (no Bash), contract files frozen and SHA-256-checked every turn, no hints in
the prompt. Evidence: [`convergence-20260807/results.json`](convergence-20260807/results.json).

## Result

**15/15 trials converged — 5 defect classes x 3 trials, every one in exactly one repair
edit** (`turns_to_converge` counts edits: turn 1 shows the failing report, the agent edits,
turn 2 verifies green). Zero contract-weakening attempts (the digest check never fired),
zero escalations, zero thrashing.

| case | defect class | trials | edits to green |
|---|---|---|---|
| bore-breach | breached hole (F15) | 3/3 | 1, 1, 1 |
| standard-mismatch | wrong dimension vs standard (F16) | 3/3 | 1, 1, 1 |
| consumed-cut | boolean consumed the part | 3/3 | 1, 1, 1 |
| hole-count | missing feature (genus) | 3/3 | 1, 1, 1 |
| boolean-order | wrong operation order | 3/3 | 1, 1, 1 |

## Findings

**C1 — the report is sufficient signal.** The agent never saw the rendered part and never
ran a command; it repaired every class from the report's check ids, measured values and
details alone. This is the loop D5's architecture bet on, holding end to end.

**C2 — this is the fixed-defect regime, and the mean of 1.0 says the cases are now easy
for a frontier model.** The baseline run (2026-08-06, `BASELINE.md`) is where the spread
lived: pre-fix partspec let `consumed-cut` cost 2 turns plus an unrequested design change.
Post-fix, difficulty has collapsed — which is evidence about the *tool's* clarity, but it
means harder cases (multi-defect, parameter-phase refusals, OCCT tier) are what a stronger
claim needs. Tracked as the natural growth of this suite, not a gap in this gate.

**C3 — nothing failed, so nothing files.** The acceptance's "failures become issues" clause
is satisfied vacuously, and per this repo's own standard that vacuity is stated rather than
implied.
