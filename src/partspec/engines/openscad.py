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
import tempfile
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backend import BuildError

__all__ = [
    "Closure",
    "OpenSCADSource",
    "find_executable",
    "include_closure",
    "render",
    "scad_literal",
]

DEFAULT_TIMEOUT_S = 300


@dataclass(frozen=True, slots=True)
class OpenSCADSource:
    """An OpenSCAD file plus the parameters to build it with."""

    path: Path
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None
    """When set, parameters are passed as arguments to a call to this module,
    appended to a throwaway copy of the source. Otherwise they override
    top-level variables via -D. The source file is never modified either way."""

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
    """A throwaway copy of the source with a call to `method` appended.

    Adopted from PartCAD, which does the same thing for the same reason: it lets
    a parameterised module be invoked without the source file having a top-level
    call, and without ever mutating the file on disk.
    """
    body = source.read_text(encoding="utf-8")
    args = ", ".join(f"{k} = {scad_literal(v)}" for k, v in params.items())
    newline = "" if body.endswith("\n") else "\n"
    return f"{body}{newline}{method}({args});\n"


def render(
    source: OpenSCADSource, out_dir: Path, *, timeout_s: int = DEFAULT_TIMEOUT_S
) -> Path | BuildError:
    """Render to binary STL, returning the path or a BuildError.

    Binary STL specifically: lib3mf cannot read ASCII STL, and OpenSCAD 2021.01
    defaults to ASCII. Choosing the format explicitly means the export does not
    silently change meaning with the installed version.
    """
    executable = find_executable()
    if executable is None:
        return BuildError(
            "openscad not found on PATH",
            hint="install the stable package, or the nightly AppImage via workstation-configs",
        )
    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / f"{source.path.stem}.stl"

    # The export path is deterministic, so a previous run's mesh is sitting there
    # before this one starts. The guards below ask whether the file exists and is
    # non-empty — questions the *stale* file answers just as well, so an
    # invocation that exits 0 without writing would measure the last run's part
    # and report it as this one's. Removing it first makes the checks mean what
    # they read as, and makes a failed render leave nothing behind for a later
    # reader to pick up.
    stl.unlink(missing_ok=True)

    scratch: Path | None = None
    try:
        if source.method:
            fd, tmp_name = tempfile.mkstemp(suffix=".scad", dir=source.path.parent)
            scratch = Path(tmp_name)
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(_method_call_source(source.path, source.method, source.params))
            render_path, defines = scratch, []
        else:
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
            return BuildError(f"openscad timed out after {timeout_s}s")
        except OSError as exc:
            # A mistyped PARTSPEC_OPENSCAD reaches here. The pin is returned
            # as given rather than validated away, because silently falling
            # back to PATH would answer with an engine the user did not choose
            # — and the version is the part (F13). So it fails, by name.
            return BuildError(
                f"could not run the openscad binary at {executable!r}: {exc.strerror}",
                hint=f"{ENV_EXECUTABLE} is set to this path"
                if os.environ.get(ENV_EXECUTABLE)
                else None,
            )

        if proc.returncode != 0:
            return BuildError(
                f"openscad exited {proc.returncode}",
                hint=_first_error_line(proc.stderr),
            )
        # OpenSCAD exits 0 on some degenerate input while writing nothing useful,
        # so the artifact is checked rather than the exit code trusted.
        if not stl.is_file() or stl.stat().st_size == 0:
            return BuildError(
                "openscad exited 0 but produced no geometry",
                hint=_first_error_line(proc.stderr),
            )
        return stl
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def _first_error_line(stderr: str) -> str | None:
    """The engine's own diagnosis, preferring its ERROR/WARNING lines.

    The fallback is the point. Matching only ERROR/WARNING silently discarded
    every failure OpenSCAD reports in its own voice — `unrecognised option
    '--backend=CGAL'`, which is exactly what a 2021.01 engine says to a contract
    written against a newer one, reduced to `openscad exited 1` and no hint.
    A failure that is visible but unexplained sends a reader off to guess, which
    is a quieter version of the thing this tool is against.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
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
