# SPEC — `partspec diff`

**Status:** draft 2 · 2026-08-09 · `kind` and `expr` join the claim fields; the digests
are stated as recorded-not-outcome-bearing
**Scope:** the semantic comparison of two reports of one part, its artifact, and its exit
codes. Written before the implementation, like the other specs.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** `SPEC-report.md` §7.1 (the silent-weakening gap), §7.2 (measurements on pass),
§8.3 (partial closures); `POST-V0.md` §2; D5 (the report is the product surface).

---

## 1. What it is for

`SPEC-report.md` §7.1 names the one gap v0 shipped with: an agent that deletes a check
produces a report that is internally consistent and green. `counts.total` and
`contract_digest` were designed to make that **detectable on comparison** — this verb is the
comparison. Its second job is the §7.2 payoff: **drift the boolean cannot see.** A wall
thinning from 2.9 mm to 2.1 mm against a 2.0 minimum is two passing reports and one
important trend, recorded in `measurement` since v0 and consumed by nothing until now.

```
partspec diff <old-report.json> <new-report.json>
```

The artifact is written to **stdout** (it is the product; it pipes); a one-line courtesy
summary goes to stderr. `diff` takes no out-directory because it owns no run.

## 2. Outcomes and exit codes

Silence must never read as "no difference". "No differences found" is a **positive claim**
that requires comparable, fully-identified inputs — not a fallthrough.

| exit | `outcome` | meaning |
|---|---|---|
| `0` | `identical` | compared conclusively; no semantic difference |
| `1` | `different` | compared; at least one semantic difference found |
| `2` | `indeterminate` | the comparison could not be made conclusively |
| `64` | — | unusable input: unreadable file, unknown `schema_version` (§7.1 requires rejection, not best-effort parsing), a report violating its own `counts.total` invariant, a report carrying two checks under one `id` (SPEC-report.md §7.1 makes uniqueness a MUST NOT, and the comparison joins on it), or otherwise malformed, or two reports that do not describe the same part. A forgotten argument is also `64` — argparse's default usage exit is `2`, which would read as `indeterminate` |

Rules:

1. Two reports with different `part.id` MUST be refused with exit `64`: `diff` compares two
   runs of one part, and comparing strangers is a usage error, not a finding.
1a. **Check ids MUST be unique within each input**, refused with exit `64` (#148). The
   comparator joins on `id`, so a report carrying two checks under one id does not merely
   lose a check — the second silently replaces the first and two unrelated claims are
   compared as one. Measured before the guard existed: a `genus` check aliased onto a
   `param_range` check reported `limit_changed` from `{"kind": "param_range"}` to
   `{"kind": "genus"}` at exit `1`, with the displaced claim absent from the output
   entirely. `counts.total` does not catch it — such a report carries exactly the number
   of checks it claims. `Part._add` refuses an id clash at authoring time, so `partspec`
   cannot emit one; this rule binds `diff` because the report schema is the product
   surface (D5) and the comparator must not assume it produced its own input.
2. A report whose `verdict` is `"error"` compares nothing — its checks are all `skipped` and
   its run did not complete. Either input erroring MUST make the outcome `indeterminate`.
3. **The partial-closure rule** (§8.3): when no differences are found but the inputs' source
   identity rests on a closure marked `partial` — or absent from either input, which is the
   ordinary v0.1.0 upgrade path for Python-engine reports — matching digests mean "nothing
   we looked at changed", not "nothing changed". The outcome MUST be `indeterminate`, with the reason
   stated — claiming `identical` there is the silence-as-success mistake at the provenance
   layer. Found differences are real regardless of closure partiality, so this rule only
   ever blocks the `identical` claim, never the `different` one.

## 3. What is compared

Checks join on `id` (`SPEC-report.md` §7.1 fixes `id` as the join key). Per check:

- **`removed` / `added`** — present in only one report. A removed check is the
  silent-weakening signal and is always a difference, whatever the statuses were.
- **`regressed` / `fixed`** — status changed, ordered by the severity that `verdict_of`
  already uses (`fail` > `unsupported` > `approximate` > `skipped` > `pass`). Any status
  change is a difference. A status-change entry MUST also carry the claim and value deltas
  when those moved: loosening a limit until a failing check passes is the flagship
  weakening move, and an entry saying only "fixed" would report the attack as an
  improvement.
- **`drifted`** — status unchanged, but a recorded value moved beyond tolerance:
  `measurement.value` (per component for vectors), or `operands` for a `requires` check
  (`SPEC-contract.md` §5 records them for exactly this).
- **`limit_changed`** — status unchanged but the *claim* moved: `kind`, `expr`, `limit`,
  `region`, `hole`, `source` or `direction` differ. (The name is historical — it covers every field
  that makes a check the claim it is, which the code names `diff.CLAIM_FIELDS` and a test
  holds in step with this list.) `source` is the quiet half of the weakening move: same
  number, citation stripped, authority now the author's say-so. `kind` and `expr` are the loud half
  and were both missing until the v0.7.0 sweep — swapping `genus` for `cavities` under one
  id turns "no through-holes" into "one sealed void", and loosening `wall >= 2.0` to
  `wall >= 0.2` rewrites a predicate outright; each read as `identical`, exit 0. Every
  other key a check can carry is listed in `diff.NON_CLAIM_FIELDS` with the reason it is
  not a claim, and a test requires every emitted field to appear in one list or the other.
  This is a contract edit visible between runs — the raw material of weakening
  detection (#31 owns adjudicating *within* a run; `diff` only reports the change, both
  sides shown, and takes no view on direction).

**Tolerance.** Numeric comparison uses the same `epsilon(reference)` as adjudication
(`SPEC-report.md` §3.3), with the old value as reference: rebuilding identical geometry
through a different transform order perturbs coordinates at ~1e-13, and exact float
equality would bury signal under noise. Non-numeric values compare exactly.

Also compared, at the top level, and **outcome-bearing**: `verdict` and `counts.total` (a
shrink is named, not implied).

**Recorded but never outcome-bearing**: `contract_digest`, `source_digest`, and the closure
digest. All three appear in the artifact as `digest_changed` / `closure` so a reader can
see the inputs moved, and none of them can make an outcome `different` on its own. The
contract digest is module-scoped and over-fires deliberately (`SPEC-report.md` §7.1) — an
unrelated docstring edit moves it — and a comment added to a `.scad` is not a semantic
difference of the part. A verb that reported `different` on either would be piped through
`|| true` inside a week, and what this comparison actually covers *is* the contract's
observable content: every check id, every field in `CLAIM_FIELDS`, every status and every
measurement. The closure digest is the exception that proves the rule: it cannot make an
outcome `different`, but under §2 rule 3 an absent or partial closure does block
`identical`, because there the question is whether the inputs were fully identified at all.

Alongside them, the environment facts that *explain* differences without being differences
of the part — `tool_version`, `engine.version`, `engine.render_backend` — reported only
when they changed (`SPEC-report.md` §8's principle: a dependency upgrade moving a number is
a different explanation than the design changing).

## 4. The artifact

```jsonc
{
  "schema_version": 1,              // this artifact's own version, not the report's
  "tool": { "name": "partspec-diff", "version": "0.2.0" },
  "part": "example-spacer",
  "outcome": "different",           // identical | different | indeterminate
  "indeterminate": [],              // {code, reason} entries when indeterminate; codes are
                                    // machine-readable: "input_error" | "partial_closure",
                                    // so CI can tolerate the honest Python-tier case
                                    // narrowly instead of tolerating exit 2 wholesale
  "verdict": { "old": "pass", "new": "fail" },
  "counts_total": { "old": 8, "new": 7 },
  "contract": {
    "digest_changed": true,
    "removed": ["wall_gt_2"],       // the headline finding, by id
    "added": []
  },
  "source": { "digest_changed": false, "closure": "same" },  // same | changed | inconclusive | null
  "checks": [                        // one entry per difference; empty when identical
    {
      "id": "envelope", "kind": "envelope", "change": "drifted",
      "status": "pass",
      "value": { "old": [15.8, 15.8, 8.0], "new": [15.8, 15.8, 9.6] }
    },
    {
      "id": "genus", "kind": "genus", "change": "regressed",
      "status": { "old": "pass", "new": "fail" }
    }
  ],
  "environment": { "engine_version": { "old": "2021.01", "new": "2026.08.01" } }
}
```

Field rules follow `SPEC-report.md` §7.1: additive fields are non-breaking; consumers MUST
ignore unknown fields and reject an unknown `schema_version`. `checks` lists differences
only — an entry per unchanged check would bury the finding in ceremony; `counts_total`
carries the reconciliation.

## 5. Non-goals

- **No weakening adjudication.** `limit_changed` shows both sides and stops. Deciding that
  a change *weakened* a contract needs a direction model and is #31's, not this verb's.
- **No visual diff.** Renders are evidence attached to a report (#21 consumes them).
- **No multi-report timelines.** Two inputs, one comparison. A trend over N runs is a
  consumer loop over N−1 diffs.

---

## Appendix: the visual diff (`partspec vdiff`, #21)

`vdiff` is the pair of this document's diff: that one says what changed in the claims,
this one what changed in the part's appearance. It consumes two on-disk render artifacts
(`render.json` from the `render` verb, or a report carrying `renders`) and emits its own
document (`vdiff_schema_version: 1`) with the same outcome vocabulary — `identical`
(exit 0) / `different` (exit 1) / `indeterminate` (exit 2).

Keys: `inputs` (file, part id and engine block per side), `views` (per view:
`pixels_changed`, `fraction`, `image` — the diff image, the new run faded to grey with
changed pixels in magenta), `bbox_delta_mm`, `magnitude`, and on refusal `refused
{reason[, hint]}`.

Rules, all MUST:

- **No silent rescaling.** Differing image sizes are refused.
- **No cross-version scoring.** A pair rendered by different engine kinds or versions is
  refused: 7.68% of pixels differ across OpenSCAD versions for identical geometry (the
  recorded audit measurement), and scoring renderer noise as change is the tool lying.
- **No cross-part pairing.** Different part ids, and differing view sets, are refused.
- **Scale cannot hide.** The framing scales with the part, so a uniform size change is
  pixel-invisible; `render_bbox` is compared alongside, and a bbox delta with identical
  pixels is `different` with a `note` referring the numbers to `measure`.
- **The scalar is reproducible.** `magnitude = max(worst view fraction,
  bbox_delta_mm / old bbox diagonal)` — 0.0 exactly when nothing changed.
