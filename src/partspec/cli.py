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
from pathlib import Path

from .report import write_placeholder
from .runner import run
from .status import EXIT_USAGE, Status, Verdict
from .target import TargetError, resolve

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

    measure = sub.add_parser(
        "measure",
        help="dump every quantity the backend can honestly produce (no verdict)",
    )
    measure.add_argument("target", help="<module-path>[:<factory>]")
    measure.add_argument("--out", type=Path, default=None)

    return parser


def _out_dir(target_spec: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    from .target import Target

    target = Target.parse(target_spec)
    return target.path.resolve().parent / "outputs" / target.slug


def _cmd_check(args: argparse.Namespace, argv: list[str]) -> int:
    try:
        part, target = resolve(args.target)
    except TargetError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    out = _out_dir(args.target, args.out)
    # Written before the engine runs: a try/finally cannot survive a native
    # fault, and a stale verdict:"pass" left at a deterministic path is the
    # worst failure this tool has.
    write_placeholder(out, part_id=part.id, contract=str(target.path), argv=argv)

    report = run(part, out_dir=out, argv=argv, contract_path=target.path)
    path = report.write(out)

    if not args.quiet:
        _summarise(report, path)
    return report.exit_code


def _cmd_measure(args: argparse.Namespace) -> int:
    """The adoption path: measure first, then decide which numbers are *intent*.

    Emits nothing that would be unsupported, and produces no verdict. partspec
    deliberately does not auto-generate checks from this — a check the tool wrote
    is a check nobody decided.
    """
    try:
        part, _ = resolve(args.target)
    except TargetError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    from .backend import BuildError, Unsupported
    from .runner import _backend_for, _engine_source
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

    measured: dict[str, object] = {
        "part": part.id,
        "engine": {"kind": part.source.engine, "version": backend.engine_version},
        "geometry": backend.provenance(artifact),
        "measurements": {},
    }
    for name in ("bbox", "volume", "area", "center_of_mass", "watertight", "solid_count", "genus"):
        if name not in backend.capabilities():
            continue
        result = getattr(backend, name)(artifact)
        if isinstance(result, Unsupported):
            continue
        entry: dict[str, object] = {
            "value": list(result.value) if result.is_vector else result.value,
            "unit": result.unit,
            "exactness": "exact" if result.exact else "approximate",
        }
        if result.axes:
            entry["axes"] = list(result.axes)
        measured["measurements"][name] = entry  # type: ignore[index]

    print(json.dumps(measured, indent=2))
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
    if args.command == "check":
        return _cmd_check(args, args_list)
    if args.command == "measure":
        return _cmd_measure(args)
    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
