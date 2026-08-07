"""Run a contract against a part and produce a report.

The phase order and its consequences are the whole of this module:

    parameter checks -> (short-circuit?) -> build -> geometry checks -> report

A failing parameter check stops the engine from running, because building
geometry from inputs already known to be invalid wastes time and produces a
shape whose measurements describe something the contract has already rejected.
The geometry checks then appear as `skipped` rather than vanishing — an absent
check is indistinguishable from one that was never declared, which is the
vacuous-green failure wearing a different hat.

Spec: SPEC-report.md sections 4, 5, 6; SPEC-contract.md sections 4, 6.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Any

from . import expr as expr_mod
from .backend import BuildError, Unsupported
from .contract import GEOMETRY, GEOMETRY_KINDS, CheckSpec, Part
from .report import CheckResult, Report
from .status import ContractError, Limit, Measurement, Status, adjudicate

__all__ = ["run"]

_TOOL_VERSION_FALLBACK = "0.0.0+unknown"


def run(
    part: Part, *, out_dir: Path, argv: list[str] | None = None, contract_path: Path | None = None
) -> Report:
    """Evaluate every declared check and return the report."""
    started = time.perf_counter()
    report = Report(
        part_id=part.id,
        contract=_relative(contract_path, contract_path) if contract_path else "<in-memory>",
        tool_version=_tool_version(),
        contract_digest=_digest(contract_path),
        source=_relative(part.source.path, contract_path),
        source_digest=_digest(part.source.path),
        source_closure=_closure(part.source),
        params=dict(part.source.params),
        argv=argv or [],
    )

    try:
        _evaluate(part, report, out_dir, contract_path)
    except ContractError as exc:
        # A malformed question has no answer: every declared check is reported
        # as skipped rather than failed, and the verdict is error.
        report.error = f"{type(exc).__name__}: {exc}"
        report.hint = "the contract is wrong, not the part"
        report.checks = [
            _skipped(spec, "not evaluated: the contract raised") for spec in _all_specs(part)
        ]

    report.duration_ms = int((time.perf_counter() - started) * 1000)
    return report


# --------------------------------------------------------------------------


def _evaluate(part: Part, report: Report, out_dir: Path, contract_path: Path | None = None) -> None:
    parameter_specs = [s for s in part.checks if s.phase != GEOMETRY]
    geometry_specs = [s for s in part.checks if s.phase == GEOMETRY]

    results = [_run_parameter_check(spec, part.source.params) for spec in parameter_specs]

    blocker = next((r for r in results if r.status is Status.FAIL), None)
    if blocker is not None:
        reason = f"not evaluated: parameter check {blocker.id!r} failed"
        results.append(_skipped(_builds_spec(), reason))
        results.extend(_skipped(spec, reason) for spec in geometry_specs)
        report.checks = results
        return

    backend = _backend_for(part.source.engine)
    report.engine = {
        "kind": part.source.engine,
        "version": backend.engine_version,
        "backend": backend.kind,
        "adopted_via": "wrapped" if part.source.engine == "cadquery" else None,
    }
    if part.source.backend:
        # Recorded because it changes the artifact: the same source rendered by
        # Manifold and by CGAL differ in mesh validity, not just in speed.
        report.engine["render_backend"] = part.source.backend

    artifact = backend.build(_engine_source(part), out_dir)
    if isinstance(artifact, BuildError):
        report.hint = artifact.hint
        report.build_origin = artifact.origin

        if artifact.origin == "environment":
            # Not a statement about the part. No engine on PATH, a mistyped pin,
            # a missing package, an absent source, a render out of time -- none
            # of these disprove anything, and reporting them as `builds: fail`
            # made a CI run on a machine without OpenSCAD say the *design* was
            # disproven. `builds` is not emitted as failing at all; every
            # declared check is skipped and the verdict is `error`.
            report.error = artifact.message
            reason = f"not evaluated: {artifact.message}"
            results.append(_skipped(_builds_spec(), reason))
            results.extend(_skipped(spec, reason) for spec in geometry_specs)
            report.checks = results
            return

        results.append(
            CheckResult(
                id="builds",
                kind="builds",
                phase=GEOMETRY,
                status=Status.FAIL,
                detail=artifact.message,
                part_refs=(part.id,),
            )
        )
        results.extend(
            _skipped(spec, "not evaluated: the part did not build") for spec in geometry_specs
        )
        report.checks = results
        return

    # After the build, not before: a Python model's imports are only knowable
    # once it has run, and helpers imported lazily inside the factory would be
    # invisible to a snapshot taken any earlier.
    if part.source.engine != "openscad":
        report.source_closure = _python_closure(part.source, contract_path)

    results.append(
        CheckResult(
            id="builds", kind="builds", phase=GEOMETRY, status=Status.PASS, part_refs=(part.id,)
        )
    )
    report.geometry = backend.provenance(artifact)
    results.extend(_run_geometry_check(spec, backend, artifact, part.id) for spec in geometry_specs)
    report.checks = results


def _run_parameter_check(spec: CheckSpec, params: dict[str, Any]) -> CheckResult:
    if spec.kind == "requires":
        assert spec.expr is not None
        ok, operands = expr_mod.evaluate(spec.expr, params)
        return CheckResult(
            id=spec.id,
            kind=spec.kind,
            phase=spec.phase,
            status=Status.PASS if ok else Status.FAIL,
            expr=spec.expr,
            operands=operands,
            detail=None if ok else expr_mod.describe(spec.expr, operands),
        )

    if spec.kind == "param_range":
        assert spec.expr is not None and spec.limit is not None
        value = params[spec.expr]
        measurement = Measurement(value, spec.unit or _unit_for(value), exact=True)
        status = adjudicate(measurement, spec.limit)
        return CheckResult(
            id=spec.id,
            kind=spec.kind,
            phase=spec.phase,
            status=status,
            measurement=measurement,
            limit=spec.limit,
            detail=None
            if status is Status.PASS
            else f"{spec.expr}={value!r} outside {_render(spec.limit)}",
        )

    raise ContractError(f"unknown parameter check kind: {spec.kind!r}")


def _run_geometry_check(spec: CheckSpec, backend: Any, artifact: Any, part_id: str) -> CheckResult:
    primitive_name = GEOMETRY_KINDS.get(spec.kind)
    if primitive_name is None:
        raise ContractError(f"unknown geometry check kind: {spec.kind!r}")

    common = {
        "id": spec.id,
        "kind": spec.kind,
        "phase": spec.phase,
        "limit": spec.limit,
        "part_refs": (part_id,),
    }

    # Capability is static and consulted first, so an unanswerable check costs
    # nothing to report.
    if primitive_name not in backend.capabilities():
        return CheckResult(
            **common,
            status=Status.UNSUPPORTED,
            detail=f"the {backend.kind} backend cannot evaluate {spec.kind}",
            requires="occt",
        )

    outcome = getattr(backend, primitive_name)(artifact)
    if isinstance(outcome, Unsupported):
        return CheckResult(
            **common, status=Status.UNSUPPORTED, detail=outcome.reason, requires=outcome.requires
        )

    assert spec.limit is not None
    status = adjudicate(outcome, spec.limit)
    detail = None
    if status is Status.FAIL:
        explain = getattr(backend, f"{spec.kind}_detail", None)
        if explain is not None:
            detail = explain(artifact)
    return CheckResult(**common, status=status, measurement=outcome, detail=detail)


# --------------------------------------------------------------------------


def _backend_for(engine: str) -> Any:
    if engine == "openscad":
        from .backends.mesh import MeshBackend

        return MeshBackend()
    if engine in ("build123d", "cadquery"):
        from .backends.occt import OcctBackend

        return OcctBackend(engine)
    raise ContractError(f"unknown engine: {engine!r}")


def _engine_source(part: Part) -> Any:
    if part.source.engine == "openscad":
        from .engines.openscad import OpenSCADSource

        return OpenSCADSource(
            path=part.source.path,
            params=part.source.params,
            method=part.source.method,
            backend=part.source.backend,
        )

    from .engines.pycad import PyCADSource

    return PyCADSource(
        path=part.source.path,
        engine=part.source.engine,
        params=part.source.params,
        method=part.source.method,
    )


def _builds_spec() -> CheckSpec:
    return CheckSpec(id="builds", kind="builds", phase=GEOMETRY)


def _all_specs(part: Part) -> list[CheckSpec]:
    return [*part.checks, _builds_spec()]


def _skipped(spec: CheckSpec, reason: str) -> CheckResult:
    return CheckResult(
        id=spec.id,
        kind=spec.kind,
        phase=spec.phase,
        status=Status.SKIPPED,
        limit=spec.limit,
        expr=spec.expr if spec.kind == "requires" else None,
        operands={} if spec.kind == "requires" else None,
        detail=reason,
    )


def _relative(path: Path | None, contract_path: Path | None) -> str:
    """A path expressed against the contract's directory, POSIX-separated.

    `part.source` was absolute after `_anchor` resolved it, so the committed
    example report leaked a developer home directory -- and two checkouts of the
    same tree at different locations produced different reports. That undoes at
    the path layer exactly the machine-independence `source_closure` was built
    to have: "a comparator's whole purpose is comparing runs from CI and a
    laptop".

    The contract's directory is the frame `_anchor` already resolves against, so
    this round-trips with no new concept. A source outside that subtree stays
    absolute and says so, rather than emitting a `../../..` chain that is no more
    portable and much harder to read.
    """
    if path is None:
        return ""
    if contract_path is None:
        return path.as_posix()
    base = contract_path.resolve().parent
    resolved = path.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return resolved.as_posix()


def _unit_for(value: Any) -> str:
    """Deliberately not inferred from the Python literal type.

    It used to be: `bool` and `int` gave "count", `float` gave "mm". So
    `plate_x=40` and `plate_y=30.0` came out as `count` and `mm` in the same
    report, on the same plate, and editing a declared parameter from `40` to
    `40.0` changed the recorded unit without changing the design -- the exact
    spurious drift SPEC-report.md 7.2 exists to keep out.

    No verdict was ever wrong (`adjudicate` never reads `unit`). What makes it
    worth fixing before the tag rather than after is that `schema_version: 1`
    freezes `measurement.unit` as a compatibility surface.

    v0 has one length unit, so `mm` is the default and a genuine count is
    declared with `p.param(..., unit="count")`.
    """
    return "mm"


def _render(limit: Limit) -> str:
    parts = []
    if limit.min is not None:
        parts.append(f"min={limit.min}")
    if limit.max is not None:
        parts.append(f"max={limit.max}")
    if limit.equals is not None:
        parts.append(f"equals={limit.equals}")
    return ", ".join(parts)


def _digest(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _python_closure(source: Any, contract_path: Path | None) -> dict[str, Any]:
    """The local modules a Python model actually imported.

    Scoped to the model's own directory, which is not an arbitrary boundary:
    `engines/pycad.py` puts exactly that directory on `sys.path` before exec'ing
    the model, precisely so a model can import helpers beside it. Those helpers
    are build inputs by design, and until now nothing recorded them — editing
    one changed the part and left `source_digest` identical, which is F13's
    failure class on the tier where it had not been closed.

    Read from `sys.modules` rather than parsed, so it reports what was imported
    instead of what appears importable. The contract file is excluded: it is
    already `contract_digest`, and folding it in here would make the *source*
    closure move whenever a claim changed.

    `partial` is unconditional. Python can import from anywhere on `sys.path`,
    read data files at runtime and load C extensions, none of which this sees.
    An earlier draft of `SPEC-report.md` §8.3 concluded that this uncertainty
    argued for emitting nothing at all. That was the wrong call: silence is not
    the absence of a claim here, because `source_digest` is still sitting in the
    report asserting that one file identifies the build. A `partial` closure is
    the shape the spec already defines for known-incomplete coverage, and it
    makes a comparator treat sameness as inconclusive rather than proven.
    """
    root = source.path.resolve().parent
    excluded = {contract_path.resolve()} if contract_path is not None else set()

    members: set[Path] = set()
    for module in list(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path in excluded or not path.is_relative_to(root) or not path.is_file():
            continue
        members.add(path)

    hashes = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in members)
    return {
        "digest": "sha256:" + hashlib.sha256("".join(hashes).encode()).hexdigest(),
        "files": len(hashes),
        "scope": "model_directory",
        "partial": True,
    }


def _closure(source: Any) -> dict[str, Any] | None:
    """Digest every file the build reads, not just the entry point.

    OpenSCAD only — the Python tier is handled after its build, by
    `_python_closure`, because its imports are not knowable until the model has
    run.

    The digest is over **content hashes, sorted** — not over paths — so it is
    identical on two machines that check the same tree out at different
    locations. A comparator's whole purpose is comparing runs from CI and a
    laptop, and a path-sensitive digest would differ on every one of them.
    """
    if source.engine != "openscad" or not source.path.is_file():
        return None

    from .engines.openscad import include_closure

    closure = include_closure(source.path)
    members = sorted(
        hashlib.sha256(f.read_bytes()).hexdigest() for f in closure.files if f.is_file()
    )
    out: dict[str, Any] = {
        "digest": "sha256:" + hashlib.sha256("".join(members).encode()).hexdigest(),
        "files": len(members),
    }
    if closure.unresolved:
        out["unresolved"] = list(closure.unresolved)
    if closure.reads_external_data:
        out["reads_external_data"] = True
    if closure.partial:
        # Stated positively so a consumer cannot mistake absence of the two
        # fields above for a guarantee it never made.
        out["partial"] = True
    return out


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("partspec")
    except PackageNotFoundError:
        return _TOOL_VERSION_FALLBACK
