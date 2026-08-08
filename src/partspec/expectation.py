"""The claims pin: a committed record of what a contract is expected to assert.

The central agent threat (#31): "make the check pass" and "delete the check"
are the same action from where a model sits, and the result of the second is
an internally consistent green report. `partspec diff` sees it — on
comparison, given a previous artifact. This is the no-baseline half: a
lockfile committed beside the contract pins the *claim set*, and a run whose
declared claims differ fails before the engine starts, naming exactly what
moved.

The pin covers the set, not the count: every claim is slugged from its
declaration — kind, limits, region, hole geometry, expression, and citation —
so swapping a strict check for a lax one under the same id is a `changed`
entry, and stripping a `source` citation (laundering an attributed bound into
an authorless one) is too. Deliberate updates are one flag (`--pin`);
accidental ones would require editing a generated file by hand.

Two scope limits, stated rather than implied. The pin binds the CLAIM set,
not the source: identical claims pointed at a different model pass — source
identity belongs to `source_digest` and `diff`. And the lockfile is a
generated file an agent can regenerate, so the tamper-resistance that makes
the pin bite is the committed lock showing in review plus the agent contract
(#28) declaring re-pin-after-weakening out of bounds; the tool's job is to
make the weakening IMPOSSIBLE to do silently, not impossible to do.

Spec: SPEC-report.md §7.1 (`expectation`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .status import Limit

if TYPE_CHECKING:
    from .contract import CheckSpec, Part

__all__ = ["LockError", "claims_of", "compare", "read_lock", "write_lock"]

LOCK_SCHEMA_VERSION = 1


class LockError(Exception):
    """The lockfile is missing, malformed, or does not cover this part."""


def _limit_slug(limit: Limit | None) -> str:
    if limit is None:
        return ""
    parts = []
    # Every Limit form, including `choices` — no Part method emits it today,
    # but a form the slug ignores is a weakening channel waiting for the
    # first check that adopts it (PR #105 review, F4).
    for name in ("min", "max", "equals", "choices"):
        value = getattr(limit, name, None)
        if value is not None:
            parts.append(f"{name}={json.dumps(value)}")
    return " ".join(parts)


def _claim_slug(spec: CheckSpec) -> str:
    """One deterministic line per declaration.

    Everything that makes the claim the claim participates — the same fields
    `diff` treats as claim-changing (limit, region, hole, source) plus kind
    and expression — so no weakening move is invisible to the pin. JSON with
    sorted keys for the dict-shaped fields, because Python repr ordering is
    not a stability promise.
    """
    fields = [spec.kind]
    if spec.expr:
        fields.append(f"expr={spec.expr}")
    slug = _limit_slug(spec.limit)
    if slug:
        fields.append(slug)
    if spec.region is not None:
        fields.append(f"region={json.dumps(spec.region.to_json(), sort_keys=True)}")
    if spec.shell is not None:
        fields.append(f"shell={spec.shell:g}")
    if spec.hole is not None:
        fields.append(f"hole={json.dumps(spec.hole, sort_keys=True)}")
    if spec.source is not None:
        fields.append(f"source={json.dumps(spec.source, sort_keys=True)}")
    return " ".join(fields)


def claims_of(part: Part) -> dict[str, str]:
    """id -> claim slug for every declared check, engine never consulted."""
    return {spec.id: _claim_slug(spec) for spec in part.checks}


def write_lock(path: Path, parts: dict[str, dict[str, str]]) -> None:
    doc = {"schema_version": LOCK_SCHEMA_VERSION, "parts": parts}
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def read_lock(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise LockError(f"no claims pin at {path}; create one with --pin {path}")
    try:
        doc = json.loads(path.read_text())
        if doc.get("schema_version") != LOCK_SCHEMA_VERSION:
            raise LockError(
                f"{path} has schema_version {doc.get('schema_version')!r}, "
                f"expected {LOCK_SCHEMA_VERSION}"
            )
        parts = doc["parts"]
        assert isinstance(parts, dict)
        for claims in parts.values():
            assert isinstance(claims, dict)
    except LockError:
        raise
    except Exception as exc:  # noqa: BLE001 - any malformation is the same refusal
        raise LockError(f"{path} is not a claims pin: {type(exc).__name__}: {exc}") from None
    return parts


def compare(pinned: dict[str, str], declared: dict[str, str]) -> list[str]:
    """Human-readable differences, empty when the sets match exactly.

    Every direction is named, added included: a pin is an exact statement,
    and an addition nobody re-pinned is still a contract that is not the one
    reviewed. The messages carry both slugs on a change, so the reader sees
    what moved without opening two files.
    """
    differences = []
    for check_id in sorted(pinned.keys() - declared.keys()):
        differences.append(f"removed: {check_id} ({pinned[check_id]})")
    for check_id in sorted(declared.keys() - pinned.keys()):
        differences.append(f"added: {check_id} ({declared[check_id]})")
    for check_id in sorted(pinned.keys() & declared.keys()):
        if pinned[check_id] != declared[check_id]:
            differences.append(
                f"changed: {check_id} — pinned '{pinned[check_id]}', "
                f"declared '{declared[check_id]}'"
            )
    return differences
