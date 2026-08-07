"""Semantic comparison of two reports of one part.

The consumer `SPEC-report.md` §7.2 recorded measurements-on-pass for, and the
comparison §7.1's silent-weakening gap was waiting on: a deleted check is
invisible inside one green report and unmissable between two.

Spec: SPEC-diff.md.
"""

from __future__ import annotations

from typing import Any

from .report import SCHEMA_VERSION
from .status import _SEVERITY, Status, epsilon

__all__ = ["DIFF_SCHEMA_VERSION", "DiffUsageError", "diff_reports", "exit_code_of", "summary_of"]

DIFF_SCHEMA_VERSION = 1

_EXIT = {"identical": 0, "different": 1, "indeterminate": 2}


class DiffUsageError(Exception):
    """The inputs cannot be compared at all — a usage error (exit 64), never a
    finding. Unreadable input, unknown schema, or two different parts."""


def exit_code_of(outcome: str) -> int:
    return _EXIT[outcome]


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
    claim_fields = [f for f in ("limit", "region", "hole") if old.get(f) != new.get(f)]
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


def _closure_state(old_part: dict[str, Any], new_part: dict[str, Any]) -> str | None:
    old_closure, new_closure = old_part.get("source_closure"), new_part.get("source_closure")
    if old_closure is None and new_closure is None:
        return None
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
        total = report.get("counts", {}).get("total")
        if total is not None and total != len(report.get("checks", [])):
            # counts.total is redundant by construction in an honest report;
            # an input that violates its own invariant is corrupt, and no
            # claim over corrupt input is earned.
            raise DiffUsageError(
                f"the {label} report is corrupt: counts.total is {total} but it "
                f"carries {len(report.get('checks', []))} checks"
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

    old_checks = {c["id"]: c for c in old.get("checks", [])}
    new_checks = {c["id"]: c for c in new.get("checks", [])}
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
        # The partial-closure rule (SPEC-diff.md §2.3): matching digests on a
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


def summary_of(doc: dict[str, Any]) -> str:
    """The one-line stderr courtesy summary."""
    if doc["outcome"] == "identical":
        return f"identical: {doc['part']} — no semantic differences"
    if doc["outcome"] == "indeterminate":
        reasons = "; ".join(entry["reason"] for entry in doc["indeterminate"])
        return f"indeterminate: {doc['part']} — {reasons}"
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
    return f"different: {doc['part']} — {'; '.join(parts) or 'verdict changed'}"
