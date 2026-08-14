"""Semantic comparison of two reports of one part.

The consumer `SPEC-report.md` §7.2 recorded measurements-on-pass for, and the
comparison §7.1's silent-weakening gap was waiting on: a deleted check is
invisible inside one green report and unmissable between two.

Spec: SPEC-diff.md.
"""

from __future__ import annotations

from typing import Any

from .report import SCHEMA_VERSION
from .status import _SEVERITY, Status, comparison_exit_code, epsilon

__all__ = [
    "CLAIM_FIELDS",
    "DIFF_SCHEMA_VERSION",
    "NON_CLAIM_FIELDS",
    "DiffUsageError",
    "diff_reports",
    "exit_code_of",
    "summary_of",
]

DIFF_SCHEMA_VERSION = 1

CLAIM_FIELDS = ("kind", "expr", "limit", "region", "hole", "source", "direction")
"""The fields that make a check the claim it is.

Public and named because SPEC-diff.md §3 enumerates them and two tests hold
the three lists in step. The list has drifted three times unnoticed, each
time in the direction that reads a weakened contract as `identical`:
`direction` arrived with `draft_angle` and was never documented; `kind` was
never compared at all, so swapping `genus` for `cavities` under one id passed
as no difference; and `expr` — the entire predicate of a `requires` check —
was missing, so `wall >= 2.0` becoming `wall >= 0.2` was invisible.

Every other key `CheckResult.to_json` emits is deliberately NOT here, and
`NON_CLAIM_FIELDS` says which and why, so the next field added to the report
has to be classified rather than silently ignored.
"""

NON_CLAIM_FIELDS = {
    "id": "the join key itself — a changed id is a removed check plus an added one",
    "status": "a result, compared separately and reported as regressed/fixed",
    "measurement": "a result, compared separately and reported as drifted",
    "operands": "a result — the values the expression saw, compared separately",
    "components": "a result, derived from measurement against limit",
    "detail": "prose about a result, not a claim",
    "phase": "structural, and cannot move without kind or expr moving with it",
    "requires": "which tier would answer a refusal — environment, like engine.version",
    "step": (
        "the STEP writer schema — tool-chosen, not author-declared, so not a claim. "
        "Note it is not surfaced anywhere else either: unlike engine.version it does "
        "NOT reach the environment block, so a schema change beside a drifted "
        "round-trip measurement goes unexplained. A known gap, stated rather than "
        "implied by calling it environment"
    ),
}
"""Why each non-claim field is not compared as a claim.

The reverse of `CLAIM_FIELDS`, and the reason the pair is testable: a claim
that the comparator covers "every field that makes a check the claim it is"
can only be checked if the fields it does NOT cover are enumerated too. PR
#147 made that claim in three places while `expr` was missing from both
lists, and no test could have noticed.
"""


class DiffUsageError(Exception):
    """The inputs cannot be compared at all — a usage error (exit 64), never a
    finding. Unreadable input, unknown schema, or two different parts."""


def exit_code_of(outcome: str) -> int:
    """The shared policy (`status.comparison_exit_code`), re-exported so both
    verbs keep their own name for it."""
    return comparison_exit_code(outcome)


def _values_equal(old: Any, new: Any) -> bool:
    """Equality under the adjudication epsilon, old value as reference.

    Exact float equality would report the ~1e-13 coordinate noise a different
    transform-composition order produces, burying signal (SPEC-diff.md §3).
    """
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(
            _values_equal(a, b) for a, b in zip(old, new, strict=True)
        )
    if (
        isinstance(old, int | float)
        and isinstance(new, int | float)
        and not isinstance(old, bool)
        and not isinstance(new, bool)
    ):
        return abs(float(new) - float(old)) <= epsilon(float(old))
    return old == new


def _check_entry(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    """The difference one joined check pair contributes, or None."""
    base = {"id": new["id"], "kind": new["kind"]}
    # `source` is part of the claim: a bound whose citation was stripped —
    # same number, authority gone — is the quiet half of the weakening move,
    # and "no semantic differences" over it would be exactly the silence this
    # verb exists to refuse (#92).
    # `kind` and `expr` are claim fields too, and both were missing. Swapping
    # `genus` for `cavities` under one id turns "no through-holes" into "one
    # sealed void"; loosening `wall >= 2.0` to `wall >= 0.2` rewrites the
    # predicate outright. Both read as `identical`, exit 0, until PR #147 and
    # its review each found one. `expectation._claim_slug` already covered
    # kind and expr and said so in its docstring; the two agree now.
    claim_fields = [f for f in CLAIM_FIELDS if old.get(f) != new.get(f)]
    claim = (
        {
            "old": {f: old.get(f) for f in claim_fields},
            "new": {f: new.get(f) for f in claim_fields},
        }
        if claim_fields
        else None
    )
    old_value = (old.get("measurement") or {}).get("value")
    new_value = (new.get("measurement") or {}).get("value")
    value_moved = not _values_equal(old_value, new_value)

    if old["status"] != new["status"]:
        # A status change does not get to hide what else moved: loosening a
        # limit until a failing check passes is the flagship weakening move,
        # and an entry saying only "fixed" would report the attack as an
        # improvement. The claim and value deltas ride along.
        worse = _SEVERITY[Status(new["status"])] > _SEVERITY[Status(old["status"])]
        entry = {
            **base,
            "change": "regressed" if worse else "fixed",
            "status": {"old": old["status"], "new": new["status"]},
        }
        if claim is not None:
            entry["claim"] = claim
        if value_moved:
            entry["value"] = {"old": old_value, "new": new_value}
        return entry

    if claim is not None:
        return {**base, "change": "limit_changed", "status": old["status"], "claim": claim}

    if value_moved:
        return {
            **base,
            "change": "drifted",
            "status": old["status"],
            "value": {"old": old_value, "new": new_value},
        }

    old_ops, new_ops = old.get("operands"), new.get("operands")
    if (old_ops or new_ops) and (
        set(old_ops or {}) != set(new_ops or {})
        or any(not _values_equal(v, (new_ops or {}).get(k)) for k, v in (old_ops or {}).items())
    ):
        return {
            **base,
            "change": "drifted",
            "status": old["status"],
            "operands": {"old": old_ops, "new": new_ops},
        }
    return None


def _closure_state(old_part: dict[str, Any], new_part: dict[str, Any]) -> str:
    old_closure, new_closure = old_part.get("source_closure"), new_part.get("source_closure")
    if old_closure is None and new_closure is None:
        # BOTH absent. SPEC-diff §2 rule 3 names this case in the same breath as
        # one-side-absent — "the ordinary v0.1.0 upgrade path" — and the rule
        # is the same: with no closure on either side, `identical` would rest
        # on `source_digest` alone, which is the overclaim SPEC-report §8.3
        # reversed itself to prevent. Returning None let it through.
        return "inconclusive"
    if not (old_closure and new_closure):
        # One run recorded a closure and the other did not — the ordinary
        # v0.1.0 upgrade path for every Python part, since its closure landed
        # after the tag. "Changed" would be a claim about the source; nothing
        # here supports one, and calling it changed let the identical claim
        # through unearned (PR #88 review, B1). Inconclusive, which blocks
        # `identical` and nothing else.
        return "inconclusive"
    if old_closure.get("digest") != new_closure.get("digest"):
        return "changed"
    if old_closure.get("partial") or new_closure.get("partial"):
        return "inconclusive"
    return "same"


def _packages_of(environment: Any) -> dict[str, Any] | None:
    """The `environment.packages` map, or None when there is nothing to compare."""
    if not isinstance(environment, dict):
        return None
    packages = environment.get("packages")
    return packages if isinstance(packages, dict) else None


def _packages_delta(old_env: Any, new_env: Any) -> dict[str, Any] | None:
    """Compare `environment.packages` — the field SPEC-report §8 rule 2 says in
    bold MUST NOT be excluded, and which this comparator excluded entirely.

    It is the field that distinguishes "a trimesh upgrade moved this number"
    from "the design changed". Without it a dependency bump produced a
    `different` verdict with nothing on the page to explain it, and the reader
    had to guess which of the two had happened — the guess the field exists to
    remove.

    Three groups, not one, because two facts are being reported and they are
    not the same fact. A version that *moved* is a change to a build input and
    explains a moved measurement. A package that *appeared or disappeared* is
    usually two machines resolving different transitive dependency sets — a CI
    runner against a laptop — and explains nothing on its own. Folding them
    together would make the reader do that separation by hand.

    Returns None when nothing differs, matching the other environment keys,
    which are reported only when they changed. When a side carries no usable
    map the result is NOT None: an omission would read as "no package moved",
    which is a claim this comparison did not make.
    """
    old_packages, new_packages = _packages_of(old_env), _packages_of(new_env)
    if old_packages is None or new_packages is None:
        missing = [
            label
            for label, packages in (("old", old_packages), ("new", new_packages))
            if packages is None
        ]
        where = "both sides" if len(missing) == 2 else f"the {missing[0]} side"
        return {
            "uncomparable": f"no environment.packages map on {where}, so whether a "
            "dependency moved is unknown"
        }
    changed = {
        name: {"old": version, "new": new_packages[name]}
        for name, version in sorted(old_packages.items())
        if name in new_packages and new_packages[name] != version
    }
    added = {name: v for name, v in sorted(new_packages.items()) if name not in old_packages}
    removed = {name: v for name, v in sorted(old_packages.items()) if name not in new_packages}
    if not (changed or added or removed):
        return None
    return {"changed": changed, "added": added, "removed": removed}


def diff_reports(old: dict[str, Any], new: dict[str, Any], *, tool_version: str) -> dict[str, Any]:
    """Compare two parsed reports. Raises DiffUsageError on unusable input."""
    for label, report in (("old", old), ("new", new)):
        if not isinstance(report, dict):
            raise DiffUsageError(f"the {label} input is not a report (top level is not an object)")
        if report.get("schema_version") != SCHEMA_VERSION:
            raise DiffUsageError(
                f"the {label} report has schema_version {report.get('schema_version')!r}; "
                f"this diff understands report schema {SCHEMA_VERSION} and must not "
                f"best-effort parse anything else (SPEC-report.md 7.1)"
            )
        # `or []` so a literal `"checks": null` reaches the branches below
        # rather than raising `TypeError: object of type 'NoneType' has no
        # len()` out of the counts check. Bound once, above the first reader,
        # because two readers spelling the fallback differently is how the
        # first one ended up not having it.
        #
        # Named `raw_checks`, not `entries`: this function rebinds `entries`
        # further down to the diff's own output list, and one name for two
        # meanings in one scope is a trap for the next edit (PR #157 review).
        raw_checks = report.get("checks") or []

        total = report.get("counts", {}).get("total")
        if total is not None and total != len(raw_checks):
            # counts.total is redundant by construction in an honest report;
            # an input that violates its own invariant is corrupt, and no
            # claim over corrupt input is earned.
            raise DiffUsageError(
                f"the {label} report is corrupt: counts.total is {total} but it "
                f"carries {len(raw_checks)} checks"
            )

        # Everything below is ONE precondition on the join at the bottom of this
        # function: `{c["id"]: c}` must be keyable, and must key each check to
        # itself. Split into branches only so the message names the actual defect.
        if not_objects := [c for c in raw_checks if not isinstance(c, dict)]:
            raise DiffUsageError(
                f"the {label} report has {len(not_objects)} entr(y/ies) in `checks` that "
                f"are not objects (first: {not_objects[0]!r}); every check is an object "
                f"with an `id` (SPEC-report.md 7.1)"
            )
        ids = [c.get("id") for c in raw_checks]

        # A check with no id is a MISSING FIELD, not a collision, and saying so
        # matters: mapping it to None first made two id-less checks report as
        # "None appears more than once", which is a confident diagnosis of the
        # wrong defect. Before this guard the join raised `KeyError: 'id'` and
        # the CLI rendered "not well-formed reports", which was less precise but
        # not misleading (PR #157 review).
        absent = sum(1 for i in ids if i is None)
        if absent:
            raise DiffUsageError(
                f"the {label} report has {absent} check(s) with no `id`. "
                f"`checks[].id` is REQUIRED and is the key this comparison joins on "
                f"(SPEC-report.md 7.1)"
            )

        # And the id must be a STRING, which SPEC-report §7.1 types it as.
        #
        # `CheckResult.id: str` is an annotation, not an enforcement, so that
        # alone did not make this safe to assume: `p.param("wall", min=2.0,
        # id=3)` was accepted by authoring and `check` wrote `"id": 3`, which
        # this branch would then have refused at 64 — blaming the artifact for a
        # contract error. `Part._add` now refuses a non-string id where it is
        # written, so nothing partspec emits reaches here (PR #157 review).
        #
        # This replaces a `repr`-keyed uniqueness count, which was a fix for
        # mixed-type and unhashable ids that reopened the very hole this guard
        # exists to close. `repr` compares ids by their RENDERING while the join
        # keys a dict on their VALUE, and the two disagree wherever Python's
        # `==`/`hash` merge distinct JSON literals: `1` and `1.0` (and `true`
        # and `1`) render differently, pass the count, and then collapse onto
        # one another in the join. Measured: a four-check report with ids `1`
        # and `1.0` was joined as three checks, no refusal, exit 1 — the same
        # confident wrong answer described above, reached through the guard
        # meant to prevent it (PR #157 review).
        #
        # Refusing the type instead of routing around it fixes all three at
        # once: a non-string never reaches the sort (no TypeError on mixed
        # types), never reaches the set (no TypeError on an unhashable list),
        # and cannot alias by numeric equality. `isinstance(True, str)` is
        # False, so booleans are covered.
        if malformed := [i for i in ids if not isinstance(i, str)]:
            raise DiffUsageError(
                f"the {label} report has check ids that are not strings "
                f"({', '.join(map(repr, malformed))}); `checks[].id` is typed as a string "
                f"and is the key this comparison joins on (SPEC-report.md 7.1)"
            )

        # Ids must be unique, for the same reason and in the same class (#148).
        # The comparator joins on id, so a report carrying two checks under one
        # id does not merely lose information — it produces a CONFIDENT WRONG
        # answer. Measured before this guard, on the input
        # `test_a_report_with_two_checks_under_one_id_is_corrupt_input` builds:
        # the displaced `param_range` claim vanished from the analysis entirely
        # and the survivor was reported as `limit_changed` from
        # `{"kind": "param_range"}` to `{"kind": "genus"}` — two unrelated
        # claims diffed as one, exit 1.
        #
        # `counts.total` cannot catch this: both reports carried the number of
        # checks they said they did. Uniqueness is a separate invariant.
        #
        # `Part._add` already refuses an id clash at authoring time, so partspec
        # cannot emit such a report. That is exactly why this belongs here: the
        # report schema is the stable product surface (D5), `diff` consumes
        # whatever is handed to it, and a guarantee that holds only for reports
        # we produced is not one the comparator may assume.
        #
        # Counted by value, the same way the join keys — so the guard and the
        # join agree by construction rather than by two implementations
        # happening to match. Safe now that every id is known to be a string.
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise DiffUsageError(
                f"the {label} report is corrupt: check ids must be unique because the "
                f"comparison joins on them, and these appear more than once: "
                f"{', '.join(repr(i) for i in duplicated)}. Two different claims under "
                f"one id are compared as if they were the same claim."
            )
    old_part, new_part = old.get("part", {}), new.get("part", {})
    if old_part.get("id") != new_part.get("id"):
        raise DiffUsageError(
            f"these reports describe different parts ({old_part.get('id')!r} vs "
            f"{new_part.get('id')!r}); diff compares two runs of one part"
        )

    indeterminate: list[dict[str, str]] = []
    for label, report in (("old", old), ("new", new)):
        if report.get("verdict") == "error":
            indeterminate.append(
                {
                    "code": "input_error",
                    "reason": f"the {label} report's run did not complete (verdict: "
                    f"error); its checks measured nothing to compare",
                }
            )

    # `or []` matching the validation loop's fallback: `"checks": null` is a
    # real shape a hand-written report can take, and spelling the fallback two
    # ways is how the counts check ended up raising TypeError past a guard that
    # had already handled it.
    old_checks = {c["id"]: c for c in old.get("checks") or []}
    new_checks = {c["id"]: c for c in new.get("checks") or []}
    removed = [check_id for check_id in old_checks if check_id not in new_checks]
    added = [check_id for check_id in new_checks if check_id not in old_checks]
    entries = [
        entry
        for check_id, old_check in old_checks.items()
        if check_id in new_checks
        for entry in [_check_entry(old_check, new_checks[check_id])]
        if entry is not None
    ]

    closure = _closure_state(old_part, new_part)
    verdict_changed = old.get("verdict") != new.get("verdict")
    different = bool(removed or added or entries or verdict_changed)
    if indeterminate:
        outcome = "indeterminate"
    elif different:
        outcome = "different"
    elif closure == "inconclusive":
        # The partial-closure rule (SPEC-diff.md §2 rule 3): matching digests on a
        # partial closure mean "nothing we looked at changed". Claiming
        # `identical` on that evidence is silence-as-success at the
        # provenance layer.
        indeterminate.append(
            {
                "code": "partial_closure",
                "reason": "no differences found, but the source identity rests on a "
                "closure marked partial or absent: nothing this diff can see changed, "
                "which is not the same claim as nothing changed",
            }
        )
        outcome = "indeterminate"
    else:
        outcome = "identical"

    environment: dict[str, Any] = {}
    for key, old_value, new_value in (
        ("tool_version", old.get("tool", {}).get("version"), new.get("tool", {}).get("version")),
        (
            "engine_version",
            old.get("engine", {}).get("version"),
            new.get("engine", {}).get("version"),
        ),
        (
            "render_backend",
            old.get("engine", {}).get("render_backend"),
            new.get("engine", {}).get("render_backend"),
        ),
    ):
        if old_value != new_value:
            environment[key] = {"old": old_value, "new": new_value}

    packages = _packages_delta(old.get("environment"), new.get("environment"))
    if packages is not None:
        environment["packages"] = packages

    return {
        "schema_version": DIFF_SCHEMA_VERSION,
        "tool": {"name": "partspec-diff", "version": tool_version},
        "part": old_part.get("id"),
        "outcome": outcome,
        "indeterminate": indeterminate,
        "verdict": {"old": old.get("verdict"), "new": new.get("verdict")},
        "counts_total": {
            "old": old.get("counts", {}).get("total"),
            "new": new.get("counts", {}).get("total"),
        },
        "contract": {
            "digest_changed": old_part.get("contract_digest") != new_part.get("contract_digest"),
            "removed": removed,
            "added": added,
        },
        "source": {
            "digest_changed": old_part.get("source_digest") != new_part.get("source_digest"),
            "closure": closure,
        },
        "checks": entries,
        "environment": environment,
    }


_SUMMARY_PACKAGE_LIMIT = 2
"""How many distributions the one-line summary names per group.

`environment.packages` now records every distribution the run imported — 15 on
the fleet's cadquery venv, 84 installed — so two runs on different machines can
differ in dozens of entries. Spilling all of them onto the summary line would
bury the finding the line exists to state. The artifact on stdout carries the
complete lists; the line names a couple and counts the rest."""


def _packages_clause(doc: dict[str, Any]) -> str:
    """The summary's `packages` fragment, or an empty string when nothing moved."""
    packages = doc.get("environment", {}).get("packages")
    if not packages:
        return ""
    if "uncomparable" in packages:
        return f"; packages not compared: {packages['uncomparable']}"

    def bounded(entries: list[str]) -> str:
        shown = entries[:_SUMMARY_PACKAGE_LIMIT]
        rest = len(entries) - len(shown)
        return ", ".join(shown) + (f", +{rest} more" if rest else "")

    clauses = []
    if packages["changed"]:
        moved = [f"{n} {v['old']} → {v['new']}" for n, v in packages["changed"].items()]
        clauses.append(f"packages moved: {bounded(moved)}")
    for group, verb in (("added", "appeared"), ("removed", "disappeared")):
        if packages[group]:
            named = [f"{n} {v}" for n, v in packages[group].items()]
            clauses.append(f"packages {verb}: {bounded(named)}")
    return "; " + "; ".join(clauses)


def summary_of(doc: dict[str, Any]) -> str:
    """The one-line stderr courtesy summary."""
    # The packages clause rides every outcome, `identical` included. A
    # dependency that moved under an unchanged part is precisely the case
    # `identical: no semantic differences` would otherwise report as an
    # unqualified nothing-happened.
    moved = _packages_clause(doc)
    if doc["outcome"] == "identical":
        return f"identical: {doc['part']} — no semantic differences{moved}"
    if doc["outcome"] == "indeterminate":
        reasons = "; ".join(entry["reason"] for entry in doc["indeterminate"])
        return f"indeterminate: {doc['part']} — {reasons}{moved}"
    contract = doc["contract"]
    parts = []
    if contract["removed"]:
        parts.append(
            f"{len(contract['removed'])} check(s) removed: {', '.join(contract['removed'])}"
        )
    if contract["added"]:
        parts.append(f"{len(contract['added'])} added")
    for change in ("regressed", "fixed", "drifted", "limit_changed"):
        n = sum(1 for c in doc["checks"] if c["change"] == change)
        if n:
            parts.append(f"{n} {change}")
    return f"different: {doc['part']} — {'; '.join(parts) or 'verdict changed'}{moved}"
