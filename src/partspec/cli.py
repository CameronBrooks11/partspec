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
import contextlib
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Any, cast

from .backend import DEFAULT_TIMEOUT_S, BuildError, effective_timeout
from .contract import Part
from .install import install_hint
from .report import tool_version, write_placeholder
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partspec",
        description="Verify CAD-as-code parts against declared engineering intent.",
        # Diagnostics cite the specs by section ("SPEC-report.md 7.1"), and the
        # wheel ships the package and nothing else — so for anyone who installed
        # rather than cloned, every one of those citations is a dead pointer
        # unless the tool says where the documents are. Found by dropping an
        # agent on a cold install: it went looking for SPEC-contract.md, could
        # not find it, and inferred the API from `inspect.getdoc` instead.
        epilog="Specs cited in diagnostics (SPEC-report.md, SPEC-contract.md, ...): "
        "https://github.com/CameronBrooks11/partspec/tree/main/docs",
    )
    parser.add_argument("--version", action="version", version=f"partspec {tool_version()}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    check = sub.add_parser("check", help="build parts and check them against their contracts")
    check.add_argument(
        "targets",
        nargs="+",
        metavar="target",
        help="<module-path>[:<factory>] — several targets share one process, "
        "one report each, exit by the worst verdict",
    )
    check.add_argument(
        "--out",
        type=Path,
        default=None,
        # The shape change is deliberate — one directory cannot hold N reports
        # at one deterministic name — but it was undocumented, so a caller who
        # built paths against the single-target shape had them move underneath
        # on adding a second target.
        help="report directory: DIR/report.json for one target, "
        "DIR/<part-slug>/report.json for several",
    )
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
    # NOT `check`'s "report directory", and the bare flag read as if it were:
    # `measure` writes no report by design (SPEC-report.md scope — the payload
    # is stdout), so `--out DIR` on the OCCT tier accepted a path, exited 0 and
    # created nothing. Same flag name, different noun, no help text to tell
    # them apart. The help that fixed that reading invited the next one (#187):
    # "where the .stl goes" reads as a filename, and a filename made a
    # DIRECTORY of that name — so a `.stl` filename is now honoured as one.
    #
    # `str`, not `type=Path`, alone among the `--out` flags: this is the one
    # that has to tell a file from a directory, and `Path` erases the single
    # syntactic signal that settles it — `Path("run.2026-08-13/")` is
    # indistinguishable from `Path("run.2026-08-13")`, so a trailing separator
    # could not mean what every shell user means by it.
    measure.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="where the engine's build artifact goes: a PATH ending in .stl IS "
        "the artifact, replaced only once the build succeeds, so a failed run "
        "leaves what was there. Any other PATH — a trailing "
        f"{os.sep!r}, an existing directory, any other suffix — is a directory "
        "to write <source>.stl in, and the MODEL'S OWN directory is refused "
        "when that name is already taken and the source closure is partial (it "
        "reads external data, or has includes partspec could not resolve). A "
        "file is refused when nothing would be written to it (the OCCT tier "
        "builds in memory) or when that same closure is partial, because an "
        "import()ed .stl is an input, not an output. The measurements "
        "themselves go to stdout — this verb emits no report file",
    )
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
        "--section",
        default=None,
        metavar="PLANE[:OFFSET]",
        help="also render a cut through xy, xz or yz at OFFSET mm "
        "(default: the bounding-box centre) — internal features made visible",
    )
    render.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=None,
        metavar="SECONDS",
        help=f"build budget in seconds (default {DEFAULT_TIMEOUT_S:g}, or "
        f"{ENV_TIMEOUT}; 0 waives the bound)",
    )

    lint = sub.add_parser(
        "lint",
        help="advisory findings about CAD source — never a verdict on the part",
    )
    lint.add_argument("sources", nargs="+", type=Path, metavar="source", help=".scad or .py")

    vdiff = sub.add_parser(
        "vdiff",
        help="compare two runs' renders visually (exit 0 identical, 1 different, 2 indeterminate)",
    )
    vdiff.add_argument("old", type=Path, help="a render.json / report.json, or its directory")
    vdiff.add_argument("new", type=Path, help="the later run's artifact or directory")
    vdiff.add_argument(
        "--out",
        type=Path,
        default=None,
        help="directory for the per-view diff images (default: <new>/vdiff)",
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


_SOURCE_ROOT = Path(__file__).resolve().parent


def _is_partspec_frame(frame: traceback.FrameSummary) -> bool:
    if frame.filename.startswith("<"):
        # `<string>` is usually a dataclass-generated `__init__` and
        # `<frozen ...>` the import machinery — partspec's implementation
        # under another name, with no source line to show. A contract MODULE
        # always has a real path (the loader imports it from a file), but code
        # the contract itself compiles does not, so this also hides frames
        # that are the reader's. They are counted in the marker, and where the
        # exception is not partspec's own they take the whole stack
        # unfiltered: the conservative side of a distinction the frame does
        # not carry.
        return True
    return Path(frame.filename).resolve().is_relative_to(_SOURCE_ROOT)


def _print_contract_traceback(exc: BaseException) -> None:
    """Print the traceback of an exception a contract raised, with partspec's
    own frames dropped (#188).

    The traceback stays because a contract is arbitrary Python: for a `TypeError`
    in user code it is the only thing that says *where*. What the reader did not
    ask for is partspec's call path to that line — six internal frames around one
    useful one, and for a `ContractError` (deliberately raised, with a message
    written for the reader) the internals are never the answer.

    Frames from a third-party library the contract called are kept: they are not
    partspec explaining itself, and a CadQuery operation that raised four calls
    deep is genuinely where the failure happened.

    What survives is printed *contiguously*, so every gap carries a
    `[N frames hidden]` marker. Without it the reprint reads as a direct call
    chain that never happened, and the reader most likely to be misled is an
    agent parsing it.

    Four cases print the whole thing unfiltered, because a filter that hides a
    partspec bug is the silence this tool exists to refuse:

    - **No contract frames at all** — the exception came from inside partspec
      before user code ran, so its frames are all there is.
    - **A partspec frame at or below the contract's own** and the exception is
      not partspec's — partspec code participated in the failure rather than
      merely reaching the contract, so an `AttributeError` from `region.py` is
      a partspec bug and its frames are the bug report. The leading frames that
      only got the process to the contract (`cli`, `target`) do not count: they
      are on every stack and are what #188 is about. A `ContractError` from the
      same position is a diagnosis written for the reader, and its frames are
      noise — the exception's own module is what separates the two.
    - **An exception group** — `format_exception_only` renders a group as its
      header alone ("2 sub-exceptions"), losing every sub-exception *and* the
      contract frames inside them, which is the opposite of the point.
    - **A chained exception** (`raise ... from`, or one raised while handling
      another) — the other segments of the chain are information.

    The chain case is a real limitation, not a rounding error: a contract doing
    `try/except → raise ContractError(...)` is idiomatic, and implicit
    `__context__` chaining sends it here. Filtering each segment independently
    was considered and refused for v1 — walking the chain means reproducing
    CPython's connector prose and its group tree by hand, and a filter that
    prints a *misleading* chain is worse than one that prints a noisy true one.

    Presentation only: the exit code (`EXIT_ERROR`), the "the contract is wrong,
    not the part" classification and the report on disk are untouched. Nothing
    is filtered out of an artifact — this path's report is `write_placeholder`'s,
    and the diagnosis lives on stderr alone (`AGENT-CONTRACT.md` §2.3), which is
    the only reason its shape is worth this much care.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    first_contract = next((i for i, f in enumerate(frames) if not _is_partspec_frame(f)), None)
    chained = exc.__cause__ is not None or (
        exc.__context__ is not None and not exc.__suppress_context__
    )
    partspec_raised_it = type(exc).__module__.split(".")[0] == "partspec"
    partspec_in_the_failure = first_contract is not None and any(
        _is_partspec_frame(f) for f in frames[first_contract:]
    )
    if (
        first_contract is None
        or chained
        or isinstance(exc, BaseExceptionGroup)
        or (partspec_in_the_failure and not partspec_raised_it)
    ):
        # `print_exception`, not `print_exc`: the exception is passed in, so
        # the fallback must not depend on being inside its `except` block.
        traceback.print_exception(exc)
        return

    out = ["Traceback (most recent call last):\n"]
    hidden = 0
    # Surviving frames are formatted in RUNS, never one at a time:
    # `[Previous line repeated N more times]` is something `format_list`
    # can only see across a list, and formatting frame by frame deletes it.
    # A recursive contract printed 1995 stderr lines that way against 20
    # collapsed ones — a 125x amplification out of a change whose whole
    # purpose is removing six lines of noise, and it would reach the MCP
    # adapter as a stderr tail (`mcp.py`) holding nothing but identical
    # frames.
    run: list[traceback.FrameSummary] = []
    for frame in frames:
        if _is_partspec_frame(frame):
            out.extend(traceback.format_list(run))
            run = []
            hidden += 1
            continue
        out.append(_hidden_marker(hidden))
        hidden = 0
        run.append(frame)
    out.extend(traceback.format_list(run))
    out.append(_hidden_marker(hidden))
    out.extend(traceback.format_exception_only(exc))
    sys.stderr.write("".join(out))


def _hidden_marker(hidden: int) -> str:
    if hidden == 0:
        return ""
    # Not "partspec frames": a `<string>` frame the CONTRACT generated is
    # hidden by the same rule, and the count would be honest while the word
    # was not.
    return f"  [{hidden} frame{'s' if hidden > 1 else ''} hidden]\n"


ARTIFACT_SUFFIX = ".stl"
"""The one thing `measure --out` can name. The OpenSCAD tier exports binary
STL and nothing else (`--export-format binstl`, SPEC-backend §5 step 1), so
this is the whole set of filenames the flag can honour — not a default among
several.

Matched exactly, so `--out UP.STL` is a directory. partspec only ever writes
the lowercase form, which makes an uppercase `.STL` almost always a file that
came from somewhere else — hand-authored or downloaded — and those are the
ones least likely to be output and most expensive to lose."""


REFUSED_OUT_HINT = (
    "only the OpenSCAD tier writes a build artifact — drop --out; on this tier "
    "no --out path receives one, whatever its shape, and the measurements go to stdout"
)
"""The remedy for `--out <file>` on a tier that exports nothing.

Named rather than inlined because its exact words are a decision, not a
phrasing: `test_measure_refuses_a_filename_on_the_tier_that_exports_nothing`
asserts EQUALITY against its own literal copy, so changing this string fails a
test and the change gets read by someone. That is deliberate, and it is the
second attempt. The first pinned `"pass a directory" not in hint`, which pins
one spelling of the advice rather than the advice: an adversarial review put
"use a directory instead" back into the hint and the whole suite still
reported 950 passed."""


def _names_the_artifact(raw: str) -> bool:
    """Whether `measure --out` names the .stl rather than a directory for it.

    `measure` writes exactly one file, so a caller reading "where the .stl
    goes" passes the .stl. That used to make a *directory* called `a.stl`
    holding `spacer.stl` and exit 0 — a run that reported success having done
    something else — while the same path existing as a file exited 4 (#187):
    the same question answered by prior state instead of by the flag.

    Three rules, in order, and each closes a way of getting this wrong:

    1. A trailing separator is directory intent, stated by the caller. This
       is why the flag keeps the raw string.
    2. An existing directory is a directory, whatever it is called.
    3. Otherwise the *suffix the engine actually writes* decides — nothing
       else. "Any suffix" was the first attempt and it was worse than the bug
       it fixed: `--out run.2026-08-13/` made a mesh file where a dated output
       directory was asked for, and `--out spacer.scad` overwrote the run's
       own source with 13 KB of STL at exit 0. A path whose name the engine
       cannot produce is not a filename this flag understands, so it falls
       through to the directory rule and, if it exists, is refused there.
    """
    if raw.endswith(("/", os.sep)):
        return False
    path = Path(raw)
    if path.is_dir():
        return False
    return path.suffix == ARTIFACT_SUFFIX


def _build_to_file(backend: Any, source: Any, dest: Path, timeout_s: float) -> Any | BuildError:
    """Build so the artifact lands at exactly `dest`, and only if it exists.

    **Nothing touches `dest` until there is an artifact to put there.** The
    engine runs in a scratch directory and the result is moved into place with
    `os.replace`, so the destination holds the old file or the new one and
    never neither: a failed build, a blown timeout or a Ctrl-C leaves whatever
    was there before, untouched.

    An earlier revision unlinked `dest` up front, reasoning that
    `openscad.render` does the same to its target so "a failed render leaves
    nothing behind for a later reader to pick up". That was wrong twice.
    `notes/FINDINGS.md` W9 states the remedy as an either/or — unlink the
    target *or* render to a fresh temp path and move it into place — and this
    function is the second branch, which is also the one FINDINGS praises
    `report.py` for. And the staleness W9 describes cannot arise here at all:
    the build happens in a fresh empty directory and the measurement is loaded
    from there, so `dest` is write-only for the whole run. What the unlink did
    reach was the caller's data. `.stl` is an *input* extension as well as an
    output one — SPEC-report §8.3 calls `import()`/`surface()` targets files
    that "genuinely are build inputs" — so deleting `dest` before the engine
    ran made a model importing it build without its import and report a
    confident, complete, wrong answer at exit 0. That is the defect #187
    exists to abolish, reintroduced by its own fix. `_measure_resolved`
    refuses a file destination for a model that reads external data; this
    function no longer removes anything it did not create.

    **The build happens in a scratch directory beside `dest`.** The engine
    names its export after the source file, so building straight into
    `dest.parent` would export `<source-stem>.stl` there first and unlink
    whatever the caller already had under that name — `--out models/a.stl`
    would destroy `models/spacer.stl`. Beside, rather than in the system temp
    dir, so the move into place is a rename on one filesystem. A symlink at
    `dest` is replaced by that rename rather than written through, so its
    target is untouched.

    The scratch directory is removed on every exit from this function,
    including exceptions and SIGINT; an uncaught signal — SIGTERM, SIGKILL —
    leaves a `.partspec-build-*` behind. Sweeping older ones is deliberately
    not done here: a concurrent `measure` writing another file in the same
    directory owns one of them, and this function cannot tell which.
    """
    import tempfile

    # One clause for every way the filesystem can refuse — an uncreatable
    # parent, an unwritable one, a failed move — because the caller's question
    # is the same in each: the artifact is not where you asked for it, and
    # that is the environment's doing, not the part's.
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=dest.parent, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as scratch:
            built = backend.build(source, Path(scratch), timeout_s=timeout_s)
            if isinstance(built, BuildError):
                return built
            (Path(scratch) / f"{source.path.stem}{ARTIFACT_SUFFIX}").replace(dest)
            return built
    except OSError as exc:
        return BuildError(
            f"could not write the build artifact to {dest}: {exc.strerror}",
            origin="environment",
        )


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
    from .engines.pycad import record_model_modules

    modules_before = set(sys.modules)
    try:
        part, target = resolve(spec)
        # The CONTRACT's sibling imports too, for every engine: a shared
        # claims.py cached from directory A silently supplied directory B's
        # checks in one process (PR #112 review) — the same stale-module
        # class as the model-helper case, one loader over. Recording for the
        # model dir happens here; the contract dir is recorded in the finally,
        # so a contract that raises AFTER its sibling import succeeded still
        # has that sibling on the books (#114).
        if part.source.engine != "openscad":
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
        _print_contract_traceback(exc)
        print(f"\npartspec: the contract raised {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  the contract is wrong, not the part", file=sys.stderr)
        return exit_code(Verdict.ERROR)
    finally:
        # Parseable without resolution, so the record exists on every outcome.
        record_model_modules(Target.parse(spec).path, modules_before)


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
    covered_ids: set[str] = set()
    codes: list[int] = []
    for spec in targets:
        code = _check_one(
            spec,
            args,
            argv,
            timeout_s,
            batch=batch,
            expect_lock=expect_lock,
            pins=pinned_parts,
            covered_ids=covered_ids,
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
        # Tallied before the coverage check joins `codes`: the synthetic
        # uncovered-pin error is not a part, and "3 parts" on a 2-target
        # invocation is a false count (PR #105 re-review, N1).
        tally: dict[str, int] = {}
        for code in codes:
            word = _EXIT_WORD.get(code, str(code))
            tally[word] = tally.get(word, 0) + 1
        summary = ", ".join(f"{n} {word}" for word, n in tally.items())
        print(f"BATCH: {len(codes)} parts — {summary}")

    if expect_lock is not None:
        # The pin must be covered, not merely consulted: dropping a pinned
        # part's target from the invocation is "delete the check" at part
        # granularity, and it read green until PR #105's review demonstrated
        # it. No report exists for a part no target produced, so this is the
        # one expectation failure that lives on stderr and in the exit alone.
        uncovered = sorted(expect_lock.keys() - covered_ids)
        if uncovered:
            print(
                f"partspec: the pin covers {', '.join(repr(p) for p in uncovered)} but no "
                f"target in this invocation produced "
                f"{'it' if len(uncovered) == 1 else 'them'}; a deleted part is a deleted "
                f"claim set (re-pin with --pin if the removal is deliberate)",
                file=sys.stderr,
            )
            codes.append(exit_code(Verdict.ERROR))

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
    covered_ids: set[str] | None = None,
) -> int:
    # Before the contract is resolved, because resolving it IMPORTS it: a
    # contract's own imports are this part's, and a snapshot taken any later
    # would report them as inherited. Names only — `sys.modules` keys cost
    # nothing here, and an OpenSCAD target never turns them into an inventory
    # (SPEC-report §8.3 rule 7).
    loaded_before = frozenset(sys.modules)

    # The placeholder is already on disk — written by `_cmd_check` for every
    # target before any ran — so a resolution failure here (a contract that
    # raises on import, a typo in a keyword argument) leaves an artifact
    # saying the run died, never the previous run's `verdict: "pass"`.
    out = _out_dir_for(spec, args.out, batch=batch)

    resolved = _resolve_or_report(spec)
    if isinstance(resolved, int):
        # The failed resolve may have cached sibling imports before raising;
        # they must not answer for a later run in this directory (#114).
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(spec).path)
        return resolved
    part, target = resolved

    expected_claims: dict[str, str] | None = None
    if expect_lock is not None:
        # An absent part entry passes an empty pin down: the pin does not
        # vouch for any of these claims, and every one reports as unpinned.
        expected_claims = expect_lock.get(part.id, {})
    if covered_ids is not None:
        covered_ids.add(part.id)
    if pins is not None and args.pin is not None:
        from .expectation import claims_of

        pins[part.id] = claims_of(part)

    try:
        return _check_resolved(
            spec, args, argv, timeout_s, part, target, out, expected_claims, loaded_before
        )
    finally:
        # Every exit path evicts — the --render usage refusal used to return
        # with the sibling record cached but not evicted (#114).
        _invalidate_after(part, target)


def _check_resolved(
    spec: str,
    args: argparse.Namespace,
    argv: list[str],
    timeout_s: float,
    part: Part,
    target: Target,
    out: Path,
    expected_claims: dict[str, str] | None,
    loaded_before: frozenset[str],
) -> int:
    built: list[object] = []
    report = run(
        part,
        out_dir=out,
        argv=argv,
        contract_path=target.path,
        timeout_s=timeout_s,
        expected_claims=expected_claims,
        artifact_out=built,
        loaded_before=loaded_before,
    )

    render_error = None
    # Renders depict the run's OWN successful build, or nothing (PR #133
    # review, F1/F2): the old `report.error is None` gate let a failing
    # build be rebuilt just for pictures, and a parameter-blocked run —
    # whose report says the build was never evaluated — build anyway and
    # ship images of it. `builds` passing is the one signal that is true
    # on both tiers.
    built_ok = any(c.kind == "builds" and c.status is Status.PASS for c in report.checks)
    if args.render and report.error is None and built_ok:
        result = _render_files(part, out, timeout_s, prebuilt=built[0] if built else None)
        if isinstance(result, BuildError):
            render_error = result
        else:
            views, meta = result
            # Relative to the report's own directory, POSIX-separated — the
            # same portability rule part.source follows (SPEC-report.md §8).
            report.renders = {v: p.relative_to(out).as_posix() for v, p in views.items()}
            report.render_bbox = cast("dict | None", meta.get("render_bbox"))
            report.render_tessellation = cast("dict | None", meta.get("render_tessellation"))

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


def _invalidate_after(part: Part, target: Target) -> None:
    """Evict what this run's resolve and build cached — the contract's
    sibling imports for every engine, the model's for the Python tiers —
    after the artifact is final (#29; PR #112 review for the contract half).
    A stale module served to the NEXT run is the failure class."""
    from .engines.pycad import invalidate_model_modules

    invalidate_model_modules(target.path)
    if part.source.engine != "openscad":
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
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(args.target).path)
        return resolved
    part, target = resolved

    try:
        return _measure_resolved(args, part, target, timeout_s)
    finally:
        _invalidate_after(part, target)


def _measure_failure(
    part: Part, target: Target, backend: Any, message: str, hint: str | None
) -> None:
    """Emit `measure`'s failure artifact: the identity prefix, then the reason.

    The failure is an artifact too (#47): a caller parsing stdout used to get
    an empty string and a bare exit code, with the reason living only on
    stderr — machine-invisible exactly where a machine is the audience. Same
    identity prefix as the success payload, so the consumer can tell WHICH
    file and revision failed to measure.

    Every build outcome and every `--out` refusal comes through here, which is
    what SPEC-report.md's Scope requires ("On any failure after the target
    resolves, both MUST emit a JSON object carrying that identity plus
    `error`/`hint`") — the refusals exit 64 rather than 4 but are no less a
    thing a machine has to understand. The exit code stays the caller's to
    choose; this only says what happened.

    One post-resolution path still prints stderr alone: an unknown engine
    (`_backend_for` raising `ContractError`), which cannot reach here because
    it has no backend to describe one with, and which the contract layer makes
    unreachable anyway.
    """
    from .report import SCHEMA_VERSION
    from .runner import engine_block, identity

    failed: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "partspec", "version": tool_version()},
        "part": identity(part, target.path),
        "engine": engine_block(part, backend),
        "params": dict(part.source.params),
        # Empty rather than absent, mirroring the report's failure shape:
        # the spec's identity-prefix claim stays exact on both verbs.
        "geometry": {},
        "error": message,
        "hint": hint,
    }
    print(json.dumps(failed, indent=2, allow_nan=False))
    print(f"partspec: {message}", file=sys.stderr)
    if hint:
        print(f"  hint: {hint}", file=sys.stderr)


def _measure_resolved(
    args: argparse.Namespace, part: Part, target: Target, timeout_s: float
) -> int:
    from .backend import Unsupported
    from .report import SCHEMA_VERSION
    from .runner import _backend_for, _engine_source, engine_block, identity
    from .status import ContractError

    try:
        backend = _backend_for(part.source.engine)
    except ContractError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    source = _engine_source(part)
    if args.out is not None and _names_the_artifact(args.out):
        dest = Path(args.out)
        if part.source.engine != "openscad":
            # Refused, not warned: the caller asked for a file this tier
            # cannot produce, and exiting 0 with nothing at that path is the
            # silent success this tool exists to refuse (#187).
            #
            # The hint no longer offers "pass a directory". It appeared to work
            # while a directory was silently accepted; #204 makes that same
            # request state that nothing was written, so following the old
            # advice now lands the reader in the state one line of output
            # complains about. `drop --out` is the whole remedy on this tier.
            #
            # It names no path of any shape, rather than naming a directory to
            # disclaim it. Two reasons, both learned here. A disclaimed remedy
            # still reads as a remedy to someone skimming for a path. And the
            # earlier phrasing said nothing is written "to it", which
            # presupposes the directory exists — it is never created, which is
            # the #204 myth this very PR spent six CHANGELOG lines refuting.
            _measure_failure(
                part,
                target,
                backend,
                f"--out {dest} names a file, but the {part.source.engine} tier builds "
                f"in memory and exports nothing to write there",
                REFUSED_OUT_HINT,
            )
            return EXIT_USAGE
        from .engines.openscad import include_closure

        # `.stl` is an INPUT extension too — `import()` reads one — so a
        # destination that looks like this run's output may be one of its
        # inputs. Writing the artifact over an input changes what the NEXT run
        # measures, so this is refused rather than guessed at, and the refusal
        # says which two files it cannot tell apart.
        #
        # The question asked is the whole of `partial`, not
        # `reads_external_data`, because those are the same question: a closure
        # with an UNRESOLVED include cannot see inside that file, so it cannot
        # know whether the file imports data either. `partial_reason` is
        # exactly "there are inputs I cannot account for" and says which kind,
        # non-None on precisely the closures `partial` is true of; it is
        # already computed (SPEC-report §8.3), and phrased in one place because
        # `openscad.render` refuses on the same grounds (#208).
        reason = include_closure(source.path).partial_reason
        if reason is not None:
            _measure_failure(
                part,
                target,
                backend,
                f"--out {dest} names a file, but {source.path.name} {reason}, so partspec "
                f"cannot account for every input and cannot prove {dest.name} is not one "
                f"of them",
                # "other than the model's own". The bare "pass a directory"
                # always worked until #223 gave the DIRECTORY form its own
                # refusal on the same grounds — so following this hint with the
                # obvious directory (`.`) landed the reader in a second refusal,
                # at a different exit code, with a different message. A remedy
                # that routes into another refusal is an answer that does
                # nothing reading as an answer (v0.7.6 pre-tag audit).
                f"pass a directory other than the model's own "
                f"({source.path.parent}) — the artifact lands in it as "
                f"{source.path.stem}{ARTIFACT_SUFFIX}",
            )
            return EXIT_USAGE
        artifact = _build_to_file(backend, source, dest, timeout_s)
        written_to = dest
    else:
        out = _out_dir(args.target, Path(args.out) if args.out is not None else None)
        artifact = backend.build(source, out, timeout_s=timeout_s)
        # The name inside the directory is partspec's, not the caller's, which
        # is the whole of #225: the caller chose `out` and cannot know the rest
        # without re-deriving a rule this tool owns and has already changed once
        # (#187). Spelled from `ARTIFACT_SUFFIX` for the same reason the
        # filename refusal above is, and pinned against a real build rather
        # than asserted, so the payload cannot promise a path nothing wrote.
        written_to = (
            out / f"{source.path.stem}{ARTIFACT_SUFFIX}"
            if part.source.engine == "openscad"
            else None
        )
    if isinstance(artifact, BuildError):
        _measure_failure(part, target, backend, artifact.message, artifact.hint)
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
        "self_intersection_free",
        "min_wall",
        "solid_count",
        "cavities",
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
        if result.bounds is not None:
            # The interval is the honesty (PR #144 review, F6): an
            # approximate value without its bounds reads more certain than
            # it is, in the verb whose job is showing the numbers.
            entry["bounds"] = list(result.bounds)
        if result.axes:
            entry["axes"] = list(result.axes)
        measurements[name] = entry

    measured: dict[str, object] = {
        # The identity prefix mirrors the report's field order exactly
        # (schema_version, tool, part, engine, params, geometry), so a
        # consumer of one artifact can orient in the other. `built=True`:
        # a Python model's imports are only knowable once it has run.
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "partspec", "version": tool_version()},
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

    # An unfulfillable `--out` is an entry, never an absence (#204). The
    # filename form of this same request exits 64 and says why; the directory
    # form accepted the path, wrote nothing and exited 0 in silence — two
    # spellings of "put the artifact here" on a tier that has no artifact, one
    # named and one not. The exit stays 0 because the MEASUREMENT succeeded and
    # is this verb's product: discarding it over an unfulfillable side-request
    # costs the caller more than the no-op flag does. The filename form keeps
    # its 64, because there the caller named a path they will go looking for.
    #
    # In BOTH channels. Stderr is for the human, and the payload for the
    # machine, because `measure`'s whole design principle is that a fact living
    # only on stderr is machine-invisible exactly where a machine is the
    # audience (#47). One `reason` string feeds both, so the two cannot drift.
    #
    # Only when `--out` was passed: nothing was asked for otherwise, and there
    # is nothing to report. `check --out` is untouched — it writes `report.json`
    # into that directory on every tier, so the flag is no no-op there.
    # Additive key, so `SCHEMA_VERSION` does not move.
    reason = (
        f"the {part.source.engine} tier builds in memory and exports nothing to put there"
        if args.out is not None and part.source.engine != "openscad"
        else None
    )
    if args.out is not None:
        # `written` states the outcome as a value rather than leaving it to be
        # inferred from the key's presence — which is what made the true case
        # cost nothing to add (#225): the key means "what happened to your
        # --out", not "your --out could not be honoured", and the narrower
        # reading was only ever an artefact of `false` being the first case
        # shipped. A consumer still reads one field.
        measured["artifact"] = (
            {"requested": args.out, "written": False, "reason": reason}
            if reason is not None
            else {"requested": args.out, "written": True, "path": str(written_to)}
        )

    print(json.dumps(measured, indent=2, allow_nan=False))
    if reason is not None:
        print(
            f"partspec: --out {args.out} names a directory for the build artifact, but {reason}",
            file=sys.stderr,
        )
        print(
            f"  hint: nothing was created at {args.out}; the measurements on stdout are "
            f"this verb's whole product, and only the OpenSCAD tier also writes an artifact",
            file=sys.stderr,
        )
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    """Tier-1 source lint (#26): engine-free, advisory, machine-readable.

    Exit 0 says the lint RAN; the findings are data in the payload — an
    advisory that failed the process would be a verdict the source never
    earned (the issue's bullet 3, verbatim: "advisory and never a verdict on
    the part"). 64 is reserved for inputs that cannot be linted at all.
    """
    import hashlib

    from .lint import LINT_SCHEMA_VERSION, LintError, lint_path

    # Deduped on the resolved path, order kept: the same file twice is one
    # file, not doubled counts (#120).
    unique: list[Path] = []
    seen: set[Path] = set()
    for source in args.sources:
        resolved = source.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(source)

    from .engines.openscad import find_executable
    from .lint import lint_scad_tier2

    scad_engine = find_executable()
    files = []
    courtesy: list[str] = []
    try:
        for source in unique:
            findings = lint_path(source)
            entry: dict[str, object] = {
                # Identity per file (#120, the #47 pattern): which bytes
                # produced these findings — a clean file is a visible
                # entry with a digest, not an absence.
                "file": str(source),
                "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
                "findings": [f.to_json() for f in findings],
            }
            if source.suffix == ".scad":
                tier2, unsupported = lint_scad_tier2(source, scad_engine)
                findings = [*findings, *tier2]
                entry["findings"] = [f.to_json() for f in findings]
                if unsupported:
                    # Refusals are entries, never absences (#118): a rule
                    # that could not run must not read as a clean bill.
                    entry["unsupported"] = unsupported
            courtesy.extend(f"  {f.rule}  {f.file}:{f.line}  {f.message}" for f in findings)
            files.append(entry)
    except LintError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    total = sum(len(f["findings"]) for f in files)
    payload = {
        "schema_version": LINT_SCHEMA_VERSION,
        "tool": {"name": "partspec-lint", "version": tool_version()},
        "files": files,
        "counts": {"files": len(files), "findings": total},
    }
    print(json.dumps(payload, indent=2, allow_nan=False))
    for line in courtesy:
        print(line, file=sys.stderr)
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

    section = None
    if args.section is not None:
        section = _parse_section(args.section)
        if section is None:
            # Usage, before any work: the ask itself is malformed.
            print(
                f"partspec: --section takes xy, xz or yz with an optional "
                f":offset in mm, got {args.section!r}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    # Before resolution (PR #131 review, F4): a failed resolve exits 64
    # with no artifact, and the previous run's render.json must not sit
    # there answering a later vdiff as if it were this run's. The images
    # without it are unreachable through the vdiff loader. An unparseable
    # target is the resolve path's message to give, hence the suppress.
    with contextlib.suppress(TargetError, OSError):
        (_out_dir(args.target, args.out) / "render.json").unlink(missing_ok=True)

    resolved = _resolve_or_report(args.target)
    if isinstance(resolved, int):
        from .engines.pycad import invalidate_model_modules

        invalidate_model_modules(Target.parse(args.target).path)
        return resolved
    part, target = resolved

    try:
        return _render_resolved(args, part, target, timeout_s, section)
    finally:
        # The render verb resolves contracts too; it leaked its sibling
        # records on every exit path until PR #124's review demonstrated it.
        _invalidate_after(part, target)


def _parse_section(text: str) -> tuple[str, float | None] | None:
    """`xy` | `xy:5.5` → (plane, offset); None when it is not a section ask."""
    plane, sep, tail = text.partition(":")
    if plane not in ("xy", "xz", "yz"):
        return None
    if not sep:
        return plane, None
    try:
        offset = float(tail)
    except ValueError:
        return None
    if not math.isfinite(offset):
        return None
    return plane, offset


_AXIS_NAMES = ("x", "y", "z")


def _render_files(
    part: Part,
    out: Path,
    timeout_s: float,
    section: tuple[str, float | None] | None = None,
    prebuilt: Any | None = None,
) -> tuple[dict[str, Path], dict[str, object]] | BuildError:
    """The view files for either tier — one dispatcher, so the `render` verb
    and `check --render` cannot drift apart (#18).

    OpenSCAD parts render through the engine's own viewer; OCCT-tier parts
    build through the same backend `check`/`measure` use and are rasterized
    from the tessellation (`raster.py`) — headless, deterministic, no GPU.
    A section (#19) is cut by the kernel that owns the geometry — OpenSCAD
    subtracts a half-space from its exported STL, the OCCT tier booleans the
    shape — and both are rasterized by the same code, cut faces distinct.
    Returns (views, meta) where meta carries `render_bbox` always and
    `render_tessellation` / `section` when they apply, in payload order.
    Raises `ContractError` when the engine has no backend, as `measure` would.
    """
    from .runner import _backend_for, _engine_source

    if part.source.engine == "openscad":
        from .engines import openscad

        views = openscad.render_views(
            _engine_source(part), out, timeout_s=effective_timeout(timeout_s)
        )
        if isinstance(views, BuildError):
            return views
        # The framing bbox rides with every render (#21): framing scales with
        # the part, so two sizes render identical pixels and the bbox is the
        # only witness. The STL is render_views's own export.
        from .backend import bbox_block

        stl = out / f"{_engine_source(part).path.stem}.stl"
        bbox = openscad._stl_bbox(stl)
        meta: dict[str, object] = {"render_bbox": bbox_block(*bbox)}
        if section is None:
            return views, meta
        plane, offset = section
        # The stale-artifact rule, hoisted (PR #130 review, F1): every
        # refusal below returns before the rasterizer's own unlink, and a
        # failing section must not leave the previous run's image to be
        # read as this run's.
        (out / "renders" / f"section_{plane}.png").unlink(missing_ok=True)
        try:
            import numpy  # noqa: F401
        except ModuleNotFoundError:
            return BuildError(
                "the section rasterizer needs numpy, and this environment has none",
                origin="environment",
                hint=(
                    "any partspec engine extra brings it, e.g. " + install_hint("'partspec[mesh]'")
                ),
            )
        from . import raster

        axis = raster.SECTION_VIEWS[plane][1]
        resolved = _resolve_offset(offset, bbox[0][axis], bbox[1][axis], plane)
        if isinstance(resolved, BuildError):
            return resolved
        cut_stl = openscad.render_section_stl(
            stl, plane, resolved, bbox, out, timeout_s=effective_timeout(timeout_s)
        )
        if isinstance(cut_stl, BuildError):
            return cut_stl
        points, faces = raster.read_stl(cut_stl)
        frame_points, _ = raster.read_stl(stl)
        png, cut_n = raster.render_section(points, faces, plane, resolved, frame_points, out)
        views[f"section_{plane}"] = png
        meta["section"] = {"plane": plane, "offset_mm": resolved, "cut_triangles": cut_n}
        return views, meta

    backend = _backend_for(part.source.engine)
    # `check --render` hands over the artifact its run just built (#129):
    # rebuilding a model the process holds in memory doubled side effects
    # and let a nondeterministic model's renders silently disagree with the
    # geometry the report measured.
    artifact = (
        prebuilt
        if prebuilt is not None
        else backend.build(_engine_source(part), out, timeout_s=timeout_s)
    )
    if isinstance(artifact, BuildError):
        return artifact
    # Imported only after the build delivered a shape: raster pulls in numpy,
    # and with the occt extra missing that import would crash HERE — a raw
    # traceback shadowing the honest environment BuildError the build's
    # import classification exists to produce (PR #127 review, F1).
    from . import raster

    result = raster.render_views(artifact, out)
    if isinstance(result, BuildError):
        return result
    views, tessellation, render_bbox = result
    meta = {"render_bbox": render_bbox, "render_tessellation": tessellation}
    if section is None:
        return views, meta

    import numpy as np

    plane, offset = section
    # Same hoisted stale-artifact rule as the OpenSCAD branch (F1).
    (out / "renders" / f"section_{plane}.png").unlink(missing_ok=True)
    frame_points = np.array(
        [(v.X, v.Y, v.Z) for v in artifact.tessellate(raster.TESSELLATION_TOLERANCE_MM)[0]]
    )
    axis = raster.SECTION_VIEWS[plane][1]
    lo, hi = frame_points.min(axis=0), frame_points.max(axis=0)
    resolved = _resolve_offset(offset, float(lo[axis]), float(hi[axis]), plane)
    if isinstance(resolved, BuildError):
        return resolved

    import build123d as bd

    pad = float(max(*(hi - lo), 1.0))
    mins = [float(c) - pad for c in lo]
    maxs = [float(c) + pad for c in hi]
    if plane == "xz":
        maxs[axis] = resolved  # camera at -Y: discard y < offset
    else:
        mins[axis] = resolved  # camera at +Z / +X: discard above the plane
    sizes = [b - a for a, b in zip(mins, maxs, strict=True)]
    middle = tuple((a + b) / 2 for a, b in zip(mins, maxs, strict=True))
    cut_shape = artifact - bd.Location(middle) * bd.Box(sizes[0], sizes[1], sizes[2])
    try:
        vertices, faces = cut_shape.tessellate(raster.TESSELLATION_TOLERANCE_MM)
    except ValueError:
        vertices, faces = [], []
    if not faces:
        return BuildError(f"the {plane} section at {resolved:g} mm discards the whole part")
    points = np.array([(v.X, v.Y, v.Z) for v in vertices])
    png, cut_n = raster.render_section(points, faces, plane, resolved, frame_points, out)
    views[f"section_{plane}"] = png
    meta["section"] = {"plane": plane, "offset_mm": resolved, "cut_triangles": cut_n}
    return views, meta


def _resolve_offset(offset: float | None, lo: float, hi: float, plane: str) -> float | BuildError:
    """The section offset, resolved and range-checked — never left implicit.

    A plane outside the part would render the uncut part with zero cut faces:
    an image that *looks fine*, which is precisely the failure this project
    documents. Refused with the range instead."""
    from . import raster

    axis = raster.SECTION_VIEWS[plane][1]
    resolved = (lo + hi) / 2.0 if offset is None else offset
    if not (lo - 1e-9 <= resolved <= hi + 1e-9):
        return BuildError(
            f"the {plane} section at {resolved:g} mm misses the part "
            f"({_AXIS_NAMES[axis]} spans {lo:g} mm to {hi:g} mm)"
        )
    return resolved


def _render_resolved(
    args: argparse.Namespace,
    part: Part,
    target: Target,
    timeout_s: float,
    section: tuple[str, float | None] | None = None,
) -> int:
    from .report import SCHEMA_VERSION
    from .runner import _backend_for, engine_block, identity
    from .status import ContractError

    if part.source.engine == "openscad":
        from .engines import openscad

        # The section-7 subset that applies here: no measurement tier is
        # involved, so no `backend` key — but method/param_mode still decide
        # what was built, and their absence made a method= render ambiguous
        # (#73).
        engine: dict[str, object] = {
            "kind": "openscad",
            "version": openscad.version(),
            "render_backend": part.source.backend,
            "method": part.source.method,
            "param_mode": "call" if part.source.method else "define",
        }
    else:
        # The OCCT tier builds through its backend to render (#18), so the
        # full engine block is true here — `backend` names a tier that ran.
        try:
            backend = _backend_for(part.source.engine)
        except ContractError as exc:
            print(f"partspec: {exc}", file=sys.stderr)
            return EXIT_USAGE
        engine = engine_block(part, backend)

    # The identity prefix mirrors the report's field order (#103, the #47
    # pattern): render was the last verb whose payload named its part with a
    # bare id string — no digests, no closure — so its images could not be
    # tied to the revision that produced them.
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "partspec", "version": tool_version()},
        "part": identity(part, target.path),
        "engine": engine,
        "params": dict(part.source.params),
    }

    out = _out_dir(args.target, args.out)
    # The same stale-artifact rule as every render file: a failing run must
    # not leave the previous run's payload to be read as this run's (#21).
    (out / "render.json").unlink(missing_ok=True)
    result = _render_files(part, out, timeout_s, section)
    if isinstance(result, BuildError):
        # The failure is an artifact too (#47): this path used to print to
        # stderr and return a bare 4 — machine-invisible exactly where a
        # machine is the audience. Empty rather than absent, mirroring
        # measure's failure shape: the identity prefix stays exact.
        payload["renders"] = {}
        payload["error"] = result.message
        payload["hint"] = result.hint
        # And WHOSE fault it was. #191 asked for "the same origin discipline
        # every other engine-side failure gets", and this payload had no
        # `origin` at all — so a consumer could not tell a degenerate solid
        # from an OCCT library that would not load, which is the distinction
        # SPEC-report §6.1 exists to force. `check`'s report has carried it
        # since #47; `render`'s did not (adversarial review of #241).
        payload["origin"] = result.origin
        print(json.dumps(payload, indent=2, allow_nan=False))
        print(f"partspec: {result.message}", file=sys.stderr)
        if result.hint:
            print(f"  hint: {result.hint}", file=sys.stderr)
        return exit_code(Verdict.ERROR)

    views, meta = result
    # `built=True`: a Python model's imports are only knowable once it has
    # run, and on this path it just did. No-op for OpenSCAD.
    payload["part"] = identity(part, target.path, built=True)
    payload["renders"] = {view: str(path) for view, path in views.items()}
    payload.update(meta)
    # The payload, on disk beside the images (#21): stdout serves the
    # invoker, but a later `vdiff` needs the engine version and framing
    # bbox of a PAST run, and stdout is gone. Renders relativized to the
    # file's own directory, the report's portability rule (§8 rule 4).
    disk = dict(payload)
    disk["renders"] = {v: p.relative_to(out).as_posix() for v, p in views.items()}
    (out / "render.json").write_text(json.dumps(disk, indent=2, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2, allow_nan=False))
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
    # One run-level fault is one fact about the run, not a fact about each
    # check. When the build fails for an environment reason, every declared
    # check is skipped carrying the SAME sentence as its detail, so a ten-check
    # contract printed an identical forty-word packaging diagnosis ten times
    # and `report.error` — the thing that actually happened — not once. The
    # detail stays in the artifact untouched, where a per-check consumer needs
    # it; only the console stops repeating itself.
    echoed = f"not evaluated: {report.error}" if report.error else None
    for check in report.checks:
        line = f"  {_ICON[check.status]} {check.id}"
        if check.detail and check.detail != echoed:
            line += f" — {check.detail}"
        print(line, file=sys.stderr)

    counts = report.counts()
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if name != "total" and n)
    print(f"\n{report.verdict.upper()}: {summary or 'no checks'}", file=sys.stderr)

    if echoed:
        # Said once, here, now that the per-check lines no longer say it. The
        # console never printed `report.error` at all before: on an
        # environment fault the only account of what happened was N copies of
        # it wearing a check's name.
        print(f"  {report.error}", file=sys.stderr)

    if report.hint:
        # `measure` and `render` have always printed their hint; `check` — the
        # verb people actually run — did not, so the one line saying what to DO
        # reached only `report.json`. A run with a hint is a run that proved
        # nothing about the part: the contract did not match its pin, the
        # contract raised, or the build failed. On the environment branch of
        # that last one the audience is necessarily a human at a terminal, and
        # the hint is the whole remedy — no machine repairs its own OCP
        # install. This does not make the console the contract (it is still a
        # courtesy, and the JSON is still ground truth); it stops the courtesy
        # from naming a problem and withholding its answer.
        print(f"  hint: {report.hint}", file=sys.stderr)

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
            f"itself — cite the source instead: partspec.refs for a standard it "
            f'carries (iso15, nema17), else partspec.Referenced(value, {{"standard": '
            f'..., "subject": ..., "field": ...}}) for anything it does not '
            f"(SPEC-contract.md 10)",
            file=sys.stderr,
        )
    print(f"  {path}", file=sys.stderr)


def _cmd_vdiff(args: argparse.Namespace) -> int:
    """What changed in the part's appearance (#21) — the pair of `diff`'s
    what-changed-in-the-claims. Same artifact-to-stdout, summary-to-stderr,
    outcome-to-exit-code shape."""
    from .vdiff import VdiffUsageError, diff_renders, exit_code_of, load_run, summary_of

    # Inputs first, numpy second: loading and validating the artifacts is
    # stdlib-only, so a numpy-less environment (the mcp-only install) still
    # names a bad ask precisely instead of leading with its own limitation.
    try:
        old = load_run(args.old)
        new = load_run(args.new)
    except VdiffUsageError as exc:
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        print(
            "partspec: vdiff compares pixels, which needs numpy — any partspec "
            "engine extra brings it",
            file=sys.stderr,
        )
        return EXIT_USAGE

    out = args.out
    if out is None:
        base = args.new if args.new.is_dir() else args.new.parent
        out = base / "vdiff"
    try:
        doc = diff_renders(old, new, out, tool_version=tool_version())
    except VdiffUsageError as exc:
        # An unreadable or foreign image mid-diff: the ask was malformed,
        # nothing was compared — usage, never a fabricated outcome.
        print(f"partspec: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        # A parseable file that is not a well-formed render artifact (no
        # part block, no engine) is unusable input — 64, never the
        # catch-all's ERROR, mirroring `diff`'s boundary (PR #131, F2).
        print(
            f"partspec: these inputs are not well-formed render artifacts "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    print(summary_of(doc), file=sys.stderr)
    return exit_code_of(doc["outcome"])


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
        doc = diff_reports(reports[0], reports[1], tool_version=tool_version())
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
    print(summary_of(doc, reports[1]), file=sys.stderr)
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
        if args.command == "lint":
            return _cmd_lint(args)
        if args.command == "diff":
            return _cmd_diff(args)
        if args.command == "vdiff":
            return _cmd_vdiff(args)
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
