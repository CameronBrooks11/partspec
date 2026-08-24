# SPEC — `partspec diff`

**Status:** draft 5 · 2026-08-23 · §2 states that being parseable is not being a report,
two `measure` payloads of a changed part having compared `identical` at exit `0` (#292);
draft 4 bound the §1 headline to the claim delta a status-change entry already carried,
the console having reported a loosened limit as `1 fixed` (#293); draft 3 keyed §2 rule 3 on the class of a **named** gap rather than on
the `partial` boolean and compared the closure's `imports` map (#190); draft 2 put `kind`
and `expr` in the claim fields and stated the digests as recorded-not-outcome-bearing
**Scope:** the semantic comparison of two reports of one part, its artifact, and its exit
codes. Written before the implementation, like the other specs.
**Normative:** MUST / SHOULD / MAY per RFC 2119.
**Backing:** `SPEC-report.md` §7.1 (the silent-weakening gap), §7.2 (measurements on pass),
§8.3 (closures, their `imports` and their named gaps); `POST-V0.md` §2; D5 (the report is the product surface).

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

The summary's **finding** stays one line. Where a group of `environment.packages` or
`source.imports` differences could run to dozens of entries, it names at most two per group
and counts the remainder (`+7 more`); the artifact on stdout carries the complete lists. It
names them on **every** outcome, `identical` included, because a build input that moved
under an unchanged part is exactly the case an unqualified "no semantic differences" would
misreport as nothing having happened. A distribution the `inputs` clause reports as
**moved** is not reported as moved again by the `packages` clause — every imported
distribution is also an installed one, so a library bump would otherwise be named twice on
one line — and that is the only suppression: matching names across *different* groups drops
real facts, since an import that appeared while its installed version moved is two
findings, not one.

Below that line, and on every outcome, the summary states the **coverage** the finding
rests on: what was covered, and every gap §2 rule 3 named that the headline has not already
stated. The irreducible ones are what replaces the exit code such a gap used to produce, so
they are not suppressible; the bounded ones appear here on the `different` path, where the
headline says nothing about them and "1 regressed" alone invites the reading that the named
regression is the whole story.

## 2. Outcomes and exit codes

Silence must never read as "no difference". "No differences found" is a **positive claim**
that requires comparable, fully-identified inputs — not a fallthrough.

| exit | `outcome` | meaning |
|---|---|---|
| `0` | `identical` | compared conclusively; no semantic difference |
| `1` | `different` | compared; at least one semantic difference found |
| `2` | `indeterminate` | the comparison could not be made conclusively |
| `64` | — | unusable input: unreadable file, unknown `schema_version` (§7.1 requires rejection, not best-effort parsing), a report violating its own `counts.total` invariant, a report carrying two checks under one `id` (SPEC-report.md §7.1 makes uniqueness a MUST NOT, and the comparison joins on it), a payload that is not a report at all — one carrying no `verdict` and no `counts`, since `measure` and `render` share this document's `schema_version` and identity prefix by design (SPEC-report.md's Scope names them) and so parse cleanly while declaring nothing for a comparison to be about — or otherwise malformed, or two reports that do not describe the same part. A forgotten argument is also `64` — argparse's default usage exit is `2`, which would read as `indeterminate` |

Rules:

1. Two reports with different `part.id` MUST be refused with exit `64`: `diff` compares two
   runs of one part, and comparing strangers is a usage error, not a finding.
2. A report whose `verdict` is `"error"` compares nothing — its checks are all `skipped` and
   its run did not complete. Either input erroring MUST make the outcome `indeterminate`.
3. **The gap-class rule** (`SPEC-report.md` §8.3). The comparison covers the closure
   `digest` **and** the `imports` map, entry by entry, and every gap the two closures name
   in `unseen` is classified:

   - `native_reads` is **irreducible** — a property of the tier, present in every Python
     report that will ever be written.
   - every other token is **bounded**, **including one this reader does not recognise**.
     Failing closed is a MUST there (§8.3): a closed vocabulary must be safe to extend.

   Then: a **bounded** gap on either side, or a closure absent from either input, MUST make
   the outcome `indeterminate` when no differences were found — matching digests there mean
   "nothing we looked at changed", not "nothing changed", and claiming `identical` is the
   silence-as-success mistake at the provenance layer. Otherwise any difference in the
   digest or the `imports` map is `closure: "changed"` and none is `"same"`.

   An **irreducible** gap MUST NOT make the outcome `indeterminate`, and MUST be printed on
   every outcome, in every mode. Through v0.7.4 the rule keyed on the `partial` boolean,
   which the Python tier sets unconditionally, so `diff` was permanently indeterminate for
   every contract wrapping an installed library: fleet-01 measured 3/3 CadQuery replicates
   indeterminate against 0/3 OpenSCAD ones on the same command and version, the only
   variable being that OpenSCAD libraries are source on disk and Python ones are installed
   distributions (#190). A signal constant across every possible input cannot discriminate
   between two of them, and all three CadQuery agents wrote shell to suppress the exit 2
   rather than go and look — a universally suppressed verdict protects less than a
   universally printed caveat. The caveat is therefore permanent output, not an option.

   **An import either side could not attribute to its own target MUST NOT be reported as
   one that appeared or disappeared.** `SPEC-report.md` §8.3 rule 7: `imports` is read
   from one `sys.modules` shared by every target of a batch, and `preloaded` names what
   that costs. An entry of `added` or `removed` that either side listed there is reported
   as **unattributable** — named on the summary line, counted apart in `covered`, and
   listed in `source.imports.unattributable`. The wording elsewhere is untouched: an
   appearance the `preloaded` sets do not explain is exactly what this verb has always
   said it was.

   **Except where a side proved it reached the entry itself.** `reached` (§8.3 rule 7)
   names what a target's own module graph provably reaches, and a distribution it names is
   that target's build input whoever imported it first — so such an entry is attributable
   and is NOT listed as unattributable. This subtracts from the unattributable set and
   never adds to it: `reached` proves reach and cannot disprove it, so an entry absent from
   it is governed exactly as before. A producer that omits `reached` — every report before
   the field existed, and every OpenSCAD one — is read as proving nothing, which reproduces
   what this verb already did.

   **It still makes the closure `changed`, and `source.closure` MUST NOT be read as a
   claim about the part's inputs.** That field says whether the two reports *recorded*
   different closures, and two `imports` maps that differ differ — the batch case,
   44 entries against 38 with nothing in the model moved, is `changed` on those grounds.
   Whose import it was is the separate question `unattributable` answers, and a reader
   keying on `source.closure` alone MUST consult it. Suppressing the entry here made the
   artifact assert `closure: "same"` while carrying the difference in `imports.added` in
   the same object; keeping what the comparison saw is the same rule that gave
   `closure_digest_changed` its own field. It costs no verdict: `different` is computed
   from the checks alone and only `inconclusive` is outcome-bearing, so a `changed`
   closure falls through to `identical` at exit `0`. This qualifies the
   *claim*, not the verdict: it moves no outcome and no exit code, and it is deliberately
   NOT a gap token, because a bounded gap here would make every multi-target Python
   comparison indeterminate and rebuild what rule 3 exists to remove. Measured before the
   qualification: one build123d cube diffed against itself, run behind a CadQuery target
   in a batch, reported `inputs appeared: cadquery 2.8.0, casadi 3.7.2, +4 more` at exit
   `0` — six build inputs positively claimed to have arrived, and nothing had.

   **The message MUST state the inability and MUST NOT state a cause.** `preloaded`
   evidences that this comparison cannot attribute the entry; it evidences nothing about
   why the entry is on one side, and "the difference is its position in a batch" is the
   same overclaim aimed the other way. Measured: a follower whose model began importing a
   shared module its leader's contract also imports — batch position 2 of 2 in **both**
   runs — is a genuine new build input that lands in this set, and calling it a batch
   artefact reports a real change as a non-event. `SPEC-report.md` §8.3 rule 7 already
   words it correctly: *the honest reading is that this comparison cannot attribute it.*

   Only `added` and `removed` can be affected; a `changed` entry is present on both sides
   with something moved between them, which is a fact about the distribution whoever
   loaded it.

   Found differences are real regardless of any gap, so this rule only ever blocks the
   `identical` claim, never the `different` one. A `changed` closure is likewise never a
   difference on its own (§3): the library moved and no declared claim moved with it is
   `identical` at exit `0`, with the moved distribution named on the summary line, which is
   what OpenSCAD already got for a changed `.scad` closure with no moved check.

   **A gap discards observed movement from the verdict, and from nothing else.** The
   `indeterminate` reason therefore takes one of two shapes, and the distinction is
   normative because only one of them is true at a time:

   - **nothing was observed to move** — the digests match and no `imports` entry differs.
     The reason MUST carry the sentence *"nothing this diff can see changed, which is not
     the same claim as nothing changed"*, verbatim.
   - **something was observed to move** — a moved closure digest, or a moved, appeared or
     disappeared import. The reason MUST name what moved and MUST NOT carry that sentence,
     because it would assert nothing was seen to change while the same line names something
     that changed. Through v0.7.4 this case was unreachable: `digest != digest` returned
     `changed` before the partiality check, so the sentence was only ever emitted with
     matching digests. Removing that short-circuit is correct — `changed` was never
     outcome-bearing, so the exit `0` it produced was an unearned `identical` — and it is
     what makes the second shape necessary.

   **Malformation fails closed, and separately from age.** Three states are distinguished:
   a field **absent** is "written before the question was asked" and is the only state that
   may be reported as `imports_not_recorded`; a field **present in the wrong shape** is
   `malformed_closure`, on either tier; and `partial` **disagreeing with `bool(unseen)`**
   violates §8.3's own invariant and is `unnamed_partial`. Collapsing any two of these
   opened a hole that failed open in review: a non-list `unseen` blocked on the Python tier
   and exited `0` on OpenSCAD, and `partial: true` beside `unseen: []` — the malformation
   closest to the real vocabulary — exited `0` where v0.7.4 exited `2`.

   **Migration.** A closure carrying no `unseen` predates 0.7.5. Where the field could have
   carried an answer — a Python closure, `scope: "model_directory"` — `diff` synthesises the
   bounded gap `imports_not_recorded`, which reproduces that report's existing exit 2 and
   names re-recording the baseline as the fix. **Naming it is a MUST, in the artifact and
   in the output**: a bounded gap that has a remedy carries it on the `indeterminate`
   entry as `remedy`, printed as its own line directly under the headline, because the
   `reason` ends in a sentence this rule fixes verbatim and a step spliced into that
   sentence would read as its consequence. Through v0.7.4 this comparison stated the cause
   and stopped — on the one exit `2` every upgrading user meets — while this document, the
   changelog, the code's own comment and its test all said the remedy was named. A gap with
   no remedy MUST NOT be given one: `unidentified_imports` is a property of how a package is
   distributed, and inventing a step sends a reader to do work that cannot help. A pre-0.7.5 **OpenSCAD** closure is
   classified from the legacy fields instead (`unresolved` → `unresolved_includes`,
   `reads_external_data` → `external_data_reads`, and a bare `partial: true` →
   `unnamed_partial`), because a complete one has no gap and flipping it to exit 2 on
   upgrade would be a false alarm about a question that tier never had. Those three plus
   `malformed_closure` are synthesised by this verb and are not part of the producer
   vocabulary §8.3 defines.
4. **Check ids MUST be unique within each input**, refused with exit `64` (#148). The
   comparator joins on `id`, so a report carrying two checks under one id does not merely
   lose a check — the second silently replaces the first and two unrelated claims are
   compared as one. Measured before the guard existed: a `genus` check aliased onto a
   `param_range` check reported `limit_changed` from `{"kind": "param_range"}` to
   `{"kind": "genus"}` at exit `1`, with the displaced claim absent from the output
   entirely. `counts.total` does not catch it — such a report carries exactly the number
   of checks it claims. Two neighbouring refusals share this precondition, because the join
   must be keyable and must key each check to itself: a check carrying no `id` is a missing
   REQUIRED field and is refused as that rather than as a repeated `null`, and an `id` that
   is not a string is refused as a type error — §7.1 types it as a string, and comparing
   ids any other way lets `1` and `1.0` pass a uniqueness check and then collapse onto one
   another in the join. `Part._add` refuses both the clash and the non-string id at
   authoring time, so `partspec` emits neither; this rule binds `diff` because the report
   schema is the product surface (D5) and the comparator must not assume it produced its
   own input.

## 3. What is compared

Checks join on `id` (`SPEC-report.md` §7.1 fixes `id` as the join key). Per check:

- **`removed` / `added`** — present in only one report. A removed check is the
  silent-weakening signal and is always a difference, whatever the statuses were.
- **`regressed` / `fixed`** — status changed, ordered by the severity that `verdict_of`
  already uses (`fail` > `unsupported` > `approximate` > `skipped` > `pass`). Any status
  change is a difference. A status-change entry MUST also carry the claim and value deltas
  when those moved: loosening a limit until a failing check passes is the flagship
  weakening move, and an entry saying only "fixed" would report the attack as an
  improvement. The **§1 headline** MUST state the same fact, since the reason is a
  statement about readers and the headline is the surface a human reads: a `regressed` or
  `fixed` count says how many of its entries also moved the claim. The count itself stays
  the bucket's true total; the qualifier breaks it down. Neither `limit_changed` (where the
  claim moving is the bucket) nor `drifted` (which cannot carry one) takes the qualifier.
  This rule reaches a *moved claim* and no further, and the gap that leaves is stated here
  rather than left to be inferred from the reason given for the rule. `pass` is the only
  status in the severity order that means the check was answered and held, so **every**
  transition into `approximate`, `unsupported` or `skipped` from a status ranked above it
  is bucketed `fixed` — a check that is not answered on the new side, filed as one that was
  answered better. Not only when it left `fail`, and not always a check that *stopped* being
  answerable: `unsupported` → `skipped` was not answered on either side. Within a status
  bucket the qualifier reads the claim and nothing else, so where the claim did not move it
  does not fire and the headline reports the transition as a repair. Such an entry is
  usually not otherwise empty — a check that stops being evaluated normally loses its
  measurement with it, and all four `skipped`/`unsupported` sites in the runner build the
  result without one — so a `value` delta is generally present and is not what the qualifier
  reads. Generally, not always: `fail` → `approximate` over an unchanged measurement, and
  any transition between two unmeasured statuses, carry nothing but the status. That is
  #325, and unfixed.
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

**Recorded but never outcome-bearing**: `contract_digest`, `source_digest`, the closure
digest and the closure's `imports` map. All four appear in the artifact — as
`contract.digest_changed`, `source.digest_changed`, `source.closure_digest_changed` and
`source.imports` — so a reader can see the inputs moved, and none of them can make an
outcome `different` on its own. The closure digest gets a field of its own rather than
riding `source.closure`, because a bounded gap collapses that field to `inconclusive` and
would otherwise take the only record of closure movement with it. The
contract digest is module-scoped and over-fires deliberately (`SPEC-report.md` §7.1) — an
unrelated docstring edit moves it — and a comment added to a `.scad` is not a semantic
difference of the part. A verb that reported `different` on either would be piped through
`|| true` inside a week, and what this comparison actually covers *is* the contract's
observable content: every check id, every field in `CLAIM_FIELDS`, every status and every
measurement. The closure is the exception that proves the rule: neither its digest nor a
moved `imports` entry can make an outcome `different`, but under §2 rule 3 an absent
closure or a bounded gap does block `identical`, because there the question is whether the
inputs were fully identified at all. Holding the line at "a moved library is not by itself
a difference of the part" is what keeps arm A and arm B one tool: OpenSCAD has always got
exit `0` for a changed `.scad` closure under unmoved checks, and the summary line naming
the distribution that moved is what carries that fact to the reader (#190).

Alongside them, the environment facts that *explain* differences without being differences
of the part — `tool_version`, `engine.version`, `engine.render_backend` and
`environment.packages` — reported only when they changed (`SPEC-report.md` §8's principle:
a dependency upgrade moving a number is a different explanation than the design changing).

**`environment.packages` is compared in three groups, and the split is normative.**
`changed` names a distribution whose version moved: a build input changed, and it is the
thing that explains a moved measurement. `added` and `removed` name distributions installed
on one side only, which is most often two machines resolving different transitive
dependency sets — CI against a laptop — and explains nothing about the part on its own.
Reporting both under one heading would leave the reader to separate them by hand.
`SPEC-report.md` §8 rule 2 says in bold that this field MUST NOT be excluded from
comparison; through v0.7.4 this comparator excluded it entirely (#211).

**The first comparison against a pre-v0.7.5 baseline MUST NOT report the widening as
installations.** The old field held at most five engine names, so every other installed
distribution is `added` against it. Nothing was installed; the recorded surface widened,
and the summary says that in those words with its remedy — re-record the baseline, the
same one-time step an upgrade already asks for. The names are listed in
`environment.packages.first_recorded`, and they stay in `added`, which is what that group
means. The split is by name against the old five: `trimesh` absent from a pre-0.7.5 report
genuinely was not installed, so it is an appearance and is reported as one on the same
line. Through v0.7.4 the whole group printed as `packages appeared: PyJWT 2.13.0, PyYAML
6.0.3, +107 more` — 109 installations reported, none of which happened — while this
paragraph already said what had actually occurred. An old report is dated by its closure
carrying no `imports` (`SPEC-report.md` §8.3), the same evidence rule 3 above reads, and
never by parsing `tool.version`.

When a side carries no usable `packages` map the artifact says so — `environment.packages`
becomes `{ "uncomparable": "…" }` — rather than omitting the key. An omission is
indistinguishable from "no dependency moved", which is a claim the comparison did not make.
It does not change the outcome: an old report that predates the field still diffs.

## 4. The artifact

```jsonc
{
  "schema_version": 2,              // this artifact's own version, not the report's
  "tool": { "name": "partspec-diff", "version": "0.7.6" },
                                    // partspec's own version. `diff` has none of its own
                                    // and never has, so a sample showing one invites a
                                    // consumer to key on a number that will never appear.
                                    // `schema_version` above versions this artifact.
  "part": "example-spacer",
  "outcome": "different",           // identical | different | indeterminate
  "indeterminate": [],              // {code, reason[, remedy]} entries when indeterminate;
                                    // `remedy` is present only where the gap has one, and
                                    // is printed under the headline; codes are
                                    // machine-readable: "input_error" | "partial_closure",
                                    // so CI can tolerate one narrowly instead of tolerating
                                    // exit 2 wholesale. `partial_closure` now covers only
                                    // bounded gaps and absent closures; the reason names
                                    // each one, and `source.unseen.bounded` keys them
  "verdict": { "old": "pass", "new": "fail" },
  "counts_total": { "old": 8, "new": 7 },
  "contract": {
    "digest_changed": true,
    "removed": ["wall_gt_2"],       // the headline finding, by id
    "added": []
  },
  "source": {
    "digest_changed": false,         // the entry file
    "closure": "changed",            // same | changed | inconclusive — whether the two
                                     // reports RECORDED different closures, not whether
                                     // the part's inputs moved: an entry in
                                     // `imports.unattributable` makes it "changed" while
                                     // saying nobody can tell whose import it was
    "closure_digest_changed": true,  // the closure digest, on its own field because a
                                     // bounded gap collapses `closure` to "inconclusive";
                                     // null when a side carries no closure at all
    "imports": {                     // the distributions the model loaded (SPEC-report 8.3),
                                     // three groups for the reason `environment.packages`
                                     // has three; `{ "uncomparable": "…" }` when a side
                                     // recorded no map, never an empty delta
      "changed": { "cqgridfinity": { "old": { "…": "…" }, "new": { "…": "…" } } },
      "added": {},
      "removed": {},
      "unattributable": []           // names in `added`/`removed` that a side's
                                     // `preloaded` covers: on one side only, and this
                                     // comparison cannot say whether they moved.
                                     // Never reported as an appearance, and never
                                     // explained away as batch position either
    },
    "unseen": {                      // the gaps by class, token -> what it says to a reader
      "irreducible": { "native_reads": "files read inside C extensions — …" },
      "bounded": {}                  // non-empty here means `closure: "inconclusive"`
    },
    "covered": "model directory (2 files); 14 imported distributions, all unchanged"
                                     // null where neither closure carries `unseen`, i.e.
                                     // two pre-0.7.5 reports, which get no coverage block
                                     // invented for a coverage they never recorded
  },
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
  "environment": {
    "engine_version": { "old": "2021.01", "new": "2026.08.01" },
    "packages": {                    // present when a package differs, and in the
                                     // `uncomparable` shape when a side has no map;
                                     // absent when both sides carry the same map
      "changed": { "trimesh": { "old": "5.0.0", "new": "5.1.0" } },   // a version moved
      "added":   { "shapely": "2.1.2" },   // installed on the new side only
      "removed": {},                       // installed on the old side only
      "first_recorded": []                 // names in `added` the pre-0.7.5 five-name
                                           // field could not have carried: the record
                                           // widening, never an install
    }
  }
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
