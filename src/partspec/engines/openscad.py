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
import subprocess
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


def _output_over_an_input(source: OpenSCADSource, out_dir: Path, stl: Path) -> BuildError | None:
    """Refuse when the artifact would land on a file that may be an input.

    Building in a scratch directory keeps the MEASUREMENT honest — the engine
    reads whatever inputs are on disk, because nothing has been removed — but
    the move into place still writes `<stem>.stl` over whatever holds that
    name, and where the model reads that file the NEXT run measures something
    else. #208's repro is exactly that: `part.scad` imports `part.stl`, a
    destination of the source's own directory derives `part.stl`, and after
    the run the input is the output. Under `check` it was worse than a wrong
    number — a PASS verdict on geometry that was not the part.

    `Closure.reads_external_data` is a bool by design: a data path may be
    computed at render time, so no static reader can resolve it. So this
    cannot know WHICH files are inputs and has to be conservative, the same
    position the file-mode `--out` guard takes (`cli._measure_resolved`). The
    narrowest condition that catches the repro is all three of:

    1. the destination is the directory the source's relative
       `import()`/`surface()` paths resolve against — its own;
    2. the closure is partial, so inputs exist that partspec cannot enumerate;
    3. `<stem>.stl` is already there to be destroyed.

    Each clause is load-bearing in the direction of NOT over-refusing. Without
    (1) the second run of any external-data model against the default
    `outputs/<slug>` finds run 1's own artifact there and is refused — the
    ordinary path, broken. Without (2) any model rendering twice into its own
    directory is refused on the second run. Without (3) a first run into the
    source directory is refused over a file that does not exist.

    It therefore **under-refuses**, deliberately: `--out sub` where the model
    imports `sub/part.stl` still loses the file. What it does not lose there is
    the answer — the scratch build reads that input before anything replaces it
    — so the residue is one destroyed file rather than a confident wrong
    measurement, which is the cheaper half. Over-refusing costs every user of a
    legitimate output directory; under-refusing costs a rare corner one file.
    Scanning the closure for the destination's NAME was the precise alternative
    considered and rejected: it resolves nothing when the path is computed,
    which is the case `reads_external_data` exists to admit, so it would refuse
    in the easy case and stay silent in the hard one.
    """
    if out_dir.resolve() != source.path.parent.resolve() or not stl.exists():
        return None
    reason = include_closure(source.path).partial_reason
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


def render(
    source: OpenSCADSource, out_dir: Path, *, timeout_s: float | None = DEFAULT_TIMEOUT_S
) -> Path | BuildError:
    """Render to binary STL, returning the path or a BuildError.

    Binary STL specifically: lib3mf cannot read ASCII STL, and OpenSCAD 2021.01
    defaults to ASCII. Choosing the format explicitly means the export does not
    silently change meaning with the installed version.

    **Nothing in `out_dir` is touched until there is an artifact to put there.**
    The engine writes into a scratch directory under `out_dir` and the result
    is moved into place with `os.replace`, so the destination holds the old
    file or the new one and never neither. It is the shape `cli._build_to_file`
    settled on for the filename form of `--out` — the directory form never got
    it (#208) — and the one SPEC-backend §5 step 1 already spells the
    invocation with (`-o <tmp>.stl`), though the spec is illustrating the
    command rather than requiring the temporary.

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
    import tempfile

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

    refusal = _output_over_an_input(source, out_dir, stl)
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
            cmd = [
                executable,
                "--export-format",
                "binstl",
                *backend_args,
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
                )
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

    scratch = out_dir / f"{stl.stem}.section.scad"
    out = out_dir / f"{stl.stem}.section.stl"
    try:
        out.unlink(missing_ok=True)  # same stale-artifact rule as render()
    except OSError as exc:
        return BuildError(
            f"could not clear the previous artifact in {out_dir}: {exc.strerror}",
            origin="environment",
        )
    scratch.write_text(
        "difference() {\n"
        f"  import({_json.dumps(str(stl.resolve()))});\n"
        f"  translate([{mins[0]!r}, {mins[1]!r}, {mins[2]!r}])"
        f" cube([{sizes[0]!r}, {sizes[1]!r}, {sizes[2]!r}]);\n"
        "}\n"
    )
    try:
        try:
            proc = subprocess.run(
                [executable, "--export-format", "binstl", "-o", str(out), str(scratch)],
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
        if not out.is_file() or out.stat().st_size == 0:
            return BuildError(
                f"the {plane} section at {offset:g} mm discards the whole part",
                hint=_first_error_line(proc.stderr),
            )
        return out
    finally:
        scratch.unlink(missing_ok=True)


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
    source: OpenSCADSource, out_dir: Path, *, timeout_s: float | None = DEFAULT_TIMEOUT_S
) -> dict[str, Path] | BuildError:
    """Render the canonical views to PNG, or say exactly why not.

    The STL is rendered first, deliberately: it carries the guards this path
    must not re-invent — unbound `-D` detection, the empty-geometry refusal —
    so a cut that consumed the part is a `BuildError` here, never four blank
    frames that *look* like a rendered part. It also supplies the bounding box
    the camera framing derives from. The images carry no verdict: rendering
    never substitutes for measurement.
    """
    stl = render(source, out_dir, timeout_s=timeout_s)
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
    try:
        for view, rot in VIEWS.items():
            png = out_dir / "renders" / f"{view}.png"
            png.parent.mkdir(parents=True, exist_ok=True)
            png.unlink(missing_ok=True)  # same stale-artifact rule as the STL
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
                str(png),
                *defines,
                str(render_path),
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout_s, check=False
                )
            except subprocess.TimeoutExpired:
                return BuildError(f"openscad timed out after {timeout_s}s", origin="environment")
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
            if not png.is_file() or png.stat().st_size == 0:
                return BuildError(
                    f"openscad exited 0 but wrote no {view} view",
                    hint=_first_error_line(proc.stderr),
                    stderr=proc.stderr,
                )
            renders[view] = png
        return renders
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
    def partial_reason(self) -> str | None:
        """Why it is partial, phrased for a refusal — None when it is not.

        One spelling, because two guards now ask this question: the file-mode
        `--out` refusal in `cli._measure_resolved` and the source-directory
        one in `render`. A reader who trips both must not be told the same
        thing two ways, and the phrasing is the part of a refusal most likely
        to drift when it is written twice.
        """
        if self.reads_external_data:
            return "reads external data (import()/surface())"
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
