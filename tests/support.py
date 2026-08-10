"""Shared test helpers."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from partspec.backend import Unsupported
from partspec.engines import openscad
from partspec.status import Measurement

__all__ = [
    "FIXTURES",
    "check_of",
    "decode_png",
    "forced_open_solid",
    "measured",
    "needs_build123d",
    "needs_mesh",
    "needs_openscad",
    "openscad_supports_backend_flag",
    "refused",
    "scad_target",
    "sew_into_solid",
]

FIXTURES = Path(__file__).parent / "fixtures"

OPENSCAD = openscad.find_executable()

needs_openscad = pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not installed")
"""Skip when there is no engine — but see `conftest.py`, which turns that skip
into a hard failure under `PARTSPEC_REQUIRE_ENGINES=1`. A skip is the right
local behaviour and the wrong CI behaviour, and the difference is worth a
switch rather than a habit."""


def openscad_supports_backend_flag() -> bool:
    """Whether the installed engine has `--backend` at all.

    2021.01 does not: render backends arrived later. This is a real portability
    boundary rather than a quirk — 2021.01 is what Debian and Ubuntu ship — so
    tests branch on it and assert both sides.
    """
    if OPENSCAD is None:
        return False
    proc = subprocess.run([OPENSCAD, "--help"], capture_output=True, text=True, check=False)
    return "--backend" in proc.stdout + proc.stderr


def measured(result: Measurement | Unsupported) -> Measurement:
    """Assert a primitive answered, and narrow the type for the type checker.

    Worth an assertion rather than a cast. Several primitives now refuse when
    their precondition fails, so "this returned a number" is a real claim about
    the fixture — and a test that silently type-ignored a refusal would pass
    while measuring nothing.
    """
    assert not isinstance(result, Unsupported), f"unexpectedly refused: {result.reason}"
    return result


def refused(result: Measurement | Unsupported) -> Unsupported:
    """Assert a primitive refused, and narrow the type."""
    assert isinstance(result, Unsupported), f"expected a refusal, got {result!r}"
    return result


needs_build123d = pytest.mark.skipif(
    importlib.util.find_spec("build123d") is None, reason="occt extra not installed"
)
needs_mesh = pytest.mark.skipif(
    importlib.util.find_spec("trimesh") is None, reason="mesh extra not installed"
)
"""Markers rather than in-body `importorskip`/`pytest.skip`.

The suite spelled these five different ways — `importorskip` in 38 bodies,
`find_spec` skipifs in three idioms, and six hand-rolled `if OPENSCAD is None:
pytest.skip(...)`. A body-level skip is also invisible to collection, which
makes `conftest.py`'s `PARTSPEC_REQUIRE_ENGINES` guard harder to reason about.
"""


def scad_target(
    tmp_path: Path, *, source: str | Path, claims: str = "", part_id: str = "subject"
) -> str:
    """The OpenSCAD equivalent. `source` may name a file in tests/fixtures."""
    src = Path(source)
    src = src if src.is_absolute() else FIXTURES / src
    name = src.name
    shutil.copy(src, tmp_path / name)
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part({part_id!r}, openscad({name!r}))\n"
        f"{claims}"
        "    return p\n"
    )
    return f"{spec}:make"


def check_of(out: Path, kind: str) -> dict:
    """The one check of `kind` from the report written under `out`.

    Replaces the eight report reads that selected a check by kind through a
    `next(c for c in ... if c["kind"] == ...)` generator. Thirty-eight
    hand-written reads remain; they want the whole document, and #153 tracks
    whichever are worth a helper.

    Raises rather than returning None: an absent check is a test bug, and
    `StopIteration` inside a generator expression reads as a confusing error.
    """
    doc = json.loads((out / "report.json").read_text())
    matching = [c for c in doc["checks"] if c["kind"] == kind]
    assert matching, (
        f"no {kind!r} check in the report; kinds present: {[c['kind'] for c in doc['checks']]}"
    )
    assert len(matching) == 1, f"{len(matching)} checks of kind {kind!r}; name one by id instead"
    return matching[0]


def sew_into_solid(faces):
    """Sew loose faces and force the result into a `Solid`, valid or not.

    The idiom three test files spelled out: it is how you build a shape the
    kernel would never produce, which is the only way to test what happens
    when one arrives. Needs build123d, so callers must be marked.
    """
    import build123d as bd
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeSolid,  # pyright: ignore[reportAttributeAccessIssue]
        BRepBuilderAPI_Sewing,  # pyright: ignore[reportAttributeAccessIssue]
    )
    from OCP.TopoDS import TopoDS  # pyright: ignore[reportAttributeAccessIssue]

    sew = BRepBuilderAPI_Sewing()
    for face in faces:
        sew.Add(face.wrapped)
    sew.Perform()
    return bd.Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew.SewedShape())).Solid())


def forced_open_solid():
    """Five faces of a box sewn into a "solid" — ill-formed on purpose, and
    the executed STEP degrader: the reader's healing drops it entirely.

    Two files built this identically; a third sews a tetrahedron, which is a
    different fixture sharing only the idiom above.
    """
    import build123d as bd

    return sew_into_solid(bd.Box(10, 10, 10).faces()[:5])


def decode_png(path: Path) -> tuple[int, int, bytes]:
    """A written PNG's `(width, height, rgb_bytes)`.

    Four copies of this walk existed — three in `test_raster.py`, one inside
    `test_cli._cut_pixels` which also reimplemented the shade formula.

    **For PNGs written by `partspec.raster.write_png` only.** That writer emits
    filter 0 on every row, which is what makes a decoder this short correct.
    OpenSCAD's writer uses libpng's adaptive filtering — measured on real
    scad-tier output: `{1: 277, 2: 350, 4: 173}` across one image's rows — so
    this refuses rather than misdecoding it. The scad tier's `--section` path
    is safe because the cut is rasterized by partspec, not by OpenSCAD.

    Deliberately not `partspec.vdiff.read_png`: a test that decoded with the
    same code the product decodes with would prove only self-consistency.
    """
    import struct
    import zlib

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    # The stride below assumes 8-bit truecolour RGB; without this check any
    # other format decodes to plausible-looking garbage.
    assert (data[24], data[25], data[28]) == (8, 2, 0), (
        f"{path.name} is not non-interlaced 8-bit truecolour RGB"
    )

    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length

    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = [raw[y * stride : (y + 1) * stride] for y in range(height)]
    assert all(row[0] == 0 for row in rows), (
        f"{path.name} uses PNG row filters. partspec's own writer emits filter 0 on "
        "every row; OpenSCAD's does not, and this decoder is only for the former"
    )
    return width, height, b"".join(row[1:] for row in rows)
