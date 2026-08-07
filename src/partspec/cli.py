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
import sys
import traceback
from pathlib import Path

from .contract import Part
from .report import write_placeholder
from .runner import run
from .status import EXIT_USAGE, Status, Verdict, exit_code
from .target import Target, TargetError, resolve

__all__ = ["main"]


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

    check = sub.add_parser("check", help="build a part and check it against its contract")
    check.add_argument("target", help="<module-path>[:<factory>]")
    check.add_argument("--out", type=Path, default=None, help="report directory")
    check.add_argument("--quiet", action="store_true", help="suppress the human summary")
    check.add_argument(
        "--render",
        action="store_true",
        help="also write the canonical views and record their paths in the report",
    )

    measure = sub.add_parser(
        "measure",
        help="dump every quantity the backend can honestly produce (no verdict)",
    )
    measure.add_argument("target", help="<module-path>[:<factory>]")
    measure.add_argument("--out", type=Path, default=None)

    render = sub.add_parser(
        "render",
        help="write the canonical views (iso, front, top, right) as PNGs — no verdict",
    )
    render.add_argument("target", help="<module-path>[:<factory>]")
    render.add_argument("--out", type=Path, default=None)

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
    """
    try:
        return resolve(spec)
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


def _cmd_check(args: argparse.Namespace, argv: list[str]) -> int:
    # The placeholder goes down BEFORE the contract is resolved, not after.
    # Resolving is itself something that can fail -- a contract that raises on
    # import, a typo in a keyword argument -- and until this moved, that path
    # returned an exit code without touching the output directory, leaving the
    # *previous* run's `verdict: "pass"` at the deterministic path. The exit
    # code said error; the artifact on disk said the part was fine, and the
    # artifact is what a later reader trusts. Making the failure quieter was a
    # regression this ordering fixes.
    #
    # `_out_dir` only parses the target string, so it needs no resolved Part.
    out = _out_dir(args.target, args.out)
    write_placeholder(out, contract=args.target, argv=argv)

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        return resolved
    part, target = resolved

    if args.render and part.source.engine != "openscad":
        # Before the run, so the refusal costs nothing and no artifact claims
        # a render pass that was never going to happen.
        print(
            "partspec: --render currently requires an OpenSCAD source "
            "(the OCCT tier does not have it yet)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    report = run(part, out_dir=out, argv=argv, contract_path=target.path)

    render_error = None
    if args.render and report.error is None:
        from .backend import BuildError
        from .engines import openscad
        from .runner import _engine_source

        views = openscad.render_views(_engine_source(part), out)
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


def _cmd_measure(args: argparse.Namespace) -> int:
    """The adoption path: measure first, then decide which numbers are *intent*.

    Emits nothing that would be unsupported, and produces no verdict. partspec
    deliberately does not auto-generate checks from this — a check the tool wrote
    is a check nobody decided.
    """
    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        return resolved
    part, _ = resolved

    from .backend import BuildError, Unsupported
    from .runner import _backend_for, _engine_source, engine_block
    from .status import ContractError

    try:
        backend = _backend_for(part.source.engine)
    except ContractError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    out = _out_dir(args.target, args.out)
    artifact = backend.build(_engine_source(part), out)
    if isinstance(artifact, BuildError):
        print(f"partspec: {artifact.message}", file=sys.stderr)
        if artifact.hint:
            print(f"  hint: {artifact.hint}", file=sys.stderr)
        return 4

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
        "part": part.id,
        "engine": engine_block(part, backend),
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
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Evidence, not judgement: images the report can reference (#20), framed
    deterministically from the bounding box so iterations are comparable. No
    verdict rides with them — rendering never substitutes for measurement."""
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
    result = openscad.render_views(_engine_source(part), out)
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
    print(f"  {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list:
        parser.print_help()
        return EXIT_USAGE

    args = parser.parse_args(args_list)

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
