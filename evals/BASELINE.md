# T0 baseline — 2026-08-06

First run of `evals/run.py` against the checker as it stands today, before any of the
correctness work in epic #1. Five seeded defects, one trial each, contract frozen, no
hints.

**Agent:** `claude -p --permission-mode bypassPermissions --allowedTools Read,Edit,Write,Glob,Grep`
(no Bash, so the agent cannot run partspec itself)
**Engine:** OpenSCAD 2026.08.01
**Raw:** `baseline-20260806/`

## Result

| case | outcome | turns | what the agent did |
|---|---|---|---|
| bore-breach | converged | 1 | `bore_d` 34 → 20, with a comment naming the constraint |
| standard-mismatch | converged | 1 | hoisted a named `grid_pitch = 42` and built both extents from it |
| hole-count | converged | 1 | added the missing fourth hole |
| boolean-order | converged | 1 | swapped the `difference()` operands **and** restored the right dimensions |
| consumed-cut | converged | 2 | `core` 30 → 10 — then **drilled a vent hole the design never asked for** |

**5/5 converged, mean 1.2 turns.**

## What this does and does not show

It shows the loop works. Given only an exit code and a list of check statuses, a current
model made a correct, minimal, well-commented edit on four of five cases at the first
attempt — including `boolean-order`, where nothing in the output says "your operands are
backwards" and the agent had to infer it from an envelope and a volume. The core thesis —
*a machine-checkable contract plus an honest verdict is enough to drive repair* — survives
its first contact with evidence.

It does not show that partspec is ready. The fifth case is the finding.

## The finding: #11 makes an agent damage the design

`consumed-cut`'s contract asks for a 20 mm block with a concentric 10 mm cubic core. The
volume figure pins the core at exactly 10 mm and nothing else does; the agent derived that
correctly on turn 1.

That part — a sealed internal cavity — **fails**:

```
$ partspec check spec.py:cored_block     # core = 10, no vent
  ok   builds
  ok   envelope
  ok   volume
  ok   watertight
  FAIL solid_count
```

A block with a sealed void is *one solid*. `solid_count` counts surface shells, so it
returns 2. This is issue #11, and it is not reachable by fixing the model, because the
model was already right.

So the agent did the only thing left: it added a 3 mm vent bore from the cavity out through
the top face, and reasoned in a comment that the ~35 mm³ cost stays inside the contract's 1%
volume band. It turned a sealed enclosure into a vented one — a different part, with
different function — to satisfy a checker that was wrong.

**This is the failure mode the project exists to prevent, running in the opposite
direction.** The tracker frames #11 as a wrong number. Measured under an agent loop it is
worse than that: a false *negative* the agent cannot argue with, so it deforms the design
until the tool stops complaining. A false green misleads a human who may later notice. This
silently produces the wrong part and reports success.

### Fixed, and re-measured

`solid_count` now counts closed, outward-oriented components, so a sealed void is a
cavity rather than a second solid, and `cavities()` gives a contract the words to say so.
Re-running the same case against the fixed checker:

| | turns | model the agent left |
|---|---|---|
| before | 2 | `core = 10` **plus a 3 mm vent bore** |
| after | 1 | `core = 10` |

The full cycle — baseline finds a defect, fix lands, baseline confirms the agent's
behaviour changed — is the thing this harness exists to do.

## What it changes

1. **#11 moves up.** It is not a "wrong but loud" second-tranche item; it is the only
   defect measured to corrupt a design, and it belongs in the first tranche with the
   silent-green set.
2. **The cavity count (#11's `b2` follow-up) is load-bearing, not a nicety.** Had
   `cavities(1)` existed, the contract could have said what it meant and the agent would
   have had a correct part to converge on.
3. **Severity intuition was wrong, and cheaply so.** The bug I ranked first for this
   tranche (#9, silent `-D` drop) never fired in five cases. The one that bit was ranked
   second-tier. This is exactly why the baseline runs before the fixes.

## Known limits of this baseline

- **n=1 per case.** Enough to find a reproducible defect, not enough for a rate. Re-run
  with `--trials 5` before quoting any convergence percentage.
- **One agent, one model.** No claim about agents in general.
- **No parameter-phase case.** `requires()` reads contract-declared parameters, and the
  contract is frozen, so a parameter-phase defect is unfixable by construction under these
  rules. Covering it needs a case whose model owns its own defaults.
- **Turn-based, so no credit for self-correction.** An agent that would have caught its own
  error by re-running the check is scored as needing another turn.
- **The checker under test has known false greens.** A case whose defect happens to sit
  behind one of them would read as converged. None of these five do, but that is an
  argument for re-running this after epic #1, not for trusting the number now.
