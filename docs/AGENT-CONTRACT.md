# The agent contract — driving partspec in a repair loop

**Status:** v1 · 2026-08-08 · closes #28
**Audience:** an agent (or the harness around one) using `partspec` to take a part to
green — via the CLI or the `partspec-mcp` tools, which run the same CLI per call.
**Scope:** how to act on partspec's output. How to *author* a contract is
`SPEC-contract.md`; what the artifact means is `SPEC-report.md`.

The one rule everything below serves: **the report artifact is the ground truth, and
only `pass` is green.** Read `report.json`, not the console — the console is a courtesy
and MCP runs `--quiet`.

---

## 1. The loop

1. `partspec check <target>` (add `--expect claims.lock` whenever a pin is committed —
   its absence from your invocation is itself a finding for review).
2. Read `report.json`. Act per §2, editing **one thing per attempt**.
3. Re-run. **At most 5 attempts per part**, counting every run after the first.
4. On attempt 5 without green — or as soon as any §4 condition fires — escalate per §3.

**Feed the failure forward.** Each attempt's context must carry the previous failing
check's `id`, `measurement`, `limit`, and `detail`. Re-deriving the failure from scratch
is how a loop rediscovers the same dead end five times; the report already names the
axis and the bound that broke (`components`, `detail`), so the next edit can be aimed.

**Batch:** `check` takes several targets in one process (exit = worst outcome across
parts). Iterate on the one failing part singly; re-run the batch to confirm.

## 2. What each outcome instructs

Every `check` run leaves a report at the deterministic path (a placeholder saying the
run died is written before anything happens, then overwritten by the real report). So
the exit code plus two fields — `verdict` and `error` — decide the action:

| exit | verdict | action |
|---|---|---|
| `0` | `pass` | Stop. Do not "improve" a passing part. First green on an unfamiliar file: apply §5 before believing it. |
| `1` | `fail` | Something asserted was disproven. Disambiguate by the failing check's `id` (§2.1), then edit the **model** — never the contract (§4). |
| `2` | `incomplete` | Nothing disproven, not everything proven. **Do not edit geometry** — the part is not the problem. Disambiguate by `checks[].status` (§2.2). |
| `3` | `empty` | The contract asserts nothing — the single most likely output when you do not know what to assert. Run `measure`, decide which numbers are *intent*, declare them. Never celebrate exit 3. |
| `4` | `error` | Not a statement about the part (§2.3). Read `error` and `hint`; fix the machine or the contract, or escalate. Editing the model on exit 4 is noise. |
| `64` | — | Your invocation is malformed (unresolvable target, bad flag, missing/corrupt pin, colliding slugs). Fix the command, not the code. |
| `130` | — | The operator interrupted you. Stop entirely. |

### 2.1 exit 1 — which `fail`?

- **`id: "builds"` failed** → the source does not compile / the model raised
  (`build_origin: "model"`). Fix the source; `build_stderr` carries the engine's own
  diagnosis unabridged.
- **A declared check failed** → the geometry is wrong. `measurement` vs `limit` says by
  how much; `components` names the failing axis; for `hole_diameter`/`bolt_circle` the
  `detail` carries the full bore inventory or the nearest circle found.

### 2.2 exit 2 — which `incomplete`?

Read the non-`pass` statuses in `checks[]`:

- **`skipped`** → a parameter check failed or an earlier blocker stopped evaluation; the
  `detail` names it ("not evaluated: …"). Fix that blocker first — everything else was
  never asked.
- **`unsupported`** → this engine tier cannot answer, and `requires` names the tier that
  would (`"occt"` → port the source to build123d/CadQuery, or accept the gap). **Never
  delete the unanswerable check to make the run conclusive** — that is §4.
- **`approximate`** → the measurement's error interval straddles the limit. Tighten the
  design away from the boundary, or escalate; do not shave the limit to swallow it.

### 2.3 exit 4 — whose error?

- **`build_origin: "environment"`** → the machine, not the part: missing engine or
  package (named in `hint`), absent source file, or a blown build budget — `error` names
  the budget; a legitimately slow model gets `--timeout` raised *deliberately*.
- **`error` mentions the claims pin** → the contract does not match its committed lock.
  If you did not change the contract, someone else's change is unreviewed — escalate.
  If you did: §4.
- **Otherwise** → the contract itself raised (the report says "the contract is wrong,
  not the part"), or the placeholder's own text ("run did not complete") means the
  process died before writing a result — re-run once; if it recurs, escalate.

## 3. Escalation

Emit exactly this line — it is the greppable surface a harness watches:

```
HUMAN_REVIEW: <why in one clause> — last failure: <check id>: <detail or error text>
```

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

- the **claims pin** (`--expect claims.lock`) fails the run before the engine starts,
  naming every removed/added/changed claim (exit 4, `expectation` block in the report);
- **re-pinning after weakening** (`--pin`) defeats nothing: the lock is committed, and
  its diff is the confession in your PR — treat running `--pin` as requiring the same
  human sign-off as the contract edit itself;
- `partspec diff old/report.json new/report.json` reports `removed` and `limit_changed`
  on comparison, including a stripped citation;
- the run-level `attribution` block discloses when every dimensional limit is
  unattributed — bounds derived from the model's own numbers prove the model matches
  itself; take limits from `partspec.refs` (`iso15`, `nema17`) or the drawing.

A contract change can be *right* — the fix is to propose it in an escalation and let a
human apply and re-pin it, never to make it silently.

## 5. Before believing a green run

On the first `pass` for an unfamiliar part, confirm in `report.json`:

1. `counts.total` is plausible for the part's complexity — one `watertight` on a bracket
   with four bolt holes proves almost nothing (exit 3 catches *zero* checks; it cannot
   catch *too few*);
2. `attribution.attributed > 0` if any dimensional claim exists — see §4;
3. `part.source_closure.partial` — a partial closure means "nothing *we looked at*
   changed"; treat identity claims accordingly;
4. when a pin is in play, `expectation.matched` is `true` in this same report.

---

*Design basis: cad-khana's `SKILL.md` (bounded loop, greppable escalation, feed-forward,
vacuous-green warning), recorded in `POST-V0.md` §3. Acceptance per #28 with the
2026-08-06 audit revision: the action map keys on (exit, verdict, report fields), not on
the exit code alone.*
