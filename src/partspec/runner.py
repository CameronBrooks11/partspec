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
from .status import (
    ContractError,
    Limit,
    Measurement,
    Status,
    adjudicate,
    adjudicate_components,
    component_limit,
    epsilon,
)

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
    report.engine = engine_block(part, backend)

    artifact = backend.build(_engine_source(part), out_dir)
    if isinstance(artifact, BuildError):
        report.hint = artifact.hint
        report.build_origin = artifact.origin
        report.build_stderr = artifact.stderr

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


def engine_block(part: Part, backend: Any) -> dict[str, Any]:
    """The engine provenance block, in the exact section-7 order.

    One constructor, used by `check` here and by the `measure` verb — the two
    had already drifted apart (#73: measure emitted kind/backend/version in
    the wrong order and omitted everything below it). Field notes:

    - `render_backend` is always present, pinned string or null — the
      unpinned run is exactly the one whose backend a reader cannot infer,
      because the engine default varies by version (CGAL on 2021.01, Manifold
      on current builds) and F10 is a mesh-validity difference between them
      (#41). Null means "the default, whichever this version chose".
    - `method` is always present, mirroring adopted_via: null states "the
      default entry", not "unrecorded" (#40). On OpenSCAD, `param_mode` says
      how parameters reached the geometry, and on the call path
      `source_rendered: "derived"` records that the engine's entry was a
      derived scratch, not the digested file.
    """
    block: dict[str, Any] = {
        "kind": part.source.engine,
        "version": backend.engine_version,
        "backend": backend.kind,
        "render_backend": part.source.backend,
        "adopted_via": "wrapped" if part.source.engine == "cadquery" else None,
        "method": part.source.method,
    }
    if part.source.engine == "openscad":
        block["param_mode"] = "call" if part.source.method else "define"
        if part.source.method:
            block["source_rendered"] = "derived"
    return block


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

    common: dict[str, Any] = {
        "id": spec.id,
        "kind": spec.kind,
        "phase": spec.phase,
        "limit": spec.limit,
        "part_refs": (part_id,),
    }
    if spec.region is not None:
        # Attached before any early return: a refusal must still state what was
        # claimed, or the reader cannot judge what went unanswered.
        common["region"] = {**spec.region.to_json(), "shell": spec.shell}
    if spec.hole is not None:
        common["hole"] = dict(spec.hole)

    # Capability is static and consulted first, so an unanswerable check costs
    # nothing to report. `requires` names the tier that would answer; for the
    # region kinds both tiers declare the primitive, so a backend without it
    # implies no tier and the field stays absent.
    if primitive_name not in backend.capabilities():
        return CheckResult(
            **common,
            status=Status.UNSUPPORTED,
            detail=f"the {backend.kind} backend cannot evaluate {spec.kind}",
            requires="occt" if spec.region is None else None,
        )

    if spec.kind in ("keep_out", "keep_in"):
        return _run_region_check(spec, backend, artifact, common)
    if spec.kind == "hole_diameter":
        return _run_hole_check(spec, backend, artifact, common)
    if spec.kind == "bolt_circle":
        return _run_bolt_circle_check(spec, backend, artifact, common)
    if spec.kind == "fillet_radius":
        return _run_fillet_check(spec, backend, artifact, common)

    outcome = getattr(backend, primitive_name)(artifact)
    if isinstance(outcome, Unsupported):
        return CheckResult(
            **common, status=Status.UNSUPPORTED, detail=outcome.reason, requires=outcome.requires
        )

    assert spec.limit is not None
    status = adjudicate(outcome, spec.limit)
    components = _components_of(outcome, spec.limit)
    detail = None
    if status is Status.FAIL:
        explain = getattr(backend, f"{spec.kind}_detail", None)
        if explain is not None:
            detail = explain(artifact)
        elif components is not None:
            detail = _failing_axes(outcome, spec.limit, components)
    return CheckResult(
        **common, status=status, measurement=outcome, components=components, detail=detail
    )


def _components_of(outcome: Measurement, limit: Limit) -> dict[str, Status] | None:
    """Axis -> status for a vector measurement; None for scalars.

    Derived from the same `adjudicate_components` call that `adjudicate` folds,
    never recomputed by other means — two adjudications of one claim is one
    adjudication too many.
    """
    if not outcome.is_vector or outcome.axes is None:
        return None
    per = adjudicate_components(outcome, limit)
    return {axis: s for axis, s in zip(outcome.axes, per, strict=True) if s is not None}


def _failing_axes(outcome: Measurement, limit: Limit, components: dict[str, Status]) -> str:
    """Name each non-passing axis with its value and the bound it broke —
    the difference between a report an agent can act on in one edit and one
    it must bisect."""
    values = dict(zip(outcome.axes or (), tuple(outcome.value), strict=True))
    n = len(tuple(outcome.value))
    axis_index = {axis: i for i, axis in enumerate(outcome.axes or ())}
    parts = []
    for axis, status in components.items():
        # Only conclusive violations: "outside" is a claim, and an APPROXIMATE
        # axis is one the tool does not know to be outside. No backend emits
        # vector bounds today, but the message must not be a lie waiting for
        # the first one that does.
        if status is not Status.FAIL:
            continue
        sub = component_limit(limit, axis_index[axis], n)
        assert sub is not None  # a constrained status implies a constraint
        parts.append(f"{axis}={values[axis]:g} outside {_render(sub)}")
    return "; ".join(parts)


def _run_hole_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate a hole_diameter claim: exactly N detected bores in the band.

    The measurement is the matched diameters themselves, not the count — the
    count is derivable from the vector's length, and the diameters are what a
    comparator tracks drift on when an author uses a real tolerance band. No
    match measured nothing for this claim, so `measurement` is null and the
    detail carries the full bore inventory instead.
    """
    assert spec.limit is not None and spec.hole is not None
    outcome = backend.bores(artifact)
    if isinstance(outcome, Unsupported):
        return CheckResult(
            **common, status=Status.UNSUPPORTED, detail=outcome.reason, requires=outcome.requires
        )

    all_bores = tuple(float(x) for x in outcome.value)
    lo, hi = spec.limit.min, spec.limit.max
    # Plain interval membership: the band IS the tolerance, already widened by
    # the author's tol or the comparison epsilon at declaration. Applying
    # epsilon again here would tolerance the tolerance.
    matched = tuple(x for x in all_bores if lo <= x <= hi)
    expected = int(spec.hole["count"])

    measurement = None
    if matched:
        measurement = Measurement(
            matched,
            "mm",
            exact=True,
            axes=tuple(f"bore_{i + 1}" for i in range(len(matched))),
        )
    detail = None
    if len(matched) != expected:
        # :.9g, not :g — a tight band rendered as "[8, 8]" reads as an empty
        # interval and hides exactly the sub-micrometre disagreement a tight
        # tol exists to surface.
        inventory = ", ".join(f"Ø{x:.9g}" for x in all_bores) if all_bores else "none"
        detail = (
            f"found {len(matched)} bore(s) with diameter in [{lo:.9g}, {hi:.9g}] mm, "
            f"expected {expected}; bores on this part: {inventory}"
        )
    return CheckResult(
        **common,
        status=Status.PASS if len(matched) == expected else Status.FAIL,
        measurement=measurement,
        detail=detail,
    )


def _run_fillet_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate every blend radius against the bounds — the one bespoke rule
    is the empty set. "Every blend is within bounds" over zero blends is
    vacuously true, and vacuous truth is the green this tool exists to refuse:
    a part with no blends FAILS the check rather than passing it
    (SPEC-contract.md 4.7)."""
    assert spec.limit is not None
    outcome = backend.blend_radii(artifact)
    if isinstance(outcome, Unsupported):
        return CheckResult(
            **common, status=Status.UNSUPPORTED, detail=outcome.reason, requires=outcome.requires
        )
    if not outcome.value:
        return CheckResult(
            **common,
            status=Status.FAIL,
            detail="no blend surfaces exist on this part; a claim about every blend "
            "needs at least one, and passing over an empty set would be vacuous green",
        )
    status = adjudicate(outcome, spec.limit)
    components = _components_of(outcome, spec.limit)
    detail = None
    if status is Status.FAIL and components is not None:
        detail = _failing_axes(outcome, spec.limit, components)
    return CheckResult(
        **common, status=status, measurement=outcome, components=components, detail=detail
    )


_BOLT_CIRCLE_SEARCH_CAP = 60
"""Candidate bores per direction group before the triple search is refused.
C(60,3) ≈ 34k circumcircles is cheap; a part with more same-diameter parallel
bores than that deserves an honest refusal over an unbounded search."""


def _run_bolt_circle_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Exactly `count` matching bores, axes parallel, concyclic at `bcd`.

    Subset semantics (SPEC-contract.md 4.6): the claim is that such a circle
    EXISTS, searched over every subset of candidate bores — an unrelated hole
    elsewhere must not break it, and a fifth hole on the claimed circle must.
    Every valid circle through >= 3 points is determined by 3 of its members,
    so searching triples finds it without enumerating subsets.
    """
    assert spec.limit is not None and spec.hole is not None
    table = backend.bore_table(artifact)
    if isinstance(table, Unsupported):
        return CheckResult(
            **common, status=Status.UNSUPPORTED, detail=table.reason, requires=table.requires
        )

    d, count, bcd = spec.hole["d"], int(spec.hole["count"]), spec.hole["bcd"]
    lo, hi = spec.limit.min, spec.limit.max
    band = hi - bcd
    candidates = [b for b in table if abs(b["d"] - d) <= epsilon(d)]

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for bore in candidates:
        groups.setdefault(tuple(round(c, 6) for c in bore["direction"]), []).append(bore)

    fitted, best = None, None  # best: (members_found, circle_diameter) for the detail
    capped = 0
    for group in groups.values():
        if len(group) < count:
            continue
        if len(group) > _BOLT_CIRCLE_SEARCH_CAP:
            # Noted, not returned: a passing circle in another direction group
            # must still be found — the refusal is only the outcome when the
            # whole search ends empty-handed with part of it unexamined.
            capped = max(capped, len(group))
            continue
        points = _plane_coordinates(group)
        fitted, best = _find_circle(points, count, bcd, band, lo, hi, best)
        if fitted is not None:
            break

    if fitted is not None:
        return CheckResult(
            **common, status=Status.PASS, measurement=Measurement(fitted, "mm", exact=True)
        )
    if capped:
        return CheckResult(
            **common,
            status=Status.UNSUPPORTED,
            detail=f"{capped} candidate bores share one axis direction; refusing to "
            f"search beyond {_BOLT_CIRCLE_SEARCH_CAP} rather than answer slowly and "
            f"claim it was exhaustive",
        )
    if best is not None:
        found, circle_d = best
        near = f"; the nearest circle of Ø{circle_d:.9g} holds {found} of them"
    else:
        near = ""
    return CheckResult(
        **common,
        status=Status.FAIL,
        detail=f"no circle of Ø{bcd:.9g} (±{band:.9g}) holds exactly {count} parallel "
        f"bores of Ø{d:g}; {len(candidates)} candidate bore(s) on this part{near}",
    )


def _plane_coordinates(group: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Project each bore centre onto the plane perpendicular to the shared axis."""
    dx, dy, dz = group[0]["direction"]
    # Any vector not parallel to the axis seeds the basis.
    ax, ay, az = (1.0, 0.0, 0.0) if abs(dx) < 0.9 else (0.0, 1.0, 0.0)
    ux, uy, uz = dy * az - dz * ay, dz * ax - dx * az, dx * ay - dy * ax
    norm = (ux * ux + uy * uy + uz * uz) ** 0.5
    ux, uy, uz = ux / norm, uy / norm, uz / norm
    vx, vy, vz = dy * uz - dz * uy, dz * ux - dx * uz, dx * uy - dy * ux
    return [
        (cx * ux + cy * uy + cz * uz, cx * vx + cy * vy + cz * vz)
        for cx, cy, cz in (bore["center"] for bore in group)
    ]


def _find_circle(
    points: list[tuple[float, float]],
    count: int,
    bcd: float,
    band: float,
    lo: float,
    hi: float,
    best: tuple[int, float] | None,
) -> tuple[float | None, tuple[int, float] | None]:
    """Search for a circle of ~bcd holding exactly `count` points.

    Triples only SEED the search: three points determine a circle exactly, but
    band membership is a claim about the *pattern* circle, and a raw
    circumcentre of perturbed points shifts by ~2x the perturbation — enough
    to eject a conforming fourth hole from a band it genuinely sits in (PR #89
    review, blocker 1). Each seed therefore captures loosely (2x band),
    refits the centre by least squares over the capture, and only then
    adjudicates strictly against the refitted centre. Exactness is judged
    against that fitted pattern circle, never against a seed's own centre.

    Returns (fitted diameter or None, best near-miss for the failure detail).
    """
    import itertools
    import math

    def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    if count == 2:
        # Two bolts on a BCD sit diametrically opposite: the circle claim
        # collapses to centre distance == bcd. The closest in-band pair is the
        # measurement — the first found would make the recorded value depend
        # on face-iteration order.
        closest = None
        for a, b in itertools.combinations(points, 2):
            separation = dist(a, b)
            if closest is None or abs(separation - bcd) < abs(closest - bcd):
                closest = separation
        if closest is not None and lo <= closest <= hi:
            return closest, best
        if closest is not None:
            best = (2, closest) if best is None or abs(closest - bcd) < abs(best[1] - bcd) else best
        return None, best

    for triple in itertools.combinations(points, 3):
        centre = _circumcentre(*triple)
        if centre is None:
            continue  # collinear
        if any(abs(2 * dist(centre, p) - bcd) > 2 * band for p in triple):
            continue  # a seed nowhere near the claimed radius cannot converge to it
        for _ in range(8):
            capture = [p for p in points if abs(2 * dist(centre, p) - bcd) <= 2 * band]
            if len(capture) < 3:
                break
            refit = _fit_centre(capture)
            if refit is None or dist(refit, centre) < 1e-12:
                break
            centre = refit
        members = [p for p in points if abs(2 * dist(centre, p) - bcd) <= band]
        if not members:
            continue
        circle_d = 2 * sum(dist(centre, p) for p in members) / len(members)
        if len(members) == count and lo <= circle_d <= hi:
            return circle_d, best
        if best is None or abs(len(members) - count) < abs(best[0] - count):
            best = (len(members), circle_d)
    return None, best


def _fit_centre(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Algebraic least-squares circle centre (Kåsa fit) — linear, stdlib-only."""
    n = len(points)
    sx = sum(p[0] for p in points) / n
    sy = sum(p[1] for p in points) / n
    # Centre the data first: the normal equations are ill-conditioned far
    # from the origin, and bore coordinates routinely sit at ~1e2.
    u = [p[0] - sx for p in points]
    v = [p[1] - sy for p in points]
    suu = sum(a * a for a in u)
    svv = sum(a * a for a in v)
    suv = sum(a * b for a, b in zip(u, v, strict=True))
    suuu = sum(a * a * a for a in u)
    svvv = sum(a * a * a for a in v)
    suvv = sum(a * b * b for a, b in zip(u, v, strict=True))
    svuu = sum(b * a * a for a, b in zip(u, v, strict=True))
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None  # collinear
    cu = ((suuu + suvv) * svv - (svvv + svuu) * suv) / (2 * det)
    cv = ((svvv + svuu) * suu - (suuu + suvv) * suv) / (2 * det)
    return (cu + sx, cv + sy)


def _circumcentre(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> tuple[float, float] | None:
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = (
        a[0] * a[0] + a[1] * a[1],
        b[0] * b[0] + b[1] * b[1],
        c[0] * c[0] + c[1] * c[1],
    )
    return (
        (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d,
        (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d,
    )


def _run_region_check(
    spec: CheckSpec, backend: Any, artifact: Any, common: dict[str, Any]
) -> CheckResult:
    """Adjudicate a keep_out / keep_in region with its verification shell.

    The core claim and its anti-vacuity guard are decided together
    (SPEC-contract.md 4.4): a keep_out's region must hold no material AND its
    shell must not be entirely empty; a keep_in's region must be entirely
    material AND its shell must not be entirely solid. The pairing is what makes
    a deleted part fail a keep_out and a solid brick fail a keep_in.

    Every volume — including the region's own — is read through
    `intersect_volume`, never from a closed form. The mesh tier's booleans run
    on a float32 reconstruction (see `_manifold`), so a float64 closed-form
    total would disagree with a measured coverage by ~2e-7 relative — above the
    1e-7 comparison epsilon — and a fully-covered keep_in could fail on
    quantisation it did not cause. Measured against itself, the reconstruction
    cancels.
    """
    assert spec.region is not None and spec.shell is not None
    region = spec.region
    outer = region.expand(spec.shell)

    region_solid = backend.region_solid(region)
    outer_solid = backend.region_solid(outer)
    volumes = []
    for a, b in (
        (artifact, region_solid),
        (artifact, outer_solid),
        (region_solid, region_solid),
        (outer_solid, outer_solid),
    ):
        outcome = backend.intersect_volume(a, b)
        if isinstance(outcome, Unsupported):
            return CheckResult(
                **common,
                status=Status.UNSUPPORTED,
                detail=outcome.reason,
                requires=outcome.requires,
            )
        volumes.append(float(outcome.value))
    in_region, in_outer, region_volume, outer_volume = volumes
    in_shell = max(0.0, in_outer - in_region)

    # Each clause's message describes only what that clause measured. The two
    # are independent and can fail together (a lone crumb of material inside
    # the region of an otherwise-deleted part fails both), so a message that
    # asserted the other clause's state would be false exactly on the worst
    # parts.
    if spec.kind == "keep_out":
        failures = [
            f"{in_region:.6g} mm3 of material intrudes into the keep-out region"
            if in_region > epsilon(0.0)
            else None,
            f"no material lies within the {spec.shell:g} mm shell around the "
            f"region — an absent part satisfies the bare emptiness claim, so an "
            f"empty region alone is not evidence the feature exists"
            if not in_shell > epsilon(0.0)
            else None,
        ]
    else:
        deficit = region_volume - in_region
        shell_volume = max(0.0, outer_volume - region_volume)
        failures = [
            f"the region is missing {deficit:.6g} mm3 of the {region_volume:.6g} mm3 "
            f"of material it must contain"
            if deficit > epsilon(region_volume)
            else None,
            f"the entire {spec.shell:g} mm shell around the region is solid — an "
            f"unbounded block satisfies the bare solidity claim; nothing bounds "
            f"the feature this region describes"
            if not shell_volume - in_shell > epsilon(shell_volume)
            else None,
        ]

    failed = [f for f in failures if f is not None]
    return CheckResult(
        **common,
        status=Status.FAIL if failed else Status.PASS,
        measurement=Measurement((in_region, in_shell), "mm3", exact=True, axes=("region", "shell")),
        # The two clauses are this check's components, same shape as an
        # envelope's axes: the reader learns which side failed without parsing
        # the prose.
        components={
            "region": Status.FAIL if failures[0] is not None else Status.PASS,
            "shell": Status.FAIL if failures[1] is not None else Status.PASS,
        },
        detail="; ".join(failed) if failed else None,
    )


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
        region={**spec.region.to_json(), "shell": spec.shell} if spec.region is not None else None,
        hole=dict(spec.hole) if spec.hole is not None else None,
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
