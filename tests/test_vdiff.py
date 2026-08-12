"""The visual diff (#21): change shows, noise refuses, scale cannot hide.

The fixture renders real parts through the CLI once per module — a base run,
a byte-identical re-run, a moved-bore variant (the F16 shape: same silhouette
family, different internals/position), and a uniformly scaled variant (the
audit's pixel-invisible case).
"""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

import pytest
from support import needs_build123d, needs_numpy, optional_module

from partspec.cli import main
from partspec.vdiff import VdiffUsageError, read_png

np = optional_module("numpy")

_HIGHLIGHT = (230, 0, 126)


def _render(root: Path, name: str, body: str) -> Path:
    d = root / name
    d.mkdir()
    (d / "m.py").write_text(body)
    (d / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = d / "out"
    assert main(["render", f"{d / 'spec.py'}:make", "--out", str(out)]) == 0
    return out


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("vdiff-runs")
    bored = (
        "from build123d import Box, Cylinder, Location\n\n\ndef make_part():\n"
        "    return Box(20, 10, 5) - Location(({x}, 0, 0)) * Cylinder(2, 5)\n"
    )
    cube = "from build123d import Box\n\n\ndef make_part():\n    return Box({s}, {s}, {s})\n"
    return {
        "base": _render(root, "base", bored.format(x=5)),
        "again": _render(root, "again", bored.format(x=5)),
        "moved": _render(root, "moved", bored.format(x=2)),
        "cube20": _render(root, "cube20", cube.format(s=20)),
        "cube204": _render(root, "cube204", cube.format(s=20.4)),
    }


def _vdiff(capsys, old: Path, new: Path, out: Path) -> tuple[int, dict]:
    code = main(["vdiff", str(old), str(new), "--out", str(out)])
    return code, json.loads(capsys.readouterr().out)


@needs_build123d
def test_identical_geometry_is_an_empty_diff(runs, tmp_path: Path, capsys):
    """The acceptance criterion canonical framing bought: two runs of the
    same part, byte-equal images, zero magnitude, exit 0."""
    code, doc = _vdiff(capsys, runs["base"], runs["again"], tmp_path / "d")
    assert code == 0
    assert doc["outcome"] == "identical"
    assert doc["magnitude"] == 0.0
    assert all(entry["pixels_changed"] == 0 for entry in doc["views"].values())
    for entry in doc["views"].values():
        img = read_png(Path(entry["image"]))
        assert not (img == _HIGHLIGHT).all(axis=2).any(), "an empty diff highlights nothing"


@needs_build123d
def test_a_moved_bore_is_a_nonzero_diff_where_it_moved(runs, tmp_path: Path, capsys):
    """The F16 regression arm: a real geometry change must not diff to zero
    — and it localises: the bore moved in x, so top and iso change while
    front and right (where a z-bore was already invisible) stay equal."""
    code, doc = _vdiff(capsys, runs["base"], runs["moved"], tmp_path / "d")
    assert code == 1
    assert doc["outcome"] == "different"
    assert doc["magnitude"] > 0.0
    assert doc["views"]["top"]["fraction"] > 0.01
    assert doc["views"]["front"]["pixels_changed"] == 0
    img = read_png(Path(doc["views"]["top"]["image"]))
    assert (img == _HIGHLIGHT).all(axis=2).sum() == doc["views"]["top"]["pixels_changed"]


@needs_build123d
def test_pure_scale_is_caught_by_the_bbox_not_missed_by_the_pixels(runs, tmp_path, capsys):
    """The audit criterion verbatim: a 20 vs 20.4 mm cube renders
    byte-identical (framing scales with the part), and the recorded bbox is
    the witness — nonzero magnitude, the scale stated, measure referred."""
    code, doc = _vdiff(capsys, runs["cube20"], runs["cube204"], tmp_path / "d")
    assert code == 1
    assert doc["outcome"] == "different"
    assert all(entry["pixels_changed"] == 0 for entry in doc["views"].values())
    assert doc["bbox_delta_mm"] == pytest.approx(0.2)
    assert doc["magnitude"] > 0.0
    assert "measure" in doc["note"]


@needs_build123d
def test_differing_image_sizes_are_refused_not_rescaled(runs, tmp_path: Path, capsys):
    from partspec.raster import write_png

    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    write_png(clone / "renders" / "top.png", np.zeros((16, 16, 3), np.uint8))
    code, doc = _vdiff(capsys, runs["base"], clone, tmp_path / "d")
    assert code == 2
    assert doc["outcome"] == "indeterminate"
    assert "different sizes" in doc["refused"]["reason"]
    assert "rescaling" in doc["refused"]["reason"]


@needs_build123d
def test_a_cross_version_pair_is_refused_as_noise_not_scored_as_change(
    runs, tmp_path: Path, capsys
):
    """The audit's second criterion: 7.68% of pixels differ across engine
    versions for identical geometry — scoring that as change is the tool
    lying. Refused, naming both versions."""
    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    meta = json.loads((clone / "render.json").read_text())
    meta["engine"]["version"] = "9999.99"
    (clone / "render.json").write_text(json.dumps(meta))
    code, doc = _vdiff(capsys, runs["base"], clone, tmp_path / "d")
    assert code == 2
    assert doc["outcome"] == "indeterminate"
    assert "9999.99" in doc["refused"]["reason"]
    assert "7.68" in doc["refused"]["hint"]


@needs_build123d
def test_different_parts_are_refused(runs, tmp_path: Path, capsys):
    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    meta = json.loads((clone / "render.json").read_text())
    meta["part"]["id"] = "impostor"
    (clone / "render.json").write_text(json.dumps(meta))
    code, doc = _vdiff(capsys, runs["base"], clone, tmp_path / "d")
    assert code == 2
    assert "different parts" in doc["refused"]["reason"]


@needs_build123d
def test_mismatched_view_sets_are_refused(runs, tmp_path: Path, capsys):
    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    meta = json.loads((clone / "render.json").read_text())
    del meta["renders"]["iso"]
    (clone / "render.json").write_text(json.dumps(meta))
    code, doc = _vdiff(capsys, runs["base"], clone, tmp_path / "d")
    assert code == 2
    assert "view sets" in doc["refused"]["reason"]


def test_unusable_inputs_are_usage_not_a_verdict(tmp_path: Path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["vdiff", str(empty), str(empty)]) == 64
    assert "render.json" in capsys.readouterr().err
    assert main(["vdiff", str(tmp_path / "gone"), str(empty)]) == 64


@needs_build123d
def test_a_missing_image_is_refused_by_name(runs, tmp_path: Path, capsys):
    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    (clone / "renders" / "front.png").unlink()
    code, doc = _vdiff(capsys, runs["base"], clone, tmp_path / "d")
    assert code == 2
    assert "front.png" in doc["refused"]["reason"]


@needs_build123d
def test_a_sub_rounding_bbox_move_is_still_different(runs, tmp_path: Path, capsys):
    """PR #131 review, F1: the outcome derived from the display-ROUNDED
    magnitude while the note derived from the raw delta — a 5e-6 mm recorded
    move produced exit 0 'identical', a nonzero bbox_delta_mm, and a note
    asserting movement, in one document. The outcome now derives from the
    unrounded value and rounding can never flatten a real change to 0.0."""
    clone = tmp_path / "clone"
    shutil.copytree(runs["cube20"], clone)
    meta = json.loads((clone / "render.json").read_text())
    meta["render_bbox"]["max"][0] += 5e-6
    (clone / "render.json").write_text(json.dumps(meta))
    code, doc = _vdiff(capsys, runs["cube20"], clone, tmp_path / "d")
    assert code == 1
    assert doc["outcome"] == "different"
    assert doc["magnitude"] > 0.0
    assert doc["bbox_delta_mm"] > 0.0
    assert "note" in doc


@needs_build123d
def test_a_corrupt_image_is_unusable_input_not_a_partspec_failure(runs, tmp_path: Path, capsys):
    """PR #131 review, F2: a truncated PNG escaped as a zlib traceback at
    exit 4 — 'this is a partspec failure' — when the input is what is
    broken. Both corruption classes land at 64 with the reason."""
    clone = tmp_path / "clone"
    shutil.copytree(runs["base"], clone)
    png = clone / "renders" / "top.png"
    png.write_bytes(png.read_bytes()[:100])
    assert main(["vdiff", str(runs["base"]), str(clone), "--out", str(tmp_path / "d")]) == 64
    assert "not a decodable PNG" in capsys.readouterr().err

    bare = tmp_path / "bare"
    shutil.copytree(runs["base"], bare)
    meta = json.loads((bare / "render.json").read_text())
    del meta["part"]
    (bare / "render.json").write_text(json.dumps(meta))
    assert main(["vdiff", str(runs["base"]), str(bare), "--out", str(tmp_path / "d")]) == 64
    assert "not well-formed render artifacts" in capsys.readouterr().err

    # F6: truncated INSIDE the header — the signature alone, then nothing.
    # The IHDR unpack sat outside the decode guard and crashed at exit 4.
    header_only = tmp_path / "header"
    shutil.copytree(runs["base"], header_only)
    png = header_only / "renders" / "top.png"
    png.write_bytes(png.read_bytes()[:18])
    code = main(["vdiff", str(runs["base"]), str(header_only), "--out", str(tmp_path / "d")])
    assert code == 64
    assert "truncated in the header" in capsys.readouterr().err


@needs_build123d
def test_an_absent_bbox_witness_is_stated_never_scored(runs, tmp_path: Path, capsys):
    """PR #131 review, F3: a pre-draft-12 artifact carries no render_bbox,
    and the 20 vs 20.4 scale case read 'identical — bbox unchanged' with a
    fabricated bbox_delta_mm of 0.0. Absence now states itself: pixel change
    still proves difference; pixel identity without the witness refuses."""

    def strip(run: Path, name: str) -> Path:
        clone = tmp_path / name
        shutil.copytree(run, clone)
        meta = json.loads((clone / "render.json").read_text())
        del meta["render_bbox"]
        (clone / "render.json").write_text(json.dumps(meta))
        return clone

    # The fail-open case: pixel-identical scale change, no witness → refuse.
    code, doc = _vdiff(
        capsys, strip(runs["cube20"], "a"), strip(runs["cube204"], "b"), tmp_path / "d1"
    )
    assert code == 2
    assert doc["outcome"] == "indeterminate"
    assert doc["bbox_delta_mm"] is None, "never a fabricated 0.0"
    assert "render_bbox" in doc["bbox_unavailable"]
    assert "cannot be asserted" in doc["refused"]["reason"]

    # Pixel change is still proof, witness or no — with the gap stated.
    code, doc = _vdiff(capsys, strip(runs["base"], "c"), strip(runs["moved"], "e"), tmp_path / "d2")
    assert code == 1
    assert doc["outcome"] == "different"
    assert doc["bbox_delta_mm"] is None
    assert "bbox_unavailable" in doc


@needs_build123d
def test_a_failed_resolve_clears_the_stale_render_json(tmp_path: Path, capsys):
    """PR #131 review, F4: a failed resolve exited before the post-resolve
    unlink, leaving the previous run's render.json to answer a later vdiff
    as if current. It is now cleared before resolution."""
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = tmp_path / "out"
    assert main(["render", f"{module}:make", "--out", str(out)]) == 0
    capsys.readouterr()
    assert (out / "render.json").is_file()
    module.write_text("import nosuchmod_xyz\n")
    assert main(["render", f"{module}:make", "--out", str(out)]) in (4, 64)
    capsys.readouterr()
    assert not (out / "render.json").exists()


# ---------------------------------------------------------------------------
# read_png: the five filters, against hand-encoded rows
# ---------------------------------------------------------------------------


@needs_numpy
def test_read_png_decodes_every_filter_the_engine_may_use(tmp_path: Path):
    """The OpenSCAD tier's images come from the engine, which filters as it
    pleases; each of the five PNG filters is hand-encoded here and must
    round-trip. A wrong unfilter would corrupt pixels silently — a diff
    built on it would hallucinate change."""
    rng = np.random.default_rng(21)
    img = rng.integers(0, 256, size=(5, 4, 3), dtype=np.uint8)

    def encode_row(kind, cur, prev) -> bytes:
        cur16, prev16 = cur.astype(np.int32), prev.astype(np.int32)
        out = np.zeros_like(cur16)
        for i in range(len(cur16)):
            a = int(cur16[i - 3]) if i >= 3 else 0
            b = int(prev16[i])
            c = int(prev16[i - 3]) if i >= 3 else 0
            if kind == 0:
                out[i] = cur16[i]
            elif kind == 1:
                out[i] = (cur16[i] - a) % 256
            elif kind == 2:
                out[i] = (cur16[i] - b) % 256
            elif kind == 3:
                out[i] = (cur16[i] - (a + b) // 2) % 256
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                nearest = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                out[i] = (cur16[i] - nearest) % 256
        return bytes([kind]) + out.astype(np.uint8).tobytes()

    rows = b""
    prev = np.zeros(12, np.uint8)
    for y in range(5):
        cur = img[y].reshape(-1)
        rows += encode_row(y, cur, prev)  # row y wears filter y: all five
        prev = cur

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    path = tmp_path / "filters.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 5, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    assert (read_png(path) == img).all()


def test_read_png_refuses_what_partspec_never_produces(tmp_path: Path):
    bogus = tmp_path / "p.png"
    bogus.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    with pytest.raises(VdiffUsageError):
        read_png(bogus)
    (tmp_path / "not.png").write_bytes(b"JFIF")
    with pytest.raises(VdiffUsageError, match="not a PNG"):
        read_png(tmp_path / "not.png")
