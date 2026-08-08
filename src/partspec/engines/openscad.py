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
        with open(fd, "w", encoding="utf-8") as fh:
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


def render(
    source: OpenSCADSource, out_dir: Path, *, timeout_s: float | None = DEFAULT_TIMEOUT_S
) -> Path | BuildError:
    """Render to binary STL, returning the path or a BuildError.

    Binary STL specifically: lib3mf cannot read ASCII STL, and OpenSCAD 2021.01
    defaults to ASCII. Choosing the format explicitly means the export does not
    silently change meaning with the installed version.

    `timeout_s` here is already resolved: a number is the bound, None is
    unbounded (the explicit `--timeout 0` waiver). The None-means-default rule
    lives one layer up, in `effective_timeout`.
    """
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

    # The export path is deterministic, so a previous run's mesh is sitting there
    # before this one starts. The guards below ask whether the file exists and is
    # non-empty — questions the *stale* file answers just as well, so an
    # invocation that exits 0 without writing would measure the last run's part
    # and report it as this one's. Removing it first makes the checks mean what
    # they read as, and makes a failed render leave nothing behind for a later
    # reader to pick up.
    try:
        stl.unlink(missing_ok=True)
    except OSError as exc:
        # A stale artifact in a directory this run cannot write is the same
        # environment fault as an uncreatable one, and must not traceback.
        return BuildError(
            f"could not clear the previous artifact in {out_dir}: {exc.strerror}",
            origin="environment",
        )

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
        cmd = [
            executable,
            "--export-format",
            "binstl",
            *backend_args,
            "-o",
            str(stl),
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
            return BuildError(
                f"openscad exited {proc.returncode}",
                hint=_first_error_line(proc.stderr),
                stderr=proc.stderr,
            )
        # OpenSCAD exits 0 on some degenerate input while writing nothing useful,
        # so the artifact is checked rather than the exit code trusted.
        if not stl.is_file() or stl.stat().st_size == 0:
            return BuildError(
                "openscad exited 0 but produced no geometry",
                hint=_first_error_line(proc.stderr),
                stderr=proc.stderr,
            )
        return stl
    finally:
        if scratch is not None:
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
    lines = [
        line.strip()
        for line in stderr.splitlines()
        if line.strip() and not _NOISE.match(line.strip())
    ]
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
_EXTERNAL_DATA_RE = re.compile(r"\b(?:import|surface)\s*\(")


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
