"""The report artifact: the thing that actually is the contract.

Per D5 the CLI verbs are not the product surface — the report schema plus the exit
code is. Everything else (an MCP layer, `diff`, CI annotations, a scorecard) is a
consumer of this file. So it is defined before any geometry, and it is written on
every terminal outcome including a crash.

Spec: SPEC-report.md sections 5, 6, 7, 8.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .status import Limit, Measurement, Status, Verdict, exit_code, verdict_of

__all__ = [
    "SCHEMA_VERSION",
    "CheckResult",
    "Report",
    "write_placeholder",
]

SCHEMA_VERSION = 1
"""Bumped only on a breaking change. Adding a field is NOT breaking — consumers
must ignore unknown fields (SPEC-report.md 7.1) — so additive evolution is free.
Removing or re-typing one is breaking. Consumers must reject an unknown version
rather than best-effort parse it."""

REPORT_FILENAME = "report.json"


def _measurement_json(m: Measurement | None) -> dict[str, Any] | None:
    if m is None:
        return None
    out: dict[str, Any] = {
        "value": list(m.value) if m.is_vector else m.value,
        "unit": m.unit,
        "exactness": "exact" if m.exact else "approximate",
    }
    if m.bounds is not None:
        out["bounds"] = [list(b) for b in m.bounds] if m.is_vector else list(m.bounds)
    if m.axes is not None:
        out["axes"] = list(m.axes)
    return out


def _limit_json(limit: Limit | None) -> dict[str, Any] | None:
    if limit is None:
        return None
    out: dict[str, Any] = {}
    if limit.min is not None:
        out["min"] = limit.min
    if limit.max is not None:
        out["max"] = limit.max
    if limit.equals is not None:
        out["equals"] = limit.equals
    if limit.choices is not None:
        out["in"] = list(limit.choices)
    return out


@dataclass(slots=True)
class CheckResult:
    """One adjudicated claim.

    `measurement` is populated whenever the check was evaluated, *including when
    it passed*. That is non-obvious and load-bearing: it is what lets a future
    `diff` report drift on checks whose pass/fail state did not change. A wall
    thinning from 2.9mm to 2.1mm against a 2.0mm minimum is two passes and one
    very important trend, and nothing else in the system can see it.

    `expr` / `operands` replace measurement/limit for parameter predicates
    (SPEC-contract.md 5). Recording the operands means a failure reports the
    inputs that produced it rather than a bare `false`.
    """

    id: str
    kind: str
    phase: str  # "parameter" | "geometry"
    status: Status
    measurement: Measurement | None = None
    limit: Limit | None = None
    components: dict[str, Status] | None = None
    """Axis -> status for a vector check, so a failure names which component to
    act on instead of leaving a consumer to re-derive it from the vectors.
    Recorded on pass too (the §7.2 principle); an unconstrained axis is absent
    because an omitted claim has no status. Additive per §7.1."""
    expr: str | None = None
    operands: dict[str, Any] | None = None
    region: dict[str, Any] | None = None
    """The declared region and shell of a `keep_out` / `keep_in` check, so the
    report states what was claimed, not just how it went. Additive per §7.1."""
    hole: dict[str, Any] | None = None
    """The declared bore of a `hole_diameter` check — `{"d": ..., "count": ...}`
    — on the same principle as `region`. Additive per §7.1."""
    detail: str | None = None
    requires: str | None = None
    part_refs: tuple[str, ...] = ()
    """Parts this check read. Always the single part in v0; recorded anyway so
    assemblies can qualify claims up a tree later without a schema change."""

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "phase": self.phase,
            "status": str(self.status),
            "measurement": _measurement_json(self.measurement),
            "limit": _limit_json(self.limit),
        }
        if self.components is not None:
            out["components"] = {axis: str(s) for axis, s in self.components.items()}
        if self.expr is not None:
            out["expr"] = self.expr
            out["operands"] = self.operands or {}
        if self.region is not None:
            out["region"] = self.region
        if self.hole is not None:
            out["hole"] = self.hole
        out["detail"] = self.detail
        if self.requires is not None:
            out["requires"] = self.requires
        return out


@dataclass(slots=True)
class Report:
    """A single part's result. One report per part, never per invocation."""

    part_id: str
    contract: str
    tool_version: str
    contract_digest: str | None = None
    source: str | None = None
    source_digest: str | None = None
    source_closure: dict[str, Any] | None = None
    """Every source file the build reads, not just the entry point.

    `source_digest` covers one file. For an OpenSCAD part that is routinely a
    small fraction of the input — the gridfinity bin in the dogfood corpus is
    one of sixteen — so two builds can share a `source_digest` and be different
    parts. This closes that for the engine where it was demonstrated; see
    `SPEC-report.md` §8.3 for what it does and does not cover.
    """

    engine: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    geometry: dict[str, Any] = field(default_factory=dict)
    renders: dict[str, str] = field(default_factory=dict)
    """View name -> image path, relative to the report's own directory.

    Populated only when a run actually produced images (`check --render`);
    absent otherwise — never an empty block, and never an empty-string path
    that reads as a file (SPEC-report.md §8.4). The images carry no verdict.
    """
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None
    hint: str | None = None
    build_origin: str | None = None
    """Why a build failed, when one did: `"environment"` or `"model"`.

    A field rather than prose in `detail`, so a consumer can branch on it. A
    design that does not compile is a statement about the part; no engine on
    PATH is not, and reporting both as `builds: fail` told a CI run with no
    OpenSCAD installed that the design was disproven.
    """
    build_stderr: str | None = None
    """The engine's full stderr when a build failed — the unabridged version
    of `hint`, so a filtered hint can never lose the diagnosis (#37)."""
    duration_ms: int | None = None
    argv: list[str] = field(default_factory=list)

    IMPLICIT_KINDS = ("builds",)
    """Checks partspec adds itself. They are real results, but they are not
    something the author *asserted*, so they must not satisfy the emptiness
    test — see `verdict`."""

    @property
    def verdict(self) -> Verdict:
        """Verdict, with the vacuous-green guard applied to *declared* checks.

        `builds` is added by the tool, so a contract that asserts nothing still
        produces one passing check. Counting it toward emptiness would let the
        single most important guard in the tool be defeated by the tool itself:
        a contract with no claims would exit 0 and read as a proven part.
        """
        if self.error is not None:
            return Verdict.ERROR
        declared = [c for c in self.checks if c.kind not in self.IMPLICIT_KINDS]
        if not declared:
            return Verdict.EMPTY
        return verdict_of([c.status for c in self.checks])

    @property
    def exit_code(self) -> int:
        return exit_code(self.verdict)

    def counts(self) -> dict[str, int]:
        """Status tally. `total` equals len(checks) and the five statuses sum to it.

        Redundant by construction and emitted anyway: it is the cheapest signal
        that a contract lost checks between two runs.
        """
        tally = {s.value: 0 for s in Status}
        for c in self.checks:
            tally[c.status.value] += 1
        return {"total": len(self.checks), **tally}

    def to_json(self) -> dict[str, Any]:
        """Serialise in the field order the spec fixes (SPEC-report.md 8.1)."""
        part: dict[str, Any] = {"id": self.part_id, "contract": self.contract}
        if self.contract_digest:
            part["contract_digest"] = self.contract_digest
        if self.source:
            part["source"] = self.source
        if self.source_digest:
            part["source_digest"] = self.source_digest
        if self.source_closure:
            part["source_closure"] = self.source_closure

        doc: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": "partspec", "version": self.tool_version},
            "part": part,
            "engine": self.engine,
            "params": self.params,
            "geometry": self.geometry,
        }
        if self.renders:
            doc["renders"] = self.renders
        doc |= {
            "verdict": str(self.verdict),
            "counts": self.counts(),
            "checks": [c.to_json() for c in self.checks],
            "error": self.error,
            "hint": self.hint,
            "build_origin": self.build_origin,
            "build_stderr": self.build_stderr,
            "environment": self._environment(),
            "invocation": {"argv": self.argv},
        }
        return doc

    def _environment(self) -> dict[str, Any]:
        """Volatile data, quarantined by field rather than by block.

        Only `timestamp`, `duration_ms` and `platform` vary between two runs of
        identical inputs. `packages` deliberately does NOT — it is exactly what
        distinguishes "a dependency upgrade moved this number" from "the design
        changed", so a comparator that excludes the whole block loses the ability
        to explain its own findings.
        """
        env: dict[str, Any] = {
            "python": platform.python_version(),
            "packages": _installed_versions(),
            "platform": f"{sys.platform}-{platform.machine()}",
        }
        if self.duration_ms is not None:
            env["duration_ms"] = self.duration_ms
        return env

    def write(self, directory: Path) -> Path:
        return _write_json(directory / REPORT_FILENAME, self.to_json())


def _installed_versions() -> dict[str, str]:
    """Versions of the optional engine packages that are actually installed."""
    from importlib.metadata import PackageNotFoundError, version

    found: dict[str, str] = {}
    for name in ("build123d", "cadquery", "cadquery-ocp", "trimesh", "manifold3d"):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write atomically: temp file in the destination directory, then rename.

    A partially written report that happens to parse is worse than none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".partspec-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # allow_nan=False: a bare NaN/Infinity literal is not JSON and no
            # conforming parser will read it back. Measurement refuses
            # non-finite values already; this is the backstop that keeps an
            # unreadable artifact from ever reaching disk.
            json.dump(payload, fh, indent=2, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_placeholder(
    directory: Path, *, contract: str, argv: list[str], part_id: str = "unresolved"
) -> Path:
    """Write an `error` report BEFORE the engine is invoked.

    A try/finally cannot survive a native fault: an OCP segfault or an OOM kill
    takes the process down with no Python unwinding, leaving yesterday's
    `verdict: "pass"` sitting at a deterministic path where both a human and an
    agent will trust it. Writing this first means the worst case is a report
    saying the run died — never one saying the part was fine.

    Only the in-process OCCT tier is exposed to a native fault; OpenSCAD runs as
    a subprocess whose crash the parent observes normally. The placeholder is
    written regardless, because the cost is one file write.

    `part_id` defaults because this is written **before the contract is
    resolved**, and resolving is itself something that can fail: a contract that
    raises on import never produced a part id, and used to leave the previous
    run's report untouched for exactly that reason. A run that got far enough to
    name its part overwrites this with the real id.
    """
    payload = Report(
        part_id=part_id,
        contract=contract,
        tool_version=_tool_version(),
        argv=argv,
        error="run did not complete: no result was written for this run",
        hint="the contract failed to resolve, or the process died before finishing "
        "(a native segfault/OOM in the CAD kernel)",
    ).to_json()
    return _write_json(directory / REPORT_FILENAME, payload)


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("partspec")
    except PackageNotFoundError:  # running from a source tree without an install
        return "0.0.0+unknown"
