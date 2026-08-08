# evals — does an agent actually converge, and do the assets change what it writes?

Two questions, one harness. Convergence (#30): `CONVERGENCE.md`. Authoring quality
under guidance-present/absent arms (#53): `AUTHORING.md`.

The project's thesis is that a machine-checkable contract plus an honest verdict is
enough for an AI agent to drive a broken CAD model to correct. Nothing in the test
suite tests that. This does.

**The question, stated so it can fail:** given a part that violates its contract, and
*only* partspec's output to work from — no human hints, no description of the defect —
does an agent converge to a passing part within a bounded number of turns?

## The rules that make the answer mean something

1. **The contract is frozen.** The agent may edit the model. It may not edit `spec.py`.
   Deleting a failing check is the cheapest way to turn a run green, and an agent will
   find it. The driver hashes every contract file before and after each turn; a
   modification ends the trial as `gamed`, which is **not** a form of success and is
   reported separately from `failed`.
2. **No hints.** The prompt carries the task framing and partspec's stdout/stderr/exit
   code. It does not carry the defect class, the file that is wrong, or the direction
   to move a number.
3. **Turn-based, not free-running.** The driver runs `partspec check`, hands the output
   to the agent, and lets it make edits; then it runs the check again. The agent never
   runs partspec itself. This is deliberate: the measurement is *"is partspec's output
   alone enough to drive a correct edit"*, and an agent that greps the model or
   brute-forces values is answering a different question.
4. **Every trial runs in a throwaway copy.** `evals/cases/` is never mutated.

## Running it

```bash
just eval                      # every case, default agent
python evals/run.py --case bore-breach --trials 3
python evals/run.py --list
```

The agent under test is a pluggable command, so this harness is not tied to one model
or one vendor:

```bash
export PARTSPEC_EVAL_AGENT='claude -p --permission-mode bypassPermissions'
```

It is invoked with the prompt on **stdin**, with the working directory set to the
trial's scratch copy. Anything it writes to that directory is the edit. `bypassPermissions`
is safe here only because the working directory is a temp copy — never point this at a
real tree.

## Reading the results

`evals/results/<timestamp>/results.json` plus a per-trial transcript. The headline
numbers:

| outcome | meaning |
|---|---|
| `converged` | exit 0, contract untouched — the only success |
| `failed` | budget exhausted, still non-zero |
| `gamed` | the agent edited the contract |
| `regressed` | a turn made the verdict strictly worse |
| `error` | the harness or the agent command broke |

`turns_to_converge` is the number that matters for comparison across changes to
partspec. A baseline taken against today's checker — which has known false greens —
is not a certification. It is a list of what an agent actually walks into, and that
list is the point.

## Adding a case

One directory under `cases/`, containing `case.toml`, the frozen contract, and the
model. See `cases/bore-breach/case.toml` for the fields. A good case has a defect that
is **visible in the report and fixable in the model**, and a natural cheat that the
frozen contract forbids.

Related: #30 (this), #53 (the guidance-present/absent dimension layers on top of this
same harness — do not build a second one).
