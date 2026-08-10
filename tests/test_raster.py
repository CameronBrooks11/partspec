"""The software rasterizer (#18): framing, orientation, occlusion, determinism.

Everything here is engine-free except the `render_views` tests, which need
build123d for a shape to tessellate. The framing assertions encode the rule
the module docstring states — the OpenSCAD camera measured off real renders —
so a change to either side breaks a number, not a vibe.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="occt extra not installed")

from partspec.backend import BuildError  # noqa: E402
from partspec.raster import (  # noqa: E402
    TESSELLATION_TOLERANCE_MM,
    rasterize,
    read_stl,
    render_section,
    render_views,
    write_png,
)

# ---------------------------------------------------------------------------
# fixtures: hand-built meshes, so no engine is in the loop
# ---------------------------------------------------------------------------


def _box(sx: float, sy: float, sz: float, at=(0.0, 0.0, 0.0)):
    """A centred box as (vertices, faces), outward CCW winding."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    ox, oy, oz = at
    verts = [(ox + x, oy + y, oz + z) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
    # Index: bit2 = x, bit1 = y, bit0 = z (0 = low, 1 = high).
    faces = [
        (0, 1, 3),
        (0, 3, 2),  # -x
        (4, 6, 7),
        (4, 7, 5),  # +x
        (0, 4, 5),
        (0, 5, 1),  # -y
        (2, 3, 7),
        (2, 7, 6),  # +y
        (0, 2, 6),
        (0, 6, 4),  # -z
        (1, 5, 7),
        (1, 7, 3),  # +z
    ]
    return verts, faces


def _merge(*meshes):
    verts, faces = [], []
    for v, f in meshes:
        base = len(verts)
        verts.extend(v)
        faces.extend((a + base, b + base, c + base) for a, b, c in f)
    return verts, faces


def _frame(verts):
    """The camera parameters the production path derives: centre, ortho
    half-height from distance = max(2.2 * diagonal, 1.0) at 22.5° fov."""
    pts = np.asarray(verts)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    center = (lo + hi) / 2.0
    diagonal = float(np.linalg.norm(hi - lo))
    distance = max(2.2 * diagonal, 1.0)
    return center, distance * math.tan(math.radians(11.25))


def _silhouette(img):
    mask = np.abs(img.astype(int) - img[0, 0].astype(int)).sum(axis=2) > 40
    ys, xs = np.nonzero(mask)
    return xs.min(), xs.max(), ys.min(), ys.max()


# ---------------------------------------------------------------------------
# framing and orientation: the OpenSCAD rules, as numbers
# ---------------------------------------------------------------------------


def test_the_framing_rule_is_the_measured_openscad_rule():
    """A 20 mm cube must occupy exactly the fraction of the frame the
    measured rule predicts: half-extent 10 over half-height
    2.2 * 20√3 * tan(11.25°), centred."""
    verts, faces = _box(20, 20, 20)
    center, half_h = _frame(verts)
    img = rasterize(verts, faces, (90.0, 0.0, 0.0), center=center, half_height=half_h)
    x0, x1, y0, y1 = _silhouette(img)
    expected = 2 * round(10.0 / half_h * 400)
    assert abs((x1 - x0 + 1) - expected) <= 2
    assert abs((y1 - y0 + 1) - expected) <= 2
    assert abs((x0 + x1) / 2 - 399.5) <= 1 and abs((y0 + y1) / 2 - 399.5) <= 1


def test_each_view_shows_the_axes_it_claims():
    """A 20×10×5 box: top sees X×Y, front sees X×Z, right sees Y×Z — the
    executed version of 'identical view names and framing rules'."""
    verts, faces = _box(20, 10, 5)
    center, half_h = _frame(verts)
    px = 400 / half_h  # pixels per mm

    def extent(rot):
        x0, x1, y0, y1 = _silhouette(
            rasterize(verts, faces, rot, center=center, half_height=half_h)
        )
        return (x1 - x0 + 1) / px, (y1 - y0 + 1) / px

    for rot, expected in {
        (0.0, 0.0, 0.0): (20, 10),  # top
        (90.0, 0.0, 0.0): (20, 5),  # front
        (90.0, 0.0, 90.0): (10, 5),  # right
    }.items():
        w, h = extent(rot)
        assert w == pytest.approx(expected[0], abs=0.03)
        assert h == pytest.approx(expected[1], abs=0.03)


def test_the_view_axes_point_the_openscad_way():
    """Signs, not just magnitudes: a narrow marker protrudes from a wide slab
    along one axis, so the silhouette's narrow edge names the direction. A
    silent axis flip would pass every extent test and lie in every image."""
    base = _box(20, 20, 2)

    def edges(mesh, rot):
        """Lit extent (px) along each boundary of the silhouette: the extent
        of the 5 outermost lit rows/columns on each side."""
        verts, faces = mesh
        center, half_h = _frame(verts)
        img = rasterize(verts, faces, rot, center=center, half_height=half_h)
        mask = np.abs(img.astype(int) - img[0, 0].astype(int)).sum(axis=2) > 40
        rows = np.nonzero(mask.any(axis=1))[0]
        cols = np.nonzero(mask.any(axis=0))[0]
        return {
            "top": mask[rows[:5]].sum(axis=1).max(),
            "bottom": mask[rows[-5:]].sum(axis=1).max(),
            "left": mask[:, cols[:5]].sum(axis=0).max(),
            "right": mask[:, cols[-5:]].sum(axis=0).max(),
        }

    plus_y = _merge(base, _box(4, 4, 2, at=(0, 12, 0)))
    e = edges(plus_y, (0.0, 0.0, 0.0))
    assert e["top"] < e["bottom"], "+Y must render upward in the top view"

    plus_z = _merge(base, _box(4, 4, 4, at=(0, 0, 3)))
    for rot in ((90.0, 0.0, 0.0), (90.0, 0.0, 90.0)):
        e = edges(plus_z, rot)
        assert e["top"] < e["bottom"], "+Z must render upward in front and right"

    plus_x = _merge(base, _box(4, 4, 4, at=(12, 0, 0)))
    for rot in ((90.0, 0.0, 0.0), (0.0, 0.0, 0.0)):
        e = edges(plus_x, rot)
        # The marker's edge profile differs from the slab's on the +X side:
        # taller than the 2 mm slab in front view, narrower than its 20 mm
        # span in top view.
        assert e["right"] != e["left"], "the marker must be distinguishable"
    e_front = edges(plus_x, (90.0, 0.0, 0.0))
    assert e_front["right"] > e_front["left"], "+X must render rightward in front"
    e_top = edges(plus_x, (0.0, 0.0, 0.0))
    assert e_top["right"] < e_top["left"], "+X must render rightward in top"


# ---------------------------------------------------------------------------
# occlusion, winding, determinism
# ---------------------------------------------------------------------------


def test_the_z_buffer_decides_not_draw_order():
    """A tilted near square over a flat far square: the centre pixel must be
    the near square's (dimmer) shade whichever order the triangles arrive —
    a painter's algorithm would give two different images."""
    far = (
        [(-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0)],
        [(0, 1, 2), (0, 2, 3)],
    )
    near = (
        [(-4, -4, 5), (4, -4, 5), (4, 4, 10), (-4, 4, 10)],
        [(0, 1, 2), (0, 2, 3)],
    )
    ab = _merge(far, near)
    ba = _merge(near, far)
    center, half_h = _frame(ab[0])
    img_ab = rasterize(*ab, (0.0, 0.0, 0.0), center=center, half_height=half_h)
    img_ba = rasterize(*ba, (0.0, 0.0, 0.0), center=center, half_height=half_h)
    far_only = rasterize(*far, (0.0, 0.0, 0.0), center=center, half_height=half_h)
    assert (img_ab == img_ba).all(), "input order changed the image"
    assert tuple(img_ab[400, 400]) != tuple(far_only[400, 400]), (
        "the nearer surface lost the depth test"
    )


def test_winding_carries_no_meaning():
    """The same cube with every triangle reversed renders byte-identically:
    normals are flipped towards the camera before shading, so a model with
    inconsistent winding cannot render holes."""
    verts, faces = _box(20, 10, 5)
    center, half_h = _frame(verts)
    flipped = [(c, b, a) for a, b, c in faces]
    one = rasterize(verts, faces, (55.0, 0.0, 25.0), center=center, half_height=half_h)
    two = rasterize(verts, flipped, (55.0, 0.0, 25.0), center=center, half_height=half_h)
    assert (one == two).all()


def test_identical_geometry_is_identical_bytes(tmp_path: Path):
    """The determinism the OpenSCAD renderer measurably lacks — and the
    property #21's visual diff will stand on."""
    verts, faces = _box(20, 10, 5)
    center, half_h = _frame(verts)
    for run in ("one", "two"):
        img = rasterize(verts, faces, (55.0, 0.0, 25.0), center=center, half_height=half_h)
        write_png(tmp_path / f"{run}.png", img)
    assert (tmp_path / "one.png").read_bytes() == (tmp_path / "two.png").read_bytes()


def test_the_png_is_a_png_and_the_pixels_round_trip(tmp_path: Path):
    img = np.zeros((4, 3, 3), dtype=np.uint8)
    img[..., 0] = np.arange(12).reshape(4, 3) * 20
    img[..., 2] = 255
    path = tmp_path / "t.png"
    write_png(path, img)
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (3, 4)
    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    rows = [raw[y * 10 : (y + 1) * 10] for y in range(4)]
    assert all(r[0] == 0 for r in rows), "writer promises filter 0"
    decoded = np.frombuffer(b"".join(r[1:] for r in rows), np.uint8).reshape(4, 3, 3)
    assert (decoded == img).all()


# ---------------------------------------------------------------------------
# render_views: the production entry, on a real shape
# ---------------------------------------------------------------------------


def test_render_views_writes_the_views_and_records_the_tessellation(tmp_path: Path):
    bd = pytest.importorskip("build123d", reason="occt extra not installed")
    result = render_views(bd.Box(20, 10, 5), tmp_path)
    assert not isinstance(result, BuildError)
    views, tessellation, bbox = result
    assert set(views) == {"iso", "front", "top", "right"}
    for path in views.values():
        assert path.stat().st_size > 0
    # A box tessellates to its 12 triangles exactly: the record is a count of
    # what was shown, not a guess.
    assert tessellation == {
        "tolerance_mm": TESSELLATION_TOLERANCE_MM,
        "triangles": 12,
    }
    # The scale witness (#21): framing scales with the part, so the bbox is
    # the only record a visual diff can compare sizes through.
    assert bbox == {"min": [-10.0, -5.0, -2.5], "max": [10.0, 5.0, 2.5]}


def test_the_production_framing_constants_bind(tmp_path: Path):
    """PR #127 review, F2: the framing tests above derive half_height through
    a formula this file duplicates, so the production constants could drift
    and nothing failed — 2.2 → 2.0 and tan(11.25°) → 0.25 both passed the
    whole suite. This pin goes through `render_views` itself: a 20 mm cube at
    distance 2.2·20√3 has half-height 15.1585 mm, so its silhouette spans
    2·round(400·10/15.1585) = 528 px. Either constant moving breaks 528."""
    bd = pytest.importorskip("build123d", reason="occt extra not installed")
    result = render_views(bd.Box(20, 20, 20), tmp_path)
    assert not isinstance(result, BuildError)
    views, _, _ = result
    data = views["front"].read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    img = (
        np.frombuffer(raw, np.uint8).reshape(height, width * 3 + 1)[:, 1:].reshape(height, width, 3)
    )
    mask = np.abs(img.astype(int) - img[0, 0].astype(int)).sum(axis=2) > 40
    ys, xs = np.nonzero(mask)
    assert abs((xs.max() - xs.min() + 1) - 528) <= 2
    assert abs((ys.max() - ys.min() + 1) - 528) <= 2


def test_render_views_refuses_an_empty_shape(tmp_path: Path):
    bd = pytest.importorskip("build123d", reason="occt extra not installed")
    result = render_views(bd.Compound(), tmp_path)
    assert isinstance(result, BuildError)
    assert "nothing to render" in result.message
    assert not (tmp_path / "renders").exists(), "a refusal writes no files"


# ---------------------------------------------------------------------------
# sections (#19): the cut faces are found, coloured, and framed like the views
# ---------------------------------------------------------------------------


def _decode(path: Path):
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    return (
        np.frombuffer(raw, np.uint8).reshape(height, width * 3 + 1)[:, 1:].reshape(height, width, 3)
    )


def test_read_stl_round_trips_a_hand_written_facet(tmp_path: Path):
    stl = tmp_path / "one.stl"
    header = b"\x00" * 80 + struct.pack("<I", 1)
    facet = struct.pack("<12fH", 0, 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0)
    stl.write_bytes(header + facet)
    points, faces = read_stl(stl)
    assert points.shape == (3, 3) and faces.shape == (1, 3)
    assert points.tolist() == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def test_the_cut_faces_wear_the_cut_colour_and_nothing_else_does(tmp_path: Path):
    """A half-cube whose top face lies on the section plane: the cap must
    render terracotta at the exact shaded value (deterministic pixels), the
    silhouette must match the full part's framing, and the count must be the
    cap's two triangles."""
    verts, faces = _box(20, 20, 10, at=(0, 0, -5))  # the kept half: z in [-10, 0]
    full = _box(20, 20, 20)  # the original part frames the section
    png, cut_n = render_section(
        np.asarray(verts, np.float64),
        np.asarray(faces, np.int64),
        "xy",
        0.0,
        np.asarray(full[0], np.float64),
        tmp_path,
    )
    assert cut_n == 2, "the cap is two triangles"
    img = _decode(png)
    # The cap faces the camera head-on: shade = 0.35 + 0.65·lz, applied to
    # terracotta (204, 92, 63) — an exact, deterministic pixel.
    lz = 0.89 / math.sqrt(0.35**2 + 0.30**2 + 0.89**2)
    shade = 0.35 + 0.65 * lz
    expected = tuple(int(c * shade) for c in (204, 92, 63))
    assert tuple(img[400, 400]) == expected
    # Framed by the ORIGINAL 20 mm cube, not the cut half: same 528 px span
    # as the canonical views, so sections and views compare.
    mask = np.abs(img.astype(int) - img[0, 0].astype(int)).sum(axis=2) > 40
    _ys, xs = np.nonzero(mask)
    assert abs((xs.max() - xs.min() + 1) - 528) <= 2


def test_coplanarity_survives_the_float32_round_trip(tmp_path: Path):
    """The OpenSCAD path stores vertices as float32: a cap at a non-dyadic
    offset lands within float32 rounding of the plane, and must still be
    found by the tolerance."""
    offset = 3.3333333
    verts, faces = _box(20, 20, 10, at=(0, 0, offset - 5))
    quantised = np.asarray(verts, np.float32).astype(np.float64)
    full = np.asarray(_box(20, 20, 20)[0], np.float64)
    _png, cut_n = render_section(
        quantised, np.asarray(faces, np.int64), "xy", offset, full, tmp_path
    )
    assert cut_n == 2, "float32 rounding must not lose the cap"
