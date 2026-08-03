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
import sys

from .status import EXIT_USAGE


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
        epilog=(
            "No subcommands yet — the report/status seam (P0) is implemented, the "
            "contract API and backends are not. See docs/PLAN.md. They are absent "
            "rather than stubbed on purpose: a verb that pretends to check "
            "something is the failure this tool exists to prevent."
        ),
    )
    parser.add_argument("--version", action="version", version=f"partspec {_version()}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        parser.print_help()
        return EXIT_USAGE
    parser.parse_args(args)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
