"""Render an OpenSCAD source to a mesh.

Deliberately does not parse `--summary` (D13). That flag omits volume and area
entirely, its `facets` field means different things depending on the render
backend, and — the reason it is banned rather than merely unhelpful — on invalid
geometry it emits JSON with the validity key *absent* while exiting 0. A checker
doing `.get("simple", True)` therefore passes a broken part silently. Export the
mesh and measure that instead; trimesh catches the same case immediately.

Ignoring `--summary` has a second benefit: it removes any reason to care whether
the installed OpenSCAD is the 2021.01 stable or a current nightly, so no nightly
install is a prerequisite.

Spec: SPEC-backend.md section 5, SPEC-contract.md section 3.1.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backend import DEFAULT_TIMEOUT_S, BuildError

__all__ = [
    "Closure",
    "OpenSCADSource",
    "find_executable",
    "include_closure",
    "render",
    "render_views",
    "scad_literal",
]


@dataclass(frozen=True, slots=True)
class OpenSCADSource:
    """An OpenSCAD file plus the parameters to build it with."""

    path: Path
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None
    """When set, parameters are passed as arguments to a call to this module,
    via a throwaway scratch entry that includes the source. Otherwise they
    override top-level variables via -D. The source file is never modified
    either way."""

    backend: str | None = None
    """OpenSCAD render backend: "Manifold", "CGAL", or None for the engine's
    default (Manifold on current builds, CGAL on 2021.01).

    Selectable because it **changes the artifact**, not merely its speed.
    Measured on a community gridfinity bin: the Manifold backend produced a mesh
    with 4 non-manifold edges where CGAL produced a clean one, from identical
    source. The flag does not exist on 2021.01, so it is only passed when set.
    """


def scad_literal(value: Any) -> str:
    """Render a Python value as an OpenSCAD literal.

    bool is checked before int because in Python `bool` subclasses `int`, so the
    obvious ordering silently turns `True` into `1`. (PartCAD's implementation
    carries the same note, having presumably been bitten by it.)
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, Sequence):
        return "[" + ", ".join(scad_literal(v) for v in value) + "]"
    if value is None:
        return "undef"
    raise TypeError(f"cannot render {type(value).__name__} as an OpenSCAD literal: {value!r}")


ENV_EXECUTABLE = "PARTSPEC_OPENSCAD"


def find_executable() -> str | None:
    """Locate the openscad binary.

    `PARTSPEC_OPENSCAD` wins if set, because **the engine version changes the
    artifact**. Measured on a gear library from `most-scad-libraries`: OpenSCAD
    2021.01 honours the removed `assign()` construct and 2026.08.01 ignores it,
    so the same source yields 648 triangles / 44463 mm3 on one and 120 / 28760
    on the other — a part 35% smaller in every planar dimension. Both exit 0 and
    write clean watertight meshes.

    Deliberately an environment variable rather than a contract field: which
    binary is installed is a property of the *machine*, not of the design. The
    render backend is the opposite — a design choice — and lives in the contract.
    The version is recorded in every report either way.

    Only two rules, in this order: the pin, then `PATH`. An earlier version also
    preferred `~/Applications/openscad/OpenSCAD-nightly.AppImage` — a convenience
    for one machine that had no business in library code. It meant `which
    openscad` reported 2021.01 while every render silently used 2026.08.01, on a
    tool whose own finding is that the version changes the part. A build whose
    engine is chosen by an undeclared path is the thing this function exists to
    prevent; set the pin instead, where the choice is visible.
    """
    pinned = os.environ.get(ENV_EXECUTABLE)
    if pinned:
        return pinned
    return shutil.which("openscad") or shutil.which("openscad-nightly")


def _define_args(params: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for name, value in params.items():
        args.append("-D")
        args.append(f"{name}={scad_literal(value)}")
    return args


def _method_call_source(source: Path, method: str, params: dict[str, Any]) -> str:
    """A scratch entry that includes the source and appends the call.

    An `include <>` of the absolute source path, not a copy of the body:
    OpenSCAD resolves nested `include`/`use` relative to the file *containing*
    the statement, so the source's own relative includes keep working wherever
    the scratch lives. The idea is PartCAD's — invoke a parameterised module
    without the file having a top-level call, never mutating the file.
    """
    args = ", ".join(f"{k} = {scad_literal(v)}" for k, v in params.items())
    return f"include <{source.resolve()}>\n{method}({args});\n"


def _method_scratch(source: OpenSCADSource, out_dir: Path) -> Path | BuildError:
    """Write the scratch entry, preferring the out dir over the source tree.

    The artifact under inspection and the inspector's scratch space must not
    share a directory (#39): the old in-tree copy crashed uncaught on a
    read-only source dir and left a tmp file for any watcher or `git add -A`
    to see. So the entry normally lives under the out dir, `.partspec-`
    prefixed per the report writer's convention.

    One measured exception. Relative `import()`/`surface()` data files
    resolve against the MAIN entry file's directory — not the file containing
    the statement — so an out-dir entry breaks exactly the sources
    `include_closure` flags as `reads_external_data` (adversarial review,
    live on 2021.01: `surface(file = "data.dat")` looked for the file in the
    out dir). Those sources keep their entry beside the source, uniquely
    named, and a read-only source dir becomes a *named* refusal instead of a
    traceback.
    """
    assert source.method is not None
    if ">" in str(source.path.resolve()):
        # `include <>` has no escape syntax; a path OpenSCAD cannot express
        # must refuse here, not surface as "Can't open include file" blaming
        # the model.
        return BuildError(
            f"the source path {source.path.resolve()} contains '>', which an OpenSCAD "
            f"include <> cannot express",
            origin="environment",
        )
    body = _method_call_source(source.path, source.method, source.params)
    if include_closure(source.path).reads_external_data:
        import tempfile

        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".partspec-", suffix=".scad", dir=source.path.parent
            )
        except OSError as exc:
            return BuildError(
                f"could not write the method scratch file in {source.path.parent}: {exc.strerror}",
                origin="environment",
                hint="this source reads external data files (import()/surface()), which "
                "resolve against the entry file's directory — the scratch must sit beside "
                "the source, and that directory is not writable",
            )
        # `os.fdopen` on the descriptor mkstemp handed back — `Path.open` takes
        # a path and would reopen by name, losing the atomic create. Spelled the
        # way `report._write_json` already spells it, which needs no suppression.
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        return Path(tmp_name)
    scratch = out_dir / f".partspec-{source.path.stem}-{source.method}.scad"
    try:
        scratch.write_text(body, encoding="utf-8")
    except OSError as exc:
        return BuildError(
            f"could not write the method scratch file in {out_dir}: {exc.strerror}",
            origin="environment",
        )
    return scratch


def _output_over_an_input(
    source: OpenSCADSource, stl: Path, closure: Closure, *, would_overwrite: bool
) -> BuildError | None:
    """Refuse, before rendering, when the artifact would land on a file that
    may be an input and nothing later can say whether it is.

    Building in a scratch directory keeps the MEASUREMENT honest — the engine
    reads whatever inputs are on disk, because nothing has been removed — but
    the move into place still writes `<stem>.stl` over whatever holds that
    name, and where the model reads that file the NEXT run measures something
    else. #208's repro is exactly that: `part.scad` imports `part.stl`, a
    destination of the source's own directory derives `part.stl`, and after
    the run the input is the output. Under `check` it was worse than a wrong
    number — a PASS verdict on geometry that was not the part.

    **This guard used to carry that case and no longer does.** An
    `import()`/`surface()` target is named in the engine's own dependency
    output, so #263 moved the question to `_wrote_over_an_input`, which is
    asked after the render and answers exactly which files were read. What is
    left here is the arm no depfile can reach: an **unresolved include**, which
    is listed nowhere at all because the depfile names what was opened and
    never what was asked for. partspec cannot see inside a file it could not
    find, so it cannot know whether that file imports data either — and no
    later signal will tell it. The narrowest condition is all three of:

    1. the destination is the directory the source's relative
       `import()`/`surface()` paths resolve against — its own;
    2. `<stem>.stl` is already there to be destroyed;
    3. an include did not resolve, so inputs exist that partspec cannot
       enumerate and the engine will not enumerate for it.

    (1) and (2) together are `would_overwrite`, which the caller computes
    before anything is written and hands to both guards — the post-render one
    falls back on exactly this condition when the engine cannot name its
    inputs, and by the time it runs, this call has created the file it would
    be asking about.

    Each clause is load-bearing in the direction of NOT over-refusing. Without
    (1) the second run of any such model against the default `outputs/<slug>`
    finds run 1's own artifact there and is refused — the ordinary path,
    broken. Without (2) a first run into the source directory is refused over a
    file that does not exist. Without (3) any model rendering twice into its
    own directory is refused on the second run.

    **What clause (1) used to cost, and no longer does.** Scoped this way, the
    old guard under-refused, and the cost was not one file. Where the import
    sat in a subdirectory — `import("sub/part.stl")` with `--out sub` — the
    artifact was REPLACED at that path rather than deleted, so the import still
    resolved and the model ate its own output. Measured then, three identical
    consecutive runs against a 3x7x11 donor:

        run 1  exit 0  bbox [8, 7, 11]   (correct)
        run 2  exit 0  bbox [13, 7, 11]
        run 3  exit 0  bbox [18, 7, 11]

    and `check` with a claim that is FALSE of the real part — `envelope(min=(12,
    7, 11))` — failed at run 1 and **passed at run 2**. So the residue was an
    unbounded series of confident wrong answers — at exit 0 for `measure`, and
    for `check` a verdict computed on geometry that is not the part, whichever
    way the claim points. That is #208's own headline symptom surviving in a
    narrower case, and it is what the post-render guard exists to end: the
    subdirectory import is in the dependency list by full resolved path, so the
    replace is refused wherever the destination sits.

    Scanning the closure for the destination's NAME was the precise alternative
    considered and rejected at the time: it resolves nothing when the path is
    computed, which is the case `reads_external_data` exists to admit, so it
    would refuse in the easy case and stay silent in the hard one. The remedy
    was always a signal that says which files a render actually READ, and that
    signal now exists.
    """
    if not would_overwrite:
        return None
    reason = closure.unresolved_reason
    if reason is None:
        return None
    return BuildError(
        f"the build artifact for {source.path.name} would be written to {stl.resolve()}, "
        f"in the model's own directory, but {source.path.name} {reason}, so partspec "
        f"cannot account for every input and cannot prove {stl.name} is not one of them",
        hint=f"pass an output directory other than the model's own ({source.path.parent}) "
        f"— the artifact lands in it as {stl.name}",
        origin="environment",
    )


def _wrote_over_an_input(
    deps: RenderDeps, dest: Path, name: str, *, refuse_unanswered: bool
) -> BuildError | None:
    """Refuse the move into place when the render itself read `dest`.

    Asked AFTER the render, which is the only time it can be answered, and
    asked only of a model whose closure is PARTIAL — for one that is not, every
    file the engine can reach is a `.scad` partspec has already walked, and the
    destination is an `.stl` no part of it names.

    Partial rather than `reads_external_data`, because the unresolved arm is
    not merely a case the depfile happens to cover as well. An `include` that
    partspec cannot find on ITS search path may resolve on the engine's, and
    the file behind it may hold the `import()` partspec then never saw — so a
    closure reporting `reads_external_data: False` is not a promise that the
    render read no data. It is the depfile, not the regex, that knows.

    **Nothing has been replaced yet**, which is what makes a late refusal
    correct rather than merely tidy: both movers stage into a scratch directory
    and this runs before the rename, so the caller's file is exactly as it was.
    What it costs is a render, and the message says so — the caller could not
    have known, and an error implying otherwise sends them looking for a
    mistake they did not make.

    **`refuse_unanswered` is what to say when the engine did not answer**, and
    it is not a preference: it is the caller keeping its own old behaviour for
    the case this cannot improve on. An engine with no `-d` writes no depfile,
    so `deps` is `absent` — which is not "the render read nothing"
    (`RenderDeps`) — and the exact question is unanswerable there exactly as it
    was before #226. So `render` passes the pre-render answer its conservative
    guard would have given (destination in the model's own directory, name
    already taken), and `cli._build_to_file` passes True, because a
    caller-named file destination was never provable and its refusal is the one
    #208 shipped. Neither loosens on an engine that cannot answer; both become
    exact on one that can.

    `partial` is unreachable from both call sites — a failed render returns
    before either mover is reached — and refuses under the same flag if that
    ever changes.
    """
    if deps.state != "complete":
        if not refuse_unanswered:
            return None
        return BuildError(
            f"the engine did not report the files it read, so partspec cannot prove "
            f"{dest.name} is not one of {name}'s inputs — and {name} reads external "
            f"data (import()/surface())",
            hint=f"this engine does not accept -d, so nothing can name the render's "
            f"inputs; write the artifact somewhere {name} cannot be reading — a "
            f"directory that holds none of its inputs",
            origin="environment",
        )
    if dest.resolve() not in deps.files:
        return None
    return BuildError(
        f"the render of {name} read {dest.resolve()}, so writing the build artifact "
        f"there would destroy one of its own inputs — the next run would measure "
        f"this run's output",
        hint=f"only the engine's own dependency list can answer this, so it took a "
        f"render to find out; nothing has been written — name a destination {name} "
        f"does not read",
        origin="environment",
    )


def render(
    source: OpenSCADSource,
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
    deps_out: list[RenderDeps] | None = None,
) -> Path | BuildError:
    """Render to binary STL, returning the path or a BuildError.

    Binary STL specifically: lib3mf cannot read ASCII STL, and OpenSCAD 2021.01
    defaults to ASCII. Choosing the format explicitly means the export does not
    silently change meaning with the installed version.

    **No file this call did not create is touched until there is an artifact to
    put there.** The engine writes into a scratch directory under `out_dir` and
    the result is moved into place with `os.replace`, so the destination holds
    the old file or the new one and never neither. It is the shape
    `cli._build_to_file` settled on for the filename form of `--out` — the
    directory form never got it (#208) — and the one SPEC-backend §5 step 1
    already spells the invocation with (`-o <tmp>.stl`), though the spec is
    illustrating the command rather than requiring the temporary.

    The claim is scoped that way rather than to "nothing in `out_dir`" because
    the scratch directory itself IS created there, before the engine runs. It
    is removed on every exit from the `with`, including exceptions and SIGINT;
    an uncaught signal — SIGTERM, SIGKILL — leaves a `.partspec-build-*`
    behind (measured: exit 143, leftover confirmed). Sweeping older ones is
    deliberately not done here, for `_build_to_file`'s reason: a concurrent
    render in the same directory owns one of them, and this call cannot tell
    which. A symlink at the destination is replaced by the rename rather than
    written through, so its target is untouched.

    An earlier revision unlinked the target up front, so that the
    exists/non-empty guards below could not be answered by a *stale* file from
    a previous run. That reason does not survive the scratch directory: the
    guards now ask about a file in a directory this call created empty
    moments earlier, so no previous run's mesh can be standing in it and there
    is nothing stale to be fooled by. What the unlink did reach was the
    caller's data — `.stl` is an input extension as well as an output one, and
    a model importing `<stem>.stl` built without its import and reported a
    complete, confident, wrong answer at exit 0, `measure` and `check` alike.

    `timeout_s` here is already resolved: a number is the bound, None is
    unbounded (the explicit `--timeout 0` waiver). The None-means-default rule
    lives one layer up, in `effective_timeout`.
    """
    global _DEPS_FLAG_OK

    executable = find_executable()
    if executable is None:
        return BuildError(
            "openscad not found on PATH",
            origin="environment",
            hint="install the stable package, or the nightly AppImage via workstation-configs",
        )
    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}", origin="environment")

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return BuildError(
            f"could not create the output directory {out_dir}: {exc.strerror}",
            origin="environment",
        )
    stl = out_dir / f"{source.path.stem}.stl"

    # Walked once and used twice: the pre-render refusal below asks it for the
    # arm no depfile can reach, and the post-render one asks whether to ask the
    # depfile at all.
    closure = include_closure(source.path)
    # Asked before anything is written, because it is the question the guard
    # below the render falls back on when the engine cannot name its inputs,
    # and by then this call has created the name it is asking about.
    would_overwrite = stl.exists() and out_dir.resolve() == source.path.parent.resolve()
    refusal = _output_over_an_input(source, stl, closure, would_overwrite=would_overwrite)
    if refusal is not None:
        return refusal

    scratch: Path | None = None
    try:
        if source.method:
            prepared = _method_scratch(source, out_dir)
            if isinstance(prepared, BuildError):
                return prepared
            scratch = prepared
            render_path, defines = scratch, []
        else:
            # A `-D` naming no top-level variable is silently accepted by
            # OpenSCAD and dropped. `openscad("part.scad", bore_diamter=8)` --
            # one transposition -- rendered the file's own default, and the
            # report then listed bore_diamter=8 under `params`, so the artifact
            # positively asserted a value the geometry never saw.
            unbound = unbound_parameters(source.path, source.params)
            if unbound:
                known = ", ".join(sorted(top_level_variables(source.path))) or "none"
                return BuildError(
                    f"parameter(s) {', '.join(unbound)} match no top-level variable in "
                    f"{source.path.name} or its includes, so -D would be silently dropped",
                    hint=f"top-level variables: {known}",
                )
            render_path, defines = source.path, _define_args(source.params)

        backend_args = ["--backend", source.backend] if source.backend else []
        # The scratch directory sits under `out_dir` rather than in the system
        # temp dir, so the move into place is a rename on one filesystem —
        # `_build_to_file` places its own beside the destination for the same
        # reason. The method entry file is NOT moved here: relative
        # `import()`/`surface()` paths resolve against the main entry file's
        # directory, so `_method_scratch` alone decides where that lives.
        with tempfile.TemporaryDirectory(
            dir=out_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as build_dir:
            staged = Path(build_dir) / stl.name
            wanted_deps = _DEPS_FLAG_OK
            # `-d` inside the scratch directory, which this call created empty
            # and which is removed with it: the engine's own account of what it
            # read is provenance, not an artifact, and it must not appear in a
            # directory the caller owns. Passed unconditionally because it is
            # inert on the render — 2021.01 documents it as
            # `deps_file -generate a dependency file for make`, and an engine
            # that does not accept it is handled where every other rejected
            # option is.
            depfile = Path(build_dir) / "deps"
            cmd = [
                executable,
                "--export-format",
                "binstl",
                *backend_args,
                "-o",
                str(staged),
                *(["-d", str(depfile)] if wanted_deps else []),
                *defines,
                str(render_path),
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                )
                rejected = _signal_lines(proc.stderr)
                if (
                    proc.returncode != 0
                    and wanted_deps
                    and _is_unknown_option(proc.stderr)
                    and _DEPS_RE.search(rejected[0])
                ):
                    # This engine has no `-d`. Drop it for the rest of the
                    # process and render again: the depfile is provenance, and
                    # losing it must cost the closure a claim, never the build.
                    _DEPS_FLAG_OK = False
                    wanted_deps = False
                    cmd = [a for a in cmd if a not in ("-d", str(depfile))]
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                    )
            except subprocess.TimeoutExpired:
                return BuildError(f"openscad timed out after {timeout_s}s", origin="environment")
            except OSError as exc:
                # A mistyped PARTSPEC_OPENSCAD reaches here. The pin is returned
                # as given rather than validated away, because silently falling
                # back to PATH would answer with an engine the user did not choose
                # — and the version is the part (F13). So it fails, by name.
                return BuildError(
                    f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                    origin="environment",
                    hint=f"{ENV_EXECUTABLE} is set to this path"
                    if os.environ.get(ENV_EXECUTABLE)
                    else None,
                )

            # Once, here: every return below this point has the same answer,
            # and `exit 0 but no geometry` is a COMPLETE depfile rather than a
            # failed one — measured, a model whose `include` did not resolve
            # exits 0 and the depfile lists the source alone. Read whether or
            # not a caller wanted it, because the guard below the render wants
            # it too and a second read would be a second answer.
            deps = (
                _read_depfile(depfile, ok=proc.returncode == 0)
                if wanted_deps
                else RenderDeps(state="absent")
            )
            if deps_out is not None:
                deps_out.append(deps)

            if proc.returncode != 0:
                reason = _first_error_line(proc.stderr)
                if _is_unknown_option(proc.stderr):
                    # The engine rejected an option partspec passed, which is a
                    # statement about the ENGINE, not the part. The 2021.01 case is
                    # `backend=`: render backends arrived later, and Debian and
                    # Ubuntu ship 2021.01, so this is the ordinary experience of a
                    # contract written against a newer engine, not an exotic one.
                    #
                    # Measured before this branch existed: `verdict: fail`,
                    # `build_origin: "model"`, hint `unrecognised option
                    # '--backend'`. The hint was right and the origin was wrong,
                    # and the origin is what AGENT-CONTRACT §2.3 routes on — so an
                    # agent was sent to §2.1 "fix the source" over a machine that
                    # simply predates the flag. SPEC-report §6.1 forbids exactly
                    # that: an environment fault MUST NOT be reported as a
                    # statement about the part.
                    # The hint names the option the ENGINE named, never a literal.
                    # It read "(2021.01 has no --backend)", which is true of the
                    # case that prompted this branch and false of every other:
                    # `--export-format` is passed on every render and arrived in
                    # 2021.01, so on an older binary every build lands here and the
                    # hint would have told the reader to drop a flag they never
                    # passed (PR #160 review).
                    return BuildError(
                        f"the openscad binary rejected an option partspec passed: {reason}",
                        hint=f"this engine does not accept it — {reason}. Upgrade openscad, "
                        f"or drop the contract argument that needs it (`backend=` needs a "
                        f"build newer than 2021.01)",
                        origin="environment",
                        stderr=proc.stderr,
                    )
                return BuildError(
                    f"openscad exited {proc.returncode}",
                    hint=reason,
                    stderr=proc.stderr,
                    produced_nothing=_EMPTY_RESULT in proc.stderr,
                    unresolved=_unresolved_lines(proc.stderr),
                )
            # OpenSCAD exits 0 on some degenerate input while writing nothing
            # useful, so the artifact is checked rather than the exit code
            # trusted. It is the STAGED file that is checked: the scratch
            # directory was created empty by this call, so "exists and is
            # non-empty" cannot be answered by a previous run's mesh — which
            # is the whole reason the old up-front unlink existed.
            if not staged.is_file() or staged.stat().st_size == 0:
                return BuildError(
                    "openscad exited 0 but produced no geometry",
                    hint=_first_error_line(proc.stderr),
                    stderr=proc.stderr,
                    # Same outcome by another route, and flagged on both because
                    # which one an empty model takes is a property of the engine
                    # BUILD, not of the part: 2021.01 exits 1 here and the CI
                    # matrix also runs 2026.08.01. Keying on one exit code would
                    # make `empty` answer differently on two engines for one
                    # source, which is F13 all over again.
                    produced_nothing=True,
                    unresolved=_unresolved_lines(proc.stderr),
                )
            if closure.partial:
                # The exact question #223's guard could not ask, asked where it
                # can be answered and while the caller's file is still intact.
                refusal = _wrote_over_an_input(
                    deps, stl, source.path.name, refuse_unanswered=would_overwrite
                )
                if refusal is not None:
                    return refusal
            staged.replace(stl)
            return stl
    except OSError as exc:
        # One clause for the scratch directory and for the move, because the
        # caller's question is the same in each: the artifact is not where you
        # asked for it, and that is the environment's doing, not the part's.
        # Same sentence `_build_to_file` uses, for the same failure.
        return BuildError(
            f"could not write the build artifact to {stl}: {exc.strerror}",
            origin="environment",
        )
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def render_section_stl(
    stl: Path,
    plane: str,
    offset: float,
    bbox: tuple[tuple[float, ...], tuple[float, ...]],
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> Path | BuildError:
    """Cut the exported STL with a half-space and re-export it, kernel-capped.

    The cut subtracts from the ALREADY-EXPORTED mesh rather than the source:
    D15's measurand is the artifact as exported, and importing it back keeps
    every parameter binding exactly as the canonical views saw it — no second
    pass through `-D`/method scratch machinery to drift. The engine does the
    boolean, so the exposed faces are real capped material, not a display
    trick. The discard side per plane follows `raster.SECTION_VIEWS`: the
    material between the section camera and the plane is removed.

    Both files this call writes go into a scratch directory and the result is
    moved into place, the shape `render()` settled on (#208, #224). Neither
    `<stem>.section.stl` nor the `<stem>.section.scad` that produces it is a
    name partspec is the only plausible author of *by extension* — both are
    model extensions — and the old code deleted the first and truncated the
    second in the caller's directory before the engine ran. The cut script is
    safe to relocate because it names the mesh it imports by resolved absolute
    path, so nothing in it resolves against its own directory.
    """
    import json as _json

    executable = find_executable()
    if executable is None:
        return BuildError(
            "openscad not found on PATH",
            origin="environment",
            hint="install the stable package, or the nightly AppImage via workstation-configs",
        )
    lo, hi = bbox
    pad = max(*(top - bottom for top, bottom in zip(hi, lo, strict=True)), 1.0)
    axis = {"xy": 2, "xz": 1, "yz": 0}[plane]
    mins = [c - pad for c in lo]
    maxs = [c + pad for c in hi]
    if plane == "xz":
        maxs[axis] = offset  # camera at -Y: discard y < offset
    else:
        mins[axis] = offset  # camera at +Z / +X: discard above the plane
    sizes = [b - a for a, b in zip(mins, maxs, strict=True)]

    out = out_dir / f"{stl.stem}.section.stl"
    try:
        with tempfile.TemporaryDirectory(
            dir=out_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
        ) as build_dir:
            scratch = Path(build_dir) / f"{stl.stem}.section.scad"
            staged = Path(build_dir) / out.name
            scratch.write_text(
                "difference() {\n"
                f"  import({_json.dumps(str(stl.resolve()))});\n"
                f"  translate([{mins[0]!r}, {mins[1]!r}, {mins[2]!r}])"
                f" cube([{sizes[0]!r}, {sizes[1]!r}, {sizes[2]!r}]);\n"
                "}\n"
            )
            try:
                proc = subprocess.run(
                    [executable, "--export-format", "binstl", "-o", str(staged), str(scratch)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return BuildError(f"openscad timed out after {timeout_s}s", origin="environment")
            except OSError as exc:
                return BuildError(
                    f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                    origin="environment",
                )
            if proc.returncode != 0:
                return BuildError(
                    f"openscad exited {proc.returncode} cutting the {plane} section",
                    hint=_first_error_line(proc.stderr),
                    stderr=proc.stderr,
                )
            # The staged file is the one asked about, for `render()`'s reason:
            # the scratch directory was created empty moments ago, so an empty
            # cut cannot be masked by a previous run's section sitting at `out`.
            if not staged.is_file() or staged.stat().st_size == 0:
                return BuildError(
                    f"the {plane} section at {offset:g} mm discards the whole part",
                    hint=_first_error_line(proc.stderr),
                )
            staged.replace(out)
            return out
    except OSError as exc:
        return BuildError(
            f"could not write the section artifact to {out}: {exc.strerror}",
            origin="environment",
        )


VIEWS: dict[str, tuple[float, float, float]] = {
    "iso": (55.0, 0.0, 25.0),
    "front": (90.0, 0.0, 0.0),
    "top": (0.0, 0.0, 0.0),
    "right": (90.0, 0.0, 90.0),
}
"""The canonical views, as gimbal rotations. Canonical rather than arbitrary
because an agent compares images across iterations, and a camera that moves
makes every comparison ambiguous (#17)."""

IMAGE_SIZE = (800, 800)


def _stl_bbox(stl: Path) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Min/max corners of a binary STL, by scanning its vertices.

    stdlib on purpose: the engine layer renders and the backend layer measures,
    and pulling trimesh in here to answer a framing question would blur that
    seam. Facets are 50 bytes — a 3-float normal, three 3-float vertices, a
    2-byte attribute — after an 80-byte header and a facet count.
    """
    import struct

    data = stl.read_bytes()
    (count,) = struct.unpack_from("<I", data, 80)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for f in range(count):
        base = 84 + f * 50 + 12  # skip the normal
        for v in range(3):
            x, y, z = struct.unpack_from("<3f", data, base + v * 12)
            for i, c in enumerate((x, y, z)):
                lo[i] = min(lo[i], c)
                hi[i] = max(hi[i], c)
    return tuple(lo), tuple(hi)


def _camera(bbox: tuple[tuple[float, ...], tuple[float, ...]], rot: tuple[float, ...]) -> str:
    """A gimbal camera string derived from the bounding box, so identical
    geometry frames identically on every run."""
    lo, hi = bbox
    center = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    diagonal = sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True)) ** 0.5
    distance = max(2.2 * diagonal, 1.0)  # a degenerate flat part still gets a frame
    return ",".join(repr(v) for v in (*center, *rot, distance))


_EMPTY_RESULT = "Current top level object is empty"

_UNRESOLVED_MARKERS = (
    "Can't open include file",
    "Ignoring unknown module",
    "Ignoring unknown function",
    "Ignoring unknown variable",
    "undefined operation",
)
"""What OpenSCAD says when a name did not resolve — measured on 2021.01, not
guessed. Each was produced from a source written to trigger it: a missing
include, a misspelt module, an unknown function, an undefined variable, and a
`vector * string`.

The list exists because an unresolved name and a genuinely null result are
INDISTINGUISHABLE downstream: both exit 1 with `Current top level object is
empty.` and write no STL. A model whose whole top-level object comes from a
failed include renders empty and, without these lines, reads exactly like a
clean pass — which is how `p.empty()` would launder a broken probe into a green
one. So the markers are the evidence, and they are all that separates the two.

Matching on the message rather than a code because OpenSCAD has no distinct
exit code for either; if a future engine version gains one, prefer it and keep
this as the fallback."""


def _unresolved_lines(stderr: str) -> tuple[str, ...]:
    """The stderr lines naming something the engine could not resolve."""
    return tuple(
        line.strip()
        for line in stderr.splitlines()
        if any(marker in line for marker in _UNRESOLVED_MARKERS)
    )


def _display_failure(returncode: int, stderr: str) -> bool:
    """Whether a PNG render died for want of a display.

    2021.01 has no EGL offscreen path: headless it prints `Unable to open a
    connection to the X server` / `Can't create OpenGL OffscreenView`, then
    segfaults (139) leaving a 0-byte file. That is an environment fault with a
    known remedy, and reporting it as `openscad exited -11` with a compile-log
    hint sends the reader off to debug their model.
    """
    if "OffscreenView" in stderr or "X server" in stderr:
        return True
    return returncode in (139, -11)


def render_views(
    source: OpenSCADSource,
    out_dir: Path,
    *,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
    deps_out: list[RenderDeps] | None = None,
) -> dict[str, Path] | BuildError:
    """Render the canonical views to PNG, or say exactly why not.

    The STL is rendered first, deliberately: it carries the guards this path
    must not re-invent — unbound `-D` detection, the empty-geometry refusal —
    so a cut that consumed the part is a `BuildError` here, never four blank
    frames that *look* like a rendered part. It also supplies the bounding box
    the camera framing derives from. The images carry no verdict: rendering
    never substitutes for measurement.

    All four views are rendered into a scratch directory and moved into place
    together, the shape `render()` settled on (#208, #224). Here the hazard the
    old per-view unlink carried was not remote: `surface(file = "...")` reads a
    PNG as a heightmap on both engine versions, so `render --out .` against a
    model reading `renders/iso.png` deleted that heightmap before the engine
    ran, then rendered and reported the part built without it — measured, first
    run, clean directory, exit 0, nothing on stderr.

    A failure while RENDERING leaves the previous set of views untouched. A
    failure while MOVING cannot: there is no atomic rename of four files, so
    the one case that is knowable up front — a destination that is a directory
    — is refused before the first move, and a move that fails anyway reports
    how many were replaced instead of claiming nothing was.

    What survives is the residue `render()` also ships with, and it is not a
    lost file: the move still replaces whatever sits at the destination, so a
    model reading its own view directory renders correctly once and then reads
    its own output forever — but only when `--out` points at a directory
    CONTAINING the file the model reads. OpenSCAD resolves `surface(file = ...)`
    against the entry file's directory, so with `--out` genuinely elsewhere the
    written PNG never lands on the read one and consecutive runs are identical.
    This paragraph omitted that condition until the v0.7.6 pre-tag audit, which
    measured both shapes; the CHANGELOG had already been corrected and the
    docstring left behind, in the same commit.

    Measured on 2021.01 for the case that does compound — a model reading
    `sub/renders/iso.png`, rendered with `--out sub` — run 1 gives a correct
    `render_bbox`, and from run 2 the heightmap IS partspec's own view, so the
    part takes that image's extent: `IMAGE_SIZE` is 800x800 and `surface()`
    spans one unit per pixel gap, giving 799 in x and y, at exit 0 with nothing
    on stderr, on every run after.

    **The exact answer now exists and this function does not yet use it.** #226
    landed the mechanism and #263 applied it to the STL move, where
    `_wrote_over_an_input` refuses on the engine's own dependency list rather
    than on a guess. The same list would answer here — `surface()` targets are
    read at parse time, so the STL render's depfile already names the heightmap
    — but the guard is asked only of `<stem>.stl`, and the view moves below go
    through untouched. So the residue above survives for PNG destinations
    exactly as measured, and it survives as a known one rather than as an
    unanswerable one.
    """
    stl = render(source, out_dir, timeout_s=timeout_s, deps_out=deps_out)
    if isinstance(stl, BuildError):
        return stl
    executable = find_executable()
    assert executable is not None  # render() just used it

    if source.method:
        prepared = _method_scratch(source, out_dir)
        if isinstance(prepared, BuildError):
            return prepared
        scratch, render_path, defines = prepared, prepared, []
    else:
        scratch, render_path, defines = None, source.path, _define_args(source.params)

    bbox = _stl_bbox(stl)
    renders: dict[str, Path] = {}
    finished: list[tuple[Path, Path]] = []
    renders_dir = out_dir / "renders"
    try:
        try:
            renders_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                dir=renders_dir, prefix=".partspec-build-", ignore_cleanup_errors=True
            ) as build_dir:
                for view, rot in VIEWS.items():
                    png = renders_dir / f"{view}.png"
                    staged = Path(build_dir) / png.name
                    cmd = [
                        executable,
                        "--camera",
                        _camera(bbox, rot),
                        "--imgsize",
                        f"{IMAGE_SIZE[0]},{IMAGE_SIZE[1]}",
                        "--projection",
                        "ortho",
                        "--colorscheme",
                        "Cornfield",
                        "-o",
                        str(staged),
                        *defines,
                        str(render_path),
                    ]
                    try:
                        proc = subprocess.run(
                            cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                        )
                    except subprocess.TimeoutExpired:
                        return BuildError(
                            f"openscad timed out after {timeout_s}s", origin="environment"
                        )
                    except OSError as exc:
                        # Caught here rather than by the clause below, which
                        # would report a failure to EXEC as a failure to write.
                        return BuildError(
                            f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                            origin="environment",
                        )
                    if _display_failure(proc.returncode, proc.stderr):
                        return BuildError(
                            "this OpenSCAD cannot render PNG without a display",
                            origin="environment",
                            hint="run under `xvfb-run -a`, or use a 2022+ build with EGL offscreen",
                            stderr=proc.stderr,
                        )
                    if proc.returncode != 0:
                        return BuildError(
                            f"openscad exited {proc.returncode} rendering the {view} view",
                            hint=_first_error_line(proc.stderr),
                            stderr=proc.stderr,
                        )
                    # Asked of the staged file: the scratch directory is this
                    # call's own and was created empty, so a view the engine
                    # never wrote cannot be answered by the previous run's PNG.
                    if not staged.is_file() or staged.stat().st_size == 0:
                        return BuildError(
                            f"openscad exited 0 but wrote no {view} view",
                            hint=_first_error_line(proc.stderr),
                            stderr=proc.stderr,
                        )
                    finished.append((staged, png))
                    renders[view] = png
                # Every view is moved only once all four exist. Replacing each
                # as it finishes would leave the LATER views reading the
                # EARLIER ones — the same model is re-parsed per view, so a
                # `surface(file = "renders/iso.png")` would see the freshly
                # written iso view from the front view onward, and the four
                # images would depict four different parts.
                #
                # A destination that is a directory is refused BEFORE the first
                # move. `os.replace` cannot replace one, and discovering that on
                # view 3 left views 1-2 fresh and 3-4 stale under a message
                # saying nothing was written — measured, and the exact mix this
                # batch exists to prevent (adversarial review of #230).
                blocked = [
                    png
                    for _, png in finished
                    # NOT `png.is_dir()`: that follows symlinks and `rename(2)`
                    # does not follow its destination, so a symlink pointing at
                    # a directory is replaced by the rename exactly as any
                    # other symlink is — measured. Refusing it turned a working
                    # render into a failure and called a symlink a directory
                    # (adversarial review of #234).
                    if (png.exists() or png.is_symlink()) and stat.S_ISDIR(png.lstat().st_mode)
                ]
                if blocked:
                    return BuildError(
                        f"the view artifacts cannot be moved into place: "
                        f"{', '.join(str(p) for p in blocked)} "
                        f"{'is a directory' if len(blocked) == 1 else 'are directories'}",
                        origin="environment",
                        hint="remove it, or render into a different output directory — "
                        "nothing in the output directory has been touched",
                    )
                # And if one fails anyway — a full disk, a permission change
                # under us — the count is reported rather than the caller being
                # told nothing was written while half the set is new. There is
                # no atomic rename of four files; the honest thing is to say
                # which state the directory is actually in.
                for moved, (staged, png) in enumerate(finished):
                    try:
                        staged.replace(png)
                    except OSError as exc:
                        # Nothing moved yet is its own sentence, and carries the
                        # pre-flight's guarantee. "the 0 view artifact(s)
                        # already moved ... are from this run and the rest are
                        # not" described a corrupted directory that was in fact
                        # untouched -- the thesis inverted, in the branch added
                        # to stop exactly that (adversarial review of #234).
                        if moved == 0:
                            return BuildError(
                                f"no view artifact could be moved into {renders_dir}: "
                                f"replacing {png.name} failed ({exc.strerror})",
                                origin="environment",
                                hint="nothing in the output directory has been touched",
                            )
                        return BuildError(
                            f"the {moved} view artifact(s) already moved into {renders_dir} "
                            f"are from this run and the rest are not: replacing {png.name} "
                            f"failed ({exc.strerror})",
                            origin="environment",
                        )
            return renders
        except OSError as exc:
            return BuildError(
                f"could not write the view artifacts to {renders_dir}: {exc.strerror}",
                origin="environment",
            )
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


_NOISE = re.compile(
    r"^(Geometries in cache|Geometry cache size|CGAL Polyhedrons in cache|"
    r"CGAL cache size|Total rendering time|Rendering finished|"
    r"Top level object is|Contours:|"
    r"Vertices:|Halfedges:|Edges:|Halffacets:|Facets:|Volumes:|Simple:)"
)
"""Bookkeeping OpenSCAD prints before (and instead of) its diagnosis: cache
statistics on both engine versions, and the geometry-summary block that can
accompany the exit-0-no-geometry branch. Both binaries print `Geometries in
cache:` FIRST, so the first-wins fallback below handed an agent a cache
statistic as the hint — confidently irrelevant — while `Current top level
object is empty.` sat one line down (#37)."""


def _signal_lines(stderr: str) -> list[str]:
    """stderr with blanks and known bookkeeping removed, in order.

    Factored out so the origin and the hint filter noise through ONE list.
    `_first_error_line` then applies its ERROR/WARNING preference over these;
    `_is_unknown_option` takes the first, deliberately not the preference.
    """
    return [
        line.strip()
        for line in stderr.splitlines()
        if line.strip() and not _NOISE.match(line.strip())
    ]


_UNKNOWN_OPTION = re.compile(r"unrecognised option|unrecognized option|unknown option", re.I)
"""The engine rejecting a FLAG rather than the source.

Measured on the apt 2021.01 binary, which is what Debian and Ubuntu ship:

    $ openscad --backend=CGAL -o out.stl m.scad
    unrecognised option '--backend=CGAL'
    Usage: openscad [options] file.scad

Both British and American spellings are matched because the message comes from
boost::program_options in one version and the engine's own parser in another,
and neither is a spelling this project controls. Deliberately narrow: it names
only the failure mode where the ENGINE could not accept what partspec passed,
which is the whole class that must not be blamed on the part."""


def _is_unknown_option(stderr: str) -> bool:
    """Whether the engine rejected an option rather than the model.

    Shares `_first_error_line`'s NOISE FILTER — one list, kept in step by being
    one list — and then takes the first line, which is not what that function
    does. Reading `lines[0]` raw let the two disagree silently: the cache
    statistics both binaries print FIRST would push a rejection to line two,
    reverting the classification to `model` while the hint still named the
    option, which is the bug this branch fixes.

    But delegating to `_first_error_line` wholesale was worse, and briefly
    shipped on this branch: it prefers a line containing `ERROR`/`WARNING`
    ANYWHERE in stderr, so a 58-line usage dump came into scope. Today's
    2021.01 dump survives on letter case alone — it contains "errors)" and
    "Stop on the first warning", both lowercase — and an engine that
    capitalised either word would flip the origin back to `model` with nothing
    to show for it (PR #160 review, R2). A CLI-level rejection is printed
    before any compilation output, so the first signal line is the whole
    question and the dump is never in scope.

    Coupling the filter is the property, not immunity to noise. A line `_NOISE`
    does not know — a Mesa/libEGL warning on a headless box, say — still
    displaces the rejection, and displaces the hint with it, so the report stays
    self-consistent and `build_stderr` carries the whole text either way. The
    fix for such a line is to teach `_NOISE` about it once it is observed;
    guessing at the list here would be a second filter to keep in step.

    One line, not a window. Anything looser reads the `Usage:` dump that
    follows, which lists every allowed option and on some builds contains this
    very phrase: a three-line window classified `ERROR: Parser error` plus a
    usage dump as an engine fault, which is an ordinary compile failure blamed
    on the machine. Both directions are pinned by test.
    """
    lines = _signal_lines(stderr)
    return bool(lines) and _UNKNOWN_OPTION.search(lines[0]) is not None


def _first_error_line(stderr: str) -> str | None:
    """The engine's own diagnosis, preferring its ERROR/WARNING lines.

    The fallback is the point. Matching only ERROR/WARNING silently discarded
    every failure OpenSCAD reports in its own voice — `unrecognised option
    '--backend=CGAL'`, which is exactly what a 2021.01 engine says to a contract
    written against a newer one, reduced to `openscad exited 1` and no hint.
    A failure that is visible but unexplained sends a reader off to guess, which
    is a quieter version of the thing this tool is against.

    First-wins, deliberately: on the 2021.01 `--backend` failure the reason is
    printed first and a long `Allowed options:` usage dump follows, so last-wins
    would return a fragment of the dump. Known noise is filtered before
    selection instead, which needs no special-casing of any message.
    """
    lines = _signal_lines(stderr)
    for line in lines:
        if "ERROR" in line or "WARNING" in line:
            return line
    # CLI-level failures are diagnosed before any compilation output, so the
    # first line is the reason and everything after it is a usage dump.
    return lines[0] if lines else None


# --------------------------------------------------------------------------
# The include closure — what a report's provenance actually has to cover
# --------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"\b(?:include|use)\s*<([^>\n]*)>")

_EXTERNAL_DATA_RE = re.compile(
    # Modules and functions whose NAME is the claim that a file is read.
    r"\b(?:import_stl|import_dxf|import_off|import|surface"
    r"|dxf_linear_extrude|dxf_rotate_extrude|dxf_dim|dxf_cross)\s*\("
    # And the two whose name is not: an extrude reads a DXF only when it is
    # given `file=`, and matching the bare name would fire on nearly every
    # OpenSCAD model ever written.
    r"|\b(?:linear_extrude|rotate_extrude)\s*\([^)]*\bfile\s*="
)
"""Every way an OpenSCAD source reads a data file, not just the modern two.

`import()` was the whole pattern until an adversarial review of #187 found
`import_stl(` walking through it: `\\s*\\(` demands the paren straight after
`import`, and 2021.01 — the version this tier targets, and what Debian and
Ubuntu ship — still executes the deprecated spelling, warning and all. Missing
it made `reads_external_data` false for a file the render genuinely reads, so
the closure claimed a completeness it did not have (SPEC-report §8.3), and the
`measure --out` guard that asks this question was answered wrongly: three runs
against `import_stl("input.stl")` ate their own input and reported
`[30,10,10]`, `[50,10,10]`, `[70,10,10]`, each at exit 0.

The deprecated `dxf_*` forms are matched by name because a file is all they
take. `linear_extrude`/`rotate_extrude` are matched only with `file=`, since
the overwhelming majority of their uses extrude a child and read nothing."""


# make-style depfile tokens: runs of non-space, with `\ ` escaping a space.
# A trailing `\` before a newline is a line continuation and matches neither
# alternative, so continuations terminate a token rather than joining into one.
_DEPS_FLAG_OK = True
"""Whether this process has seen the engine accept `-d`.

Set false the first time a build is rejected for it, and that build is retried
without it. `-d` has been in OpenSCAD since long before 2021.01 and is in
current master, so this is expected to stay true — but a `PARTSPEC_OPENSCAD`
pin can name any binary, and the alternative to degrading is that EVERY render
fails on such a build, under a hint telling the reader to drop a contract
argument they never passed. Provenance is not worth a render.
"""


_DEPS_RE = re.compile(r"(?<![\w-])(?:-d|--d)(?![\w-])")
"""The `-d` flag as an engine's REJECTION LINE names it, never as its usage does.

Matched against `_signal_lines(...)[0]` alone, for the reason
`_is_unknown_option` gives at length and this constant re-learned the hard way:
a rejection is followed by a `Usage:` dump listing every allowed option, and on
2021.01 line 46 of it reads `-d [ --d ] arg  deps_file -generate a dependency
file for make`. Searching the whole of stderr therefore matched on EVERY
rejected option — `--backend=CGAL` on 2021.01 is the ordinary case — so any
such build silently disabled depfiles for the rest of the process. Caught by
the suite, not by review, and pinned below.

`deps_file` is deliberately not in the pattern: it appears only in that dump's
prose, never in a rejection.
"""


_DEP_TOKEN = re.compile(r"(?:[^\s\\]|\\.)+")


@dataclass(frozen=True, slots=True)
class RenderDeps:
    """What the engine says it actually read, from `openscad -d`.

    `Closure` is what a *static* reader can see; this is what the render
    resolved. The two are complementary and neither supersedes the other —
    measured on 2021.01, a **missing** `include` is not listed here at all (the
    depfile names what was successfully opened, never what was requested), so
    `include_closure`'s regex stays the only thing that knows an include was
    asked for. What this adds is the half no static reader can have: a
    `surface(file = ...)` target, and an `import(names[i])` whose path is
    computed at render time.
    """

    state: str
    """`complete`, `partial` or `absent` — and `absent` MUST NOT read as `complete`.

    - `complete` — the engine exited 0 and wrote a depfile: its resolved input
      set, in full.
    - `partial` — the engine failed but wrote a depfile: what it had opened
      before it stopped, which is a floor and not the whole set.
    - `absent` — no depfile at all. Nothing may be concluded from it; in
      particular it is not "the render read nothing", which is what an empty
      `files` under any other state would mean.

      **Which failures land here is engine-version-dependent, so do not key on
      the cause.** Measured: 2021.01 writes nothing for a syntax error (exit 1,
      no file) while the 2026.08.01 snapshot writes one anyway, making the same
      broken model `absent` on one engine and `partial` on the other. That is
      F13, and the first cut of this feature shipped a test asserting the
      2021.01 answer as universal. What holds on both is the only thing worth
      asserting: a failed render is never `complete`.
    """

    files: tuple[Path, ...] = ()
    """Resolved dependencies, sorted. Absolute, except where noted in `missing`."""

    missing: tuple[Path, ...] = ()
    """Listed dependencies that do not exist on disk.

    Not a contradiction and not a parse failure: a **missing** `import()` target
    is listed by its resolved absolute path (measured), which is strictly more
    than the silence partspec had before — it names a build input the model
    wanted and did not get. Anything hashing this list must treat `ENOENT` as a
    normal outcome.
    """


def _parse_depfile(text: str, cwd: Path) -> tuple[Path, ...]:
    """Resolved dependencies from a make-style depfile, entry file included.

    The target is everything up to the first colon and is dropped. Paths are
    resolved against `cwd` because they are not uniformly absolute: OpenSCAD
    emits resolved dependencies absolute but **echoes the invoked source as it
    was given**, and partspec passes `source.path` unresolved (`contract.py`
    builds `Source` with a bare `Path(path)`), so a contract saying
    `openscad("part.scad")` puts a relative entry in this list.
    """
    _, _, body = text.partition(":")
    out: set[Path] = set()
    for match in _DEP_TOKEN.finditer(body):
        token = re.sub(r"\\(.)", r"\1", match.group())
        if token:
            out.add((cwd / token).resolve())
    return tuple(sorted(out))


def _read_depfile(path: Path, *, ok: bool) -> RenderDeps:
    """Grade a render's depfile. `ok` is whether the engine exited zero."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return RenderDeps(state="absent")
    files = _parse_depfile(text, Path.cwd())
    return RenderDeps(
        state="complete" if ok else "partial",
        files=files,
        missing=tuple(f for f in files if not f.exists()),
    )


@dataclass(frozen=True, slots=True)
class Closure:
    """Every source file a render reads, and an honest account of the rest.

    A digest over the entry file alone is not an identifier for the build. The
    gridfinity bin in the dogfood corpus is one file of **sixteen**; edit a
    helper three levels down and the part changes while the entry file's hash
    does not. That is the same class of silent drift as F13, and `diff` would
    have inherited it.
    """

    files: tuple[Path, ...]
    """Resolved members, entry file included, in sorted order."""

    unresolved: tuple[str, ...] = ()
    """`include`/`use` targets that could not be found on any search path."""

    reads_external_data: bool = False
    """True if `import()` or `surface()` appears anywhere in the closure.

    Those name STL/DXF/DAT files that are genuinely build inputs, and this does
    not resolve them — the path may be computed at render time, so no static
    reader can. Recorded rather than ignored: the closure must not claim to be
    complete when something it cannot see may have changed.
    """

    @property
    def partial(self) -> bool:
        """True when the closure is known not to cover every input."""
        return bool(self.unresolved) or self.reads_external_data

    @property
    def unresolved_reason(self) -> str | None:
        """Why a *pre-render* guard must refuse, phrased for one — None if it need not.

        One spelling, because two guards ask this question: the file-mode
        `--out` refusal in `cli._measure_resolved` and the source-directory
        one in `render`. A reader who trips both must not be told the same
        thing two ways, and the phrasing is the part of a refusal most likely
        to drift when it is written twice.

        **Narrower than `partial` since #263, and the difference is which
        signal can answer later.** This used to refuse on either arm of
        `partial`, because before the depfile nothing could ever do better. An
        `import()`/`surface()` target now is named in the engine's own
        dependency output, so refusing before the render refuses a case that
        becomes decidable seconds later — that arm moved to
        `_wrote_over_an_input`, which answers it exactly. An **unresolved
        include** is named nowhere: the depfile lists what was opened, never
        what was asked for (`RenderDeps`), so no later signal supersedes this
        one and refusing early is the only honest answer there is.
        """
        if self.unresolved:
            return f"has include(s) partspec could not resolve ({', '.join(self.unresolved)})"
        return None


_ASSIGNMENT = re.compile(r"([A-Za-z_$][A-Za-z0-9_]*)\s*=")
_DIRECTIVE = re.compile(r"\b(?:include|use)\s*<[^>]*>")


def top_level_variables(entry: Path) -> set[str]:
    """Names assignable by `-D`, across the include closure.

    OpenSCAD's `-D name=value` overrides a **top-level** variable. If no such
    variable exists it is not an error there — the define is simply accepted and
    dropped, and the render proceeds with the file's own defaults.

    Only depth-zero assignments count: `bore_d` inside a module body is a local
    and `-D bore_d=...` does not reach it. Comments and string interiors are
    blanked first, so `// bore_d = 8` and `x = "wall = 2"` are not mistaken for
    declarations — a false positive here would re-open the hole rather than
    merely widen it.

    Read across the whole closure rather than the entry alone, because a
    library's parameters routinely live in an included `standard.scad`.
    """
    names: set[str] = set()
    for path in include_closure(entry).files:
        try:
            text = _strip_noise(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue  # provenance is best-effort; see include_closure
        # `include <a.scad>` carries no semicolon, so it would otherwise merge
        # with the statement after it and hide that statement's assignment.
        text = _DIRECTIVE.sub(" ", text)
        depth = 0
        for statement in text.replace("\n", " ").split(";"):
            head: list[str] = []
            for ch in statement:
                if ch in "{([":
                    depth += 1
                elif ch in "})]":
                    depth = max(depth - 1, 0)
                elif depth == 0:
                    head.append(ch)
            if depth == 0:
                match = _ASSIGNMENT.match("".join(head).strip())
                if match:
                    names.add(match.group(1))
    return names


def unbound_parameters(entry: Path, params: dict[str, Any]) -> list[str]:
    """Declared parameters that no top-level variable would receive.

    Special variables (`$fn`, `$fa`, `$fs`) are exempt: they are built in, so a
    file need not assign one for `-D` to take effect.
    """
    declared = top_level_variables(entry)
    return sorted(n for n in params if not n.startswith("$") and n not in declared)


def _strip_noise(text: str) -> str:
    """Blank out comments and string interiors before scanning.

    Strings must be *tracked* rather than skipped, or a `//` inside one starts a
    comment that swallows the rest of the line. Their contents must not be
    scanned, or `x = "include <a.scad>"` is read as a dependency and reported
    unresolved — a false alarm, which is its own kind of dishonesty.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def library_path() -> list[Path]:
    """Where OpenSCAD looks for a library, after the including file's directory."""
    dirs = [Path(p) for p in os.environ.get("OPENSCADPATH", "").split(os.pathsep) if p]
    dirs.append(Path.home() / ".local/share/OpenSCAD/libraries")
    dirs.append(Path("/usr/share/openscad/libraries"))
    return dirs


def include_closure(entry: Path) -> Closure:
    """Walk `include`/`use` transitively from `entry`.

    Resolution follows OpenSCAD's own rule: relative to the directory of the
    file containing the statement — *not* the top-level file — then the library
    path. Cycles are legal in OpenSCAD and terminate here on the visited set.

    A file that cannot be read is skipped rather than raised on: this is
    provenance, and failing a check because provenance was awkward would be the
    tail wagging the dog.
    """
    entry = entry.resolve()
    seen: set[Path] = {entry}
    unresolved: set[str] = set()
    external = False
    queue: deque[Path] = deque([entry])
    search = library_path()

    while queue:
        current = queue.popleft()
        try:
            text = _strip_noise(current.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if _EXTERNAL_DATA_RE.search(text):
            external = True
        for raw in _INCLUDE_RE.findall(text):
            ref = raw.strip()
            if not ref:
                continue
            found = next(
                (c for c in ((b / ref) for b in (current.parent, *search)) if c.is_file()), None
            )
            if found is None:
                unresolved.add(ref)
            elif (resolved := found.resolve()) not in seen:
                seen.add(resolved)
                queue.append(resolved)

    return Closure(
        files=tuple(sorted(seen)),
        unresolved=tuple(sorted(unresolved)),
        reads_external_data=external,
    )


def version(executable: str | None = None) -> str:
    """Report the engine version, for the report's provenance block."""
    exe = executable or find_executable()
    if exe is None:
        return "unknown"
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    # OpenSCAD prints its version to stderr.
    text = (proc.stderr or proc.stdout).strip()
    return text.replace("OpenSCAD version", "").strip() or "unknown"
