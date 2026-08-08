"""Command-line entry point.

CLI first, MCP later (D5) — and the reason matters: the real contract is the
report schema plus the exit code, not the verbs. If `check` printed prose for
humans, an MCP layer would become a parser and the tool would be built twice.
With machine-readable output first, MCP is a thin adapter and `diff`, CI
annotations and a scorecard all fall out of the same artifact.

argparse rather than a CLI framework: a handful of subcommands does not justify a
dependency, and the core package is deliberately stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path

from .backend import DEFAULT_TIMEOUT_S, effective_timeout
from .contract import Part
from .report import write_placeholder
from .runner import run
from .status import EXIT_USAGE, Status, Verdict, exit_code
from .target import Target, TargetError, resolve

__all__ = ["main"]

ENV_TIMEOUT = "PARTSPEC_TIMEOUT"
MAX_TIMEOUT_S = 1e8  # ~3 years; anything past this is "unbounded", said honestly


def _timeout_arg(text: str) -> float:
    """argparse type for --timeout: seconds >= 0, where 0 waives the bound."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(
            f"the budget must be a finite number of seconds >= 0 (0 waives it), got {text}"
        )
    if value > MAX_TIMEOUT_S:
        # setitimer overflows platform time_t far above this; refused here so
        # the failure is a usage message, not a traceback from the timer.
        raise argparse.ArgumentTypeError(
            f"a budget over {MAX_TIMEOUT_S:g}s is not a budget; use --timeout 0 to waive it"
        )
    return value


class _TimeoutUsage(Exception):
    """PARTSPEC_TIMEOUT holds something that is not a budget."""


def _timeout_s(explicit: float | None) -> float:
    """Resolve the run's build budget: flag, then environment, then default.

    Fully resolved here — never left implicit — so `invocation.timeout_s`
    always names the budget that actually governed a CLI run, including the
    default; a run stopped by a budget nobody typed must still be attributable
    to it from the artifact alone. A garbage `PARTSPEC_TIMEOUT` raises
    `_TimeoutUsage` rather than being silently ignored, because a
    machine-level bound that quietly stopped applying is the unbounded run
    wearing a configured one's clothes.
    """
    if explicit is not None:
        return explicit
    raw = os.environ.get(ENV_TIMEOUT)
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_S
    try:
        return _timeout_arg(raw)
    except argparse.ArgumentTypeError as exc:
        raise _TimeoutUsage(f"{ENV_TIMEOUT} is unusable: {exc}") from None


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("partspec")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partspec",
        description="Verify CAD-as-code parts against declared engineering intent.",
    )
    parser.add_argument("--version", action="version", version=f"partspec {_version()}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    check = sub.add_parser("check", help="build parts and check them against their contracts")
    check.add_argument(
        "targets",
        nargs="+",
        metavar="target",
        help="<module-path>[:<factory>] — several targets share one process, "
        "one report each, exit by the worst verdict",
    )
    check.add_argument("--out", type=Path, default=None, help="report directory")
    check.add_argument("--quiet", action="store_true", help="suppress the human summary")
    check.add_argument(
        "--render",
        action="store_true",
        help="also write the canonical views and record their paths in the report",
    )
    check.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )
    pin_group = check.add_mutually_exclusive_group()
    pin_group.add_argument(
        "--expect",
        type=Path,
        default=None,
        metavar="LOCK",
        help="fail (error, exit 4) unless the declared claims match this pin exactly",
    )
    pin_group.add_argument(
        "--pin",
        type=Path,
        default=None,
        metavar="LOCK",
        help="write the declared claims to this pin file, then check normally",
    )

    measure = sub.add_parser(
        "measure",
        help="dump every quantity the backend can honestly produce (no verdict)",
    )
    measure.add_argument("target", help="<module-path>[:<factory>]")
    measure.add_argument("--out", type=Path, default=None)
    measure.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )

    render = sub.add_parser(
        "render",
        help="write the canonical views (iso, front, top, right) as PNGs — no verdict",
    )
    render.add_argument("target", help="<module-path>[:<factory>]")
    render.add_argument("--out", type=Path, default=None)
    render.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )

    diff = sub.add_parser(
        "diff",
        help="compare two reports of one part semantically (exit 0 identical, "
        "1 different, 2 indeterminate)",
    )
    diff.add_argument("old", type=Path, help="the earlier report.json")
    diff.add_argument("new", type=Path, help="the later report.json")

    return parser


def _out_dir(target_spec: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    target = Target.parse(target_spec)
    return target.path.resolve().parent / "outputs" / target.slug


def _resolve_or_report(spec: str) -> tuple[Part, Target] | int:
    """Resolve a target, turning any failure into an exit code rather than a
    traceback.

    The second clause is the load-bearing one. A contract is Python, so it can
    raise anything — a typo in a keyword argument raises `TypeError` — and an
    uncaught exception leaves the interpreter exiting **1**, which is this
    tool's code for *the part failed its contract*. A broken question would
    report as a wrong answer, and in CI the two are indistinguishable. It is
    `EXIT_ERROR` for the same reason a `ContractError` raised during a run is:
    nothing was evaluated, so nothing may be said about the part.

    Resolution is also snapshot for the model-module registry: a CONTRACT that
    imports a helper beside the model puts it into `sys.modules` before the
    build's own snapshot, and PR #104's review reproduced POST-V0 §8's
    stale-helper build through exactly that path. Recording resolve-time
    additions against the model's directory closes it.
    """
    modules_before = set(sys.modules)
    try:
        part, target = resolve(spec)
        if part.source.engine != "openscad":
            from .engines.pycad import record_model_modules

            record_model_modules(part.source.path, modules_before)
        return part, target
    except TargetError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\npartspec: interrupted", file=sys.stderr)
        return 130
    except BaseException as exc:  # noqa: BLE001 - a contract may raise anything
        # BaseException, not Exception. A contract calling `sys.exit(0)` raises
        # SystemExit, which sailed past an `except Exception` and exited the
        # process **0** -- green, silent, zero checks evaluated. Worse, the code
        # was the contract's to choose: `sys.exit(2)` read as `incomplete` and
        # `sys.exit(3)` as `empty`. No exit code from user code may become a
        # partspec verdict. Scoped to resolution, so argparse's own SystemExit
        # (`--version`, a usage error) is untouched.
        traceback.print_exc()
        print(f"\npartspec: the contract raised {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  the contract is wrong, not the part", file=sys.stderr)
        return exit_code(Verdict.ERROR)


_EXIT_PRECEDENCE = (130, EXIT_USAGE, 4, 3, 1, 2, 0)
"""Batch exit order: interrupt, usage, then SPEC-report §6.1's verdict
precedence (error, empty, fail, incomplete, pass). `empty` outranking `fail`
is the spec's call, not an accident: a contract that asserts nothing is the
vacuous-green case, and a batch hiding one behind a mere failure would bury
the more dangerous signal."""

_EXIT_WORD = {0: "pass", 1: "fail", 2: "incomplete", 3: "empty", 4: "error", EXIT_USAGE: "usage"}


def _batch_exit(codes: list[int]) -> int:
    for code in _EXIT_PRECEDENCE:
        if code in codes:
            return code
    return max(codes, default=0)


def _out_dir_for(spec: str, explicit: Path | None, *, batch: bool) -> Path:
    if explicit is not None and batch:
        # One directory cannot hold N reports at one deterministic name each;
        # every part gets its slug as a subdirectory.
        return explicit / Target.parse(spec).slug
    return _out_dir(spec, explicit)


def _cmd_check(args: argparse.Namespace, argv: list[str]) -> int:
    targets: list[str] = args.targets
    batch = len(targets) > 1

    # Invocation-SHAPE refusals come before anything touches disk: a shape
    # the tool won't run never meant to re-check anything. The collision
    # guard in particular must precede the placeholder fan-out, or the
    # fan-out itself performs the shared-path overwrite the guard exists to
    # refuse (PR #104 re-review, finding 7).
    if batch and args.render:
        print("partspec: --render is single-target for now", file=sys.stderr)
        return EXIT_USAGE
    if batch and args.out is not None:
        slugs = [Target.parse(spec).slug for spec in targets]
        collisions = sorted({s for s in slugs if slugs.count(s) > 1})
        if collisions:
            # Refuse rather than let the last part silently overwrite the
            # first's report under one deterministic path.
            print(
                f"partspec: --out with several targets needs distinct slugs, and "
                f"{', '.join(collisions)} collide{'s' if len(collisions) == 1 else ''}; "
                f"rename a factory or drop --out for per-contract output directories",
                file=sys.stderr,
            )
            return EXIT_USAGE

    # EVERY target's placeholder goes down before ANY target runs — not per
    # target inside the loop. An invocation that dies mid-flight (garbage
    # PARTSPEC_TIMEOUT below, interrupt during part two) meant to re-check
    # the later targets too, and their previous `verdict: "pass"` sitting
    # untouched at the deterministic path is a stale artifact reading as
    # current — the worst failure in the system (SPEC-report 5, rules 1-2;
    # PR #104 review). `_out_dir_for` only parses the target string, so it
    # needs no resolved Part.
    for spec in targets:
        write_placeholder(_out_dir_for(spec, args.out, batch=batch), contract=spec, argv=argv)

    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    expect_lock: dict[str, dict[str, str]] | None = None
    if args.expect is not None:
        from .expectation import LockError, read_lock

        try:
            expect_lock = read_lock(args.expect)
        except LockError as exc:
            print(f"partspec: {exc}", file=sys.stderr)
            return EXIT_USAGE

    pinned_parts: dict[str, dict[str, str]] = {}
    codes: list[int] = []
    for spec in targets:
        code = _check_one(
            spec, args, argv, timeout_s, batch=batch, expect_lock=expect_lock, pins=pinned_parts
        )
        if code == 130:
            # The user's own abort is the one failure that DOES stop a batch.
            return 130
        codes.append(code)

    if args.pin is not None and pinned_parts:
        from .expectation import write_lock

        write_lock(args.pin, pinned_parts)
        if not args.quiet:
            print(f"pinned {len(pinned_parts)} part(s) -> {args.pin}")

    if batch and not args.quiet:
        tally: dict[str, int] = {}
        for code in codes:
            word = _EXIT_WORD.get(code, str(code))
            tally[word] = tally.get(word, 0) + 1
        summary = ", ".join(f"{n} {word}" for word, n in tally.items())
        print(f"BATCH: {len(codes)} parts — {summary}")
    return _batch_exit(codes)


def _check_one(
    spec: str,
    args: argparse.Namespace,
    argv: list[str],
    timeout_s: float,
    *,
    batch: bool,
    expect_lock: dict[str, dict[str, str]] | None = None,
    pins: dict[str, dict[str, str]] | None = None,
) -> int:
    # The placeholder is already on disk — written by `_cmd_check` for every
    # target before any ran — so a resolution failure here (a contract that
    # raises on import, a typo in a keyword argument) leaves an artifact
    # saying the run died, never the previous run's `verdict: "pass"`.
    out = _out_dir_for(spec, args.out, batch=batch)

    resolved = _resolve_or_report(spec)
    if isinstance(resolved, int):
        return resolved
    part, target = resolved

    expected_claims: dict[str, str] | None = None
    if expect_lock is not None:
        # An absent part entry passes an empty pin down: the pin does not
        # vouch for any of these claims, and every one reports as unpinned.
        expected_claims = expect_lock.get(part.id, {})
    if pins is not None and args.pin is not None:
        from .expectation import claims_of

        pins[part.id] = claims_of(part)

    if args.render and part.source.engine != "openscad":
        # Before the run, so the refusal costs nothing and no artifact claims
        # a render pass that was never going to happen.
        print(
            "partspec: --render currently requires an OpenSCAD source "
            "(the OCCT tier does not have it yet)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    report = run(
        part,
        out_dir=out,
        argv=argv,
        contract_path=target.path,
        timeout_s=timeout_s,
        expected_claims=expected_claims,
    )

    render_error = None
    if args.render and report.error is None:
        from .backend import BuildError
        from .engines import openscad
        from .runner import _engine_source

        views = openscad.render_views(
            _engine_source(part), out, timeout_s=effective_timeout(timeout_s)
        )
        if isinstance(views, BuildError):
            render_error = views
        else:
            # Relative to the report's own directory, POSIX-separated — the
            # same portability rule part.source follows (SPEC-report.md §8).
            report.renders = {v: p.relative_to(out).as_posix() for v, p in views.items()}

    path = report.write(out)

    if not args.quiet:
        _summarise(report, path)
    if render_error is not None:
        # The report speaks for the part; this exit speaks for the run. A
        # requested render that failed must not exit as if it were delivered,
        # and the report carries no renders block — absence, not a lie.
        print(f"partspec: {render_error.message}", file=sys.stderr)
        if render_error.hint:
            print(f"  hint: {render_error.hint}", file=sys.stderr)
        return exit_code(Verdict.ERROR)
    return report.exit_code


def _invalidate_python_model(part: Part) -> None:
    """`measure` builds outside `run()`, so it evicts the model's cached
    modules itself — after the closure was read, same rule as the runner
    (#29). A stale helper served to the NEXT build is the failure class."""
    if part.source.engine != "openscad":
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(part.source.path)


def _cmd_measure(args: argparse.Namespace) -> int:
    """The adoption path: measure first, then decide which numbers are *intent*.

    Emits nothing that would be unsupported, and produces no verdict. partspec
    deliberately does not auto-generate checks from this — a check the tool wrote
    is a check nobody decided.
    """
    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        return resolved
    part, target = resolved

    from .backend import BuildError, Unsupported
    from .report import SCHEMA_VERSION
    from .runner import _backend_for, _engine_source, _tool_version, engine_block, identity
    from .status import ContractError

    try:
        backend = _backend_for(part.source.engine)
    except ContractError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    out = _out_dir(args.target, args.out)
    artifact = backend.build(_engine_source(part), out, timeout_s=timeout_s)
    if isinstance(artifact, BuildError):
        # The failure is an artifact too (#47): a caller parsing stdout used
        # to get an empty string and a bare exit code, with the reason living
        # only on stderr — machine-invisible exactly where a machine is the
        # audience. Same identity prefix as the success payload, so the
        # consumer can tell WHICH file and revision failed to measure.
        failed: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": "partspec", "version": _tool_version()},
            "part": identity(part, target.path),
            "engine": engine_block(part, backend),
            "params": dict(part.source.params),
            # Empty rather than absent, mirroring the report's failure shape:
            # the spec's identity-prefix claim stays exact on both verbs.
            "geometry": {},
            "error": artifact.message,
            "hint": artifact.hint,
        }
        print(json.dumps(failed, indent=2, allow_nan=False))
        print(f"partspec: {artifact.message}", file=sys.stderr)
        if artifact.hint:
            print(f"  hint: {artifact.hint}", file=sys.stderr)
        _invalidate_python_model(part)
        return exit_code(Verdict.ERROR)

    measurements: dict[str, object] = {}
    refused: dict[str, str] = {}
    unavailable: list[str] = []

    # `is_valid` and `topology_counts` are here but are not check kinds — the
    # first because its meaning differs by tier, the second because it is
    # answerable on only one. Both are useful to *see* while writing a contract,
    # which is what this verb is for.
    for name in (
        "bbox",
        "volume",
        "area",
        "center_of_mass",
        "is_valid",
        "watertight",
        "solid_count",
        "genus",
        "topology_counts",
        "bores",
        "blend_radii",
    ):
        if name not in backend.capabilities():
            unavailable.append(name)
            continue
        result = getattr(backend, name)(artifact)
        if isinstance(result, Unsupported):
            refused[name] = result.reason
            continue
        entry: dict[str, object] = {
            "value": list(result.value) if result.is_vector else result.value,
            "unit": result.unit,
            "exactness": "exact" if result.exact else "approximate",
        }
        if result.axes:
            entry["axes"] = list(result.axes)
        measurements[name] = entry

    measured: dict[str, object] = {
        # The identity prefix mirrors the report's field order exactly
        # (schema_version, tool, part, engine, params, geometry), so a
        # consumer of one artifact can orient in the other. `built=True`:
        # a Python model's imports are only knowable once it has run.
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "partspec", "version": _tool_version()},
        "part": identity(part, target.path, built=True),
        "engine": engine_block(part, backend),
        "params": dict(part.source.params),
        "geometry": backend.provenance(artifact),
        "measurements": measurements,
    }
    # Two different silences, separated because conflating them is a bug this
    # verb once had. `unavailable` is a property of the tier and the same for
    # every part it measures; `refused` is a property of *this* part, and its
    # reason names the defect. Before D17 only the first kind existed and
    # dropping it was honest. Now an open mesh drops `volume`, `genus` and
    # `center_of_mass`, and a reader writing their first contract from this
    # output would see no volume and decline to claim one — the omission
    # teaching exactly the wrong lesson, in the verb that exists for adoption.
    if refused:
        measured["refused"] = refused
    if unavailable:
        measured["unavailable"] = unavailable

    print(json.dumps(measured, indent=2, allow_nan=False))
    _invalidate_python_model(part)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Evidence, not judgement: images the report can reference (#20), framed
    deterministically from the bounding box so iterations are comparable. No
    verdict rides with them — rendering never substitutes for measurement."""
    try:
        timeout_s = _timeout_s(args.timeout)
    except _TimeoutUsage as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        return resolved
    part, _ = resolved

    if part.source.engine != "openscad":
        # Usage, not error: nothing failed — this verb does not exist for the
        # OCCT tier yet, and saying so beats a traceback from pretending it does.
        print(
            "partspec: render currently requires an OpenSCAD source "
            "(the OCCT tier does not have it yet)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    from .backend import BuildError
    from .engines import openscad
    from .runner import _engine_source

    out = _out_dir(args.target, args.out)
    result = openscad.render_views(
        _engine_source(part), out, timeout_s=effective_timeout(timeout_s)
    )
    if isinstance(result, BuildError):
        print(f"partspec: {result.message}", file=sys.stderr)
        if result.hint:
            print(f"  hint: {result.hint}", file=sys.stderr)
        return 4

    # The section-7 subset that applies to a render: no measurement tier is
    # involved, so no `backend` key — but method/param_mode still decide what
    # was built, and their absence made a method= render ambiguous (#73).
    engine: dict[str, object] = {
        "kind": "openscad",
        "version": openscad.version(),
        "render_backend": part.source.backend,
        "method": part.source.method,
        "param_mode": "call" if part.source.method else "define",
    }
    print(
        json.dumps(
            {
                "part": part.id,
                "engine": engine,
                "renders": {view: str(path) for view, path in result.items()},
            },
            indent=2,
        )
    )
    return 0


_ICON = {
    Status.PASS: "ok  ",
    Status.FAIL: "FAIL",
    Status.APPROXIMATE: "~?  ",
    Status.UNSUPPORTED: "n/a ",
    Status.SKIPPED: "--  ",
}


def _summarise(report, path: Path) -> None:
    """A human summary on stderr. stdout stays clean for the report path.

    Deliberately terse: this is a courtesy, not the contract. Anything a
    consumer needs is in the JSON.
    """
    for check in report.checks:
        line = f"  {_ICON[check.status]} {check.id}"
        if check.detail:
            line += f" — {check.detail}"
        print(line, file=sys.stderr)

    counts = report.counts()
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if name != "total" and n)
    print(f"\n{report.verdict.upper()}: {summary or 'no checks'}", file=sys.stderr)

    if report.verdict is Verdict.EMPTY:
        print(
            f"  {report.part_id!r} declares no checks. That is an unasked question, "
            f"not a passing design.",
            file=sys.stderr,
        )

    attribution = report.attribution()
    if attribution["dimensional"] and not attribution["attributed"]:
        # The circular-contract warning (#50, SPEC-contract.md 6): a bound
        # recomputed from the model's own constants cannot fail however the
        # design moves, and nothing in a single green run distinguishes that
        # from a real proof. Attribution is the distinguisher, and its total
        # absence is worth one line — same channel as the empty-contract
        # warning, because both are a green that proved less than it looks.
        print(
            f"  every dimensional limit on {report.part_id!r} is unattributed: "
            f"bounds derived from the model's own numbers prove the model matches "
            f"itself (partspec.refs carries cited values; SPEC-contract.md 10)",
            file=sys.stderr,
        )
    print(f"  {path}", file=sys.stderr)


def _cmd_diff(args: argparse.Namespace) -> int:
    """Compare two reports. The artifact goes to stdout — it is the product
    and it pipes; the courtesy summary goes to stderr (SPEC-diff.md 1)."""
    from .diff import DiffUsageError, diff_reports, exit_code_of, summary_of

    reports = []
    for path in (args.old, args.new):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except OSError as exc:
            print(f"partspec: cannot read {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except json.JSONDecodeError as exc:
            print(f"partspec: {path} is not a report: {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        doc = diff_reports(reports[0], reports[1], tool_version=_version())
    except DiffUsageError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        # A parseable file that is not a well-formed report (a check without
        # an id, a status outside the enum, a JSON array) is unusable input —
        # exit 64, never the catch-all's ERROR, and never a finding.
        print(
            f"partspec: these inputs are not well-formed reports ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    print(summary_of(doc), file=sys.stderr)
    return exit_code_of(doc["outcome"])


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list:
        parser.print_help()
        return EXIT_USAGE

    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        # argparse exits 2 on a usage error, and 2 is this tool's exit for
        # `incomplete` — a forgotten argument must not read as a verdict.
        # --help and --version exit 0 and pass through untouched.
        raise SystemExit(EXIT_USAGE if exc.code == 2 else exc.code) from None

    # The catch-all sits here, around the dispatch, and not inside `run`. Several
    # of the ways this fires never reach `run` at all: `--out` pointing at an
    # unwritable directory or an existing file dies in `write_placeholder`
    # (report.py) before the engine is touched. Left unguarded, every one of them
    # exited **1** -- this tool's code for "the part failed its contract" --
    # while the placeholder already on disk said `verdict: "error"`. The exit
    # code and the artifact contradicted each other, and exit 1 is the one an
    # agent is most likely to answer by editing the model.
    #
    # Reproduced with a `str` parameter (TypeError in adjudication), a
    # `PosixPath` parameter (TypeError rendering the -D literal), and both
    # `--out` cases. Deliberately not an isinstance ladder: the point is that
    # *unanticipated* failures land on ERROR rather than on a verdict about the
    # part. Placed after `parse_args`, so argparse keeps its own SystemExit.
    try:
        if args.command == "check":
            return _cmd_check(args, args_list)
        if args.command == "measure":
            return _cmd_measure(args)
        if args.command == "render":
            return _cmd_render(args)
        if args.command == "diff":
            return _cmd_diff(args)
    except KeyboardInterrupt:
        print("\npartspec: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - the last resort before the shell
        traceback.print_exc()
        print(f"\npartspec: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  this is a partspec failure, not a verdict on the part", file=sys.stderr)
        return exit_code(Verdict.ERROR)

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
