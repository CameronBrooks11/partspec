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

import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backend import BuildError

__all__ = ["OpenSCADSource", "find_executable", "render", "scad_literal"]

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


def find_executable() -> str | None:
    """Locate the openscad binary, preferring a nightly AppImage if present."""
    nightly = Path.home() / "Applications" / "openscad" / "OpenSCAD-nightly.AppImage"
    if nightly.is_file():
        return str(nightly)
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
    for line in stderr.splitlines():
        if "ERROR" in line or "WARNING" in line:
            return line.strip()
    return None


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
