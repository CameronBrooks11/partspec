# The agent contract — driving partspec in a repair loop

**Status:** v1 · 2026-08-08 · closes #28
**Audience:** an agent (or the harness around one) using `partspec` to take a part to
green, **via the CLI**.
**Scope:** how to act on partspec's output. How to *author* a contract is
`SPEC-contract.md`; what the artifact means is `SPEC-report.md`.

**The `partspec-mcp` tools cannot execute this document.** They run the same CLI per call,
but the four registered tools are `check` / `measure` / `render` / `vdiff`, and the check
tool builds only `["check", target, "--quiet"]` plus `--out` and `--render`. There is no
`--expect`, no `--pin`, no `--timeout`, and **no `diff` tool at all** — so §1 step 1's
claims pin and §4's `diff` remedy are both unreachable from MCP. An MCP-driven agent is
running a weaker loop than the one specified here, and should be told so rather than
assumed to be following it. (Tracked: the flags are plumbing, not design.)

The one rule everything below serves: **the report artifact is the ground truth, and
only `pass` is green.** Read `report.json`, not the console — the console is a courtesy
and MCP runs `--quiet`.

---

## 1. The loop

1. `partspec check <target>` — with `--expect <lock>` whenever a lockfile is committed
   beside the contract or named in the repo's CI invocation (conventionally
   `claims.lock`). A green obtained without the pin while a lock is committed is
   unverified: re-run with `--expect` before believing it, and a harness should treat
   the missing flag as reviewable.
2. Read `report.json`. Act per §2, editing **one thing per attempt**.
3. Re-run. **At most 5 attempts per part**, counting every run after the first.
4. On attempt 5 without green — or as soon as any §4 condition fires — escalate per §3.

**Feed the failure forward.** Each attempt's context must carry the previous failing
check's `id`, `measurement`, `limit`, and `detail`. Re-deriving the failure from scratch
is how a loop rediscovers the same dead end five times; the report already names the
axis and the bound that broke (`components`, `detail`), so the next edit can be aimed.

**Batch:** `check` takes several targets in one process. The exit is the
highest-**precedence** verdict across parts — `error > empty > fail > incomplete > pass`
(SPEC-report §6.2), so a batch containing a disproven part can still exit `3` if another
part asserts nothing. Route per-part from each part's own report, never from the process
exit; iterate on the one failing part singly and re-run the batch to confirm. The one
thing the reports do not carry is §2's exception: a render the run was asked for and did
not deliver is a fact about the RUN, so it reaches the exit and stderr — named with its
target — while that part's own report says whatever the part deserved, `pass` included.

## 2. What each outcome instructs

Every evaluated `check` run leaves a report at the deterministic path (a placeholder
saying the run died is written before anything happens, then overwritten by the real
report; a usage refusal — exit 64 — may leave the placeholder, or nothing when the
invocation's shape was refused outright). The exit code plus two fields — `verdict` and
`error` — decide the action, with **two** exceptions, both of which exit 4 while the
report says something else:

1. The uncovered-pin failure (§4) lives on stderr and in the exit alone, because no report
   path exists for a part no target produced.
2. A `check --render` whose render fails on an otherwise green part writes a normal report
   — `verdict: "pass"`, `error: null`, no `hint` — and still exits 4. The report speaks for
   the part; the exit speaks for the run, and the run did not produce what was asked of it.
   The diagnosis is on stderr, prefixed with the target when several were given, since one
   message and N parts otherwise names nothing.

In both, reading `error` and `hint` from the report yields nothing. Read stderr.

| exit | verdict | action |
|---|---|---|
| `0` | `pass` | Stop. Do not "improve" a passing part. First green on an unfamiliar file: apply §5 before believing it. |
| `1` | `fail` | Something asserted was disproven. Disambiguate by the failing check (§2.1), then edit the **model** — or, for a parameter-phase fail, the declared parameter *values*; never the claims (§4). |
| `2` | `incomplete` | Nothing disproven, not everything proven. **Do not edit geometry** — the part is not the problem. Disambiguate by `checks[].status` (§2.2). |
| `3` | `empty` | The contract asserts nothing — the single most likely output when you do not know what to assert. Run `measure`, decide which numbers are *intent*, declare them. Never celebrate exit 3. |
| `4` | `error` | Not a statement about the part (§2.3). Read `error` and `hint` — **except in the two cases above, where the report carries neither and stderr is the only diagnosis**; fix the machine or the contract, or escalate. Editing the model on exit 4 is noise. |
| `64` | — | Your invocation is malformed (unresolvable target, bad flag, missing/corrupt pin, colliding slugs). Fix the command, not the code. |
| `130` | — | The operator interrupted you. Stop entirely. |

### 2.1 exit 1 — which `fail`?

- **`id: "builds"` failed** → the source does not compile / the model raised
  (`build_origin: "model"`). Fix the source; `build_stderr` carries the engine's own
  diagnosis unabridged.
- **A check with `phase: "parameter"` failed** → the *declared inputs* are wrong, before
  any geometry existed: a `requires` expression came out false (`operands` shows the
  values it read) or a `param` left its range. Everything else reports `skipped` with a
  `detail` naming the blocker ("not evaluated: parameter check … failed") — fix that
  blocker first; nothing else was asked. The fix is the parameter values in the
  contract's source declaration (`openscad("m.scad", x=…)`), which is a value edit, not
  a claim edit — it changes no claim slug and does not trip the pin.
- **A geometry check failed** → the geometry is wrong. `measurement` vs `limit` says by
  how much; `components` names the failing axis; for `hole_diameter`/`bolt_circle` the
  `detail` carries the full bore inventory or the nearest circle found.

### 2.2 exit 2 — which `incomplete`?

Read the non-`pass` statuses in `checks[]`:

- **`unsupported`** → this engine tier cannot answer, and `requires` names the tier that
  would (`"occt"` → port the source to build123d/CadQuery, or accept the gap). **Never
  delete the unanswerable check to make the run conclusive** — that is §4.
- **`approximate`** → the guaranteed interval around the measurement straddles the limit:
  the tool does not know, and will not guess. **Live since `min_wall` shipped** (#140) and
  routine on the OCCT tier — a wall whose bound is `[1.0, 3.0]` against `min=2` is neither
  proven nor disproven. This paragraph told you the opposite until the v0.7.0 sweep, and an
  agent following it would have escalated correct output as a tool bug. Act on it: tighten
  the design away from the boundary, or measure the feature a different way, or accept the
  gap and say so. **Never shave the limit to swallow it** — that is §4.
- **`skipped` alone** cannot produce exit 2 in v0: every path that skips checks
  co-occurs with a `fail` (exit 1, §2.1's parameter branch) or an `error` (exit 4). A
  lone `skipped` under exit 2 would mean a referenced part is absent — an assemblies
  state with no v0 path — and is worth escalating as unexpected.

### 2.3 exit 4 — whose error?

- **`build_origin: "environment"`** → the machine, not the part: missing engine or
  package (named in `hint`), absent source file, or a blown build budget — `error` names
  the budget; a legitimately slow model gets `--timeout` raised *deliberately*.
- **`error` mentions the claims pin** → the contract does not match its committed lock.
  If you did not change the contract, someone else's change is unreviewed — escalate.
  If you did: §4.
- **Otherwise** → the contract itself raised (the report says "the contract is wrong,
  not the part"), or the report is still the placeholder ("run did not complete") —
  whose most common cause is deterministic, not transient: **the contract failed to
  resolve** (a typo'd keyword, an import error at contract scope), and here the
  diagnosis (the traceback) is on stderr only, like the uncovered-pin case — though
  here a placeholder exists where that one leaves no report at all. Re-run once; if the
  placeholder recurs, read the console before escalating — the fix is usually a
  one-line contract repair to propose.

## 3. Escalation

Emit exactly this line — it is the greppable surface a harness watches:

```
HUMAN_REVIEW: <why in one clause> — last failure: <check id>: <detail or error text>
```

Parse rule for harnesses: split on the **first** `" — last failure: "`; everything after
it is one opaque assertion string (check ids legitimately contain colons — `param:x`,
`iso15:608:seat` — so id and detail are not separately recoverable, by design).

Example:

```
HUMAN_REVIEW: bore must be Ø22 H7 but the seat prints at 22.31 after 5 attempts — last failure: iso15:608:seat: found 0 bore(s) with diameter in [21.99, 22.01] mm, expected 1
```

Escalate — immediately, without spending remaining attempts — when:

- green would require **weakening the contract** (§4);
- the same check has failed **identically twice** despite different edits;
- exit 4 persists after one environment fix attempt;
- the contract itself appears wrong (a limit contradicts the drawing, a `requires`
  expression is inverted): propose the contract change in the escalation, do not apply it.

## 4. Out of bounds — and the guards that are watching

**Never weaken the contract to reach green.** Deleting a check, loosening a limit,
swapping a strict check for a lax one, stripping a `source` citation, or dropping a
pinned part from the invocation — from where you sit these are indistinguishable from
"fixed it", which is exactly why they are forbidden and instrumented:

- the **claims pin** (`--expect claims.lock`) catches all of that, but its guards do not
  cost the same, and the difference is a build budget. A lock that is missing or the wrong
  schema is refused before any target runs (exit 64). A **claim mismatch** — the declared
  claims differ from the lock — is adjudicated from the resolved contract, so *that part*
  never builds and every removed/added/changed claim is named (exit 4, `expectation` block
  in the report): free in a single-target run, but a batch keeps going, so the other pinned
  targets still build. A **dropped part** — the lock covers a part no target in this
  invocation produced — is compared only after the target loop has finished, so today every
  surviving target **builds first** and the run fails after them: budget a full build per
  surviving part, tens of seconds each on the OCCT tier. That variant is also the one guard
  with **no report evidence**: the surviving parts' reports look normal (`verdict: "pass"`,
  no `error`), the confession is stderr + exit 4 alone — a harness must watch the exit, not
  only the artifacts;
- **re-pinning after weakening** (`--pin`) defeats nothing: the lock is committed, and
  its diff is the confession in your PR — treat running `--pin` as requiring the same
  human sign-off as the contract edit itself;
- `partspec diff old/report.json new/report.json` reports `removed` and `limit_changed`
  on comparison, including a stripped citation. The **first** comparison against a
  baseline recorded before v0.7.5 is a migration, not a finding about the part: a Python
  baseline is `indeterminate` at exit 2 because it carries no import map, and either tier
  reports the widened `environment.packages` as names recorded for the first time. Both
  name the same remedy — re-record the baseline (`indeterminate[].remedy`,
  `environment.packages.first_recorded`) — and it is one step, not a per-run condition to
  tolerate;
- the run-level `attribution` block discloses when every dimensional limit is
  unattributed — bounds derived from the model's own numbers prove the model matches
  itself; take limits from `partspec.refs` (`iso15`, `iso_metric_thread`,
  `nema17`) or the drawing.

A contract change can be *right* — the fix is to propose it in an escalation and let a
human apply and re-pin it, never to make it silently.

## 5. Before believing a green run

On the first `pass` for an unfamiliar part, confirm in `report.json`:

1. `counts.total` is plausible for the part's complexity — one `watertight` on a bracket
   with four bolt holes proves almost nothing (exit 3 catches *zero* checks; it cannot
   catch *too few*). With a pin in play the test is exact, not a judgment call:
   `counts.total == expectation.claims + 1` (the implicit `builds` check);
2. `attribution.dimensional > 0` with `attribution.attributed == 0` is the
   circular-contract signal — checkable from those two fields alone. Two honesty limits:
   `attributed` counts citations present, not pertinent; and arithmetic on a
   `Referenced` value deliberately sheds the citation (a derived number is the
   author's), so cite the un-derived bound, not an expression over it;
3. `part.source_closure.partial` — a partial closure means "nothing *we looked at*
   changed"; treat identity claims accordingly. `unseen` says *which* gaps, from a closed
   vocabulary, and `imports` says which distributions the model loaded and whether their
   bytes were read or their installer taken at its word (SPEC-report §8.3). An unrecognised
   `unseen` token is a gap, not noise; `imports` absent means the question was never asked.
   `imports` **over-reports in a multi-target run** — one interpreter, one `sys.modules` —
   and `preloaded` names the entries this part cannot be credited with. Such an entry may
   have been loaded by this part or by an earlier target — nothing in the report can say
   which — so treat its arrival between two runs as unresolved: not as a build input that
   appeared, and equally not as one that did not (§8.3 rule 7). In a diff this shows up as
   `source.closure: "changed"` with the name in `source.imports.unattributable`: the field
   says the two reports recorded different closures, never that the part's inputs moved,
   so read the two together and not `source.closure` alone.
   `diff` classifies those gaps rather than counting them: `native_reads` is irreducible on
   the Python tier and reaches no verdict — it is printed on every outcome as `not covered:`
   — while every other token, recognised or not, still blocks `identical` (SPEC-diff §2
   rule 3). Read the `not covered:` line; do not filter it out;
4. when a pin is in play, `expectation.matched` is `true` in this same report.

---

*Design basis: cad-khana's `SKILL.md` (bounded loop, greppable escalation, feed-forward,
vacuous-green warning), recorded in `POST-V0.md` §3. Acceptance per #28 with the
2026-08-06 audit revision: the action map keys on (exit, verdict, report fields), not on
the exit code alone.*
