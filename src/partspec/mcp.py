"""MCP server over the same primitives as the CLI.

D5 deferred this until the report was machine-readable and the CLI had real
use; D18 fixes what it may be: **stateless verbs over `check` and `measure`**.
Every call is a fresh evaluation of a contract against a source on disk,
returning the same artifact the CLI writes. No tool holds geometry between
calls — the interactive authoring session belongs to authoring tools.

Each call runs the CLI in a subprocess rather than calling into the runner
in-process, for two reasons that are load-bearing, not stylistic:

- `POST-V0.md` §8: `sys.modules` caches a model's helper modules, so a
  long-lived process that re-checks an edited model can build the *previous*
  version of a helper while digesting the new one from disk — a stale build
  reported as fresh. A process per call makes that impossible; #27 owns
  deciding whether an invalidation story is worth the startup cost it saves.
- The exit code is part of the contract (`SPEC-report.md`). A subprocess
  returns the CLI's own, unlaundered; an in-process call would re-derive it.

The `mcp` dependency is an extra, imported lazily inside `build_server` —
`import partspec` stays stdlib-only, and this module is imported only by the
`partspec-mcp` entry point and its tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .status import EXIT_USAGE

if TYPE_CHECKING:
    from mcp.server import MCPServer

__all__ = ["build_server", "main"]

# Enough stderr to carry a traceback and the CLI's own diagnosis; not enough
# to flood a model's context when an engine dumps its life story.
_STDERR_TAIL = 4000

_INSTRUCTIONS = """\
partspec verifies CAD-as-code parts against engineering intent declared in a
Python contract. Only the verdict `pass` is green. `incomplete` means checks
could not be evaluated — unproven, not failing. `empty` means the contract
asserts nothing. `error` means the tool or environment failed and says nothing
about the part. Never weaken a contract to make it pass: a green report on a
weakened contract proves nothing, and the report records enough to detect it.
"""


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "partspec", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _check(target: str, out: str | None) -> dict[str, Any]:
    # Private import, deliberately: the report's location is the CLI's rule
    # (`<contract dir>/outputs/<slug>` unless --out), and duplicating the rule
    # here would let the two drift apart silently. `Target.parse` is total, so
    # this cannot raise — resolution failures happen in the subprocess, which
    # leaves its placeholder artifact behind for the read below.
    from .cli import _out_dir

    out_dir = _out_dir(target, Path(out) if out is not None else None)

    args = ["check", target, "--quiet"]
    if out is not None:
        args += ["--out", out]
    proc = _run_cli(args)

    result: dict[str, Any] = {
        "exit_code": proc.returncode,
        "report": None,
        "report_path": str(out_dir / "report.json"),
    }
    try:
        result["report"] = json.loads((out_dir / "report.json").read_text())
    except (OSError, json.JSONDecodeError):
        # No artifact — the CLI's own failure path. stderr is the only
        # evidence there is, so it rides along; when a report exists it is
        # the whole story and stderr would only restate it.
        result["report_path"] = None
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def _measure(target: str) -> dict[str, Any]:
    proc = _run_cli(["measure", target])
    result: dict[str, Any] = {"exit_code": proc.returncode, "measured": None}
    try:
        result["measured"] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["stderr"] = proc.stderr[-_STDERR_TAIL:]
    return result


def build_server() -> MCPServer:
    from mcp.server import MCPServer

    server = MCPServer("partspec", instructions=_INSTRUCTIONS)

    # The verbs match the CLI by name and meaning — agents use the same
    # commands as humans (D5). No `render` tool until one can answer honestly
    # (#17, #27): a listed tool that cannot work is the tool-list version of
    # silence reading as success.

    @server.tool()
    def check(target: str, out: str | None = None) -> dict[str, Any]:
        """Build a part and check it against its contract.

        `target` is `<module-path>[:<factory>]`, e.g. `specs/bracket.py:bracket`.
        Returns the report the CLI writes, its path, and the exit code:
        0 pass, 1 fail, 2 incomplete (unproven, not failing), 3 empty
        (the contract asserts nothing), 4 error (partspec or the environment
        failed — no verdict on the part), 64 bad usage.
        """
        return _check(target, out)

    @server.tool()
    def measure(target: str) -> dict[str, Any]:
        """Dump every quantity the backend can honestly produce. No verdict.

        The adoption path: see the numbers before deciding which of them are
        intent. `refused` quantities name this part's defect; `unavailable`
        ones name the tier's limit. It will not write checks for you — a
        check the tool wrote is a check nobody decided.
        """
        return _measure(target)

    return server


def main() -> int:
    try:
        server = build_server()
    except ImportError as exc:
        print(f"partspec-mcp: the MCP SDK is not importable: {exc}", file=sys.stderr)
        print("  hint: pip install 'partspec[mcp]'", file=sys.stderr)
        return EXIT_USAGE
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
