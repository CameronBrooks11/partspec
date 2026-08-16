"""A deterministic software rasterizer: the OCCT tier's render path (#18).

The OpenSCAD tier renders through the engine's own viewer. This tier has no
viewer — the shape is analytic, in memory, and the environments that build it
are routinely headless — so requiring a display would make the verb refuse
almost everywhere it runs, and a GPU driver's output varies by build. The
views are instead rasterized here: an orthographic z-buffer over the shape's
tessellation, in numpy. Identical geometry produces identical bytes on every
run and platform, which is the substrate a visual diff needs (#21) and the
OpenSCAD renderer measurably lacks (7.68% of pixels differ across engine
versions for identical geometry).

The framing rules are the OpenSCAD path's, shared by import where they are
explicit and measured from it where they are not:

- same view names and gimbal angles (``VIEWS``), same ``IMAGE_SIZE``;
- same camera: bounding-box centre, distance ``max(2.2 * diagonal, 1.0)``;
- orthographic viewport half-height = ``distance * tan(22.5° / 2)`` —
  OpenSCAD keeps this implicit, so it was measured off real renders: the
  silhouette of a known cube at two distances gives half-height/distance of
  0.198 and 0.200, i.e. its default 22.5° field of view applied at the
  camera distance.

What is shown is the tessellation, at a stated tolerance — the same D15
reading the measurement tiers use — so the tolerance and triangle count ride
with the images rather than being silently absorbed into them.

numpy arrives with both OCCT-tier engines; this module is imported only on
that tier, so the core stays stdlib-only.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np

from .backend import BuildError, bbox_block
from .engines.openscad import IMAGE_SIZE, VIEWS

__all__ = [
    "SECTION_VIEWS",
    "TESSELLATION_TOLERANCE_MM",
    "rasterize",
    "read_stl",
    "render_section",
    "render_views",
    "write_png",
]

# The same tolerance the OCCT backend's `triangles` capability uses: one
# tessellation is the measurand (D15), not one per consumer.
TESSELLATION_TOLERANCE_MM = 0.1

_BACKGROUND = (255, 255, 229)  # OpenSCAD's Cornfield background
_FACE = (249, 215, 44)  # Cornfield's face colour, shaded below
_CUT = (204, 92, 63)  # terracotta: the material the section plane exposed (#19)
_AMBIENT = 0.35
_LIGHT = (0.35, 0.30, 0.89)  # towards the camera, upper-left — fixed, in view space

# A section is viewed along the cut plane's normal, looking INTO the cut: the
# material on the camera's side of the plane is discarded, so the exposed
# faces at the plane fill the frame. The rotations are the canonical views'
# own (top / front / right), so a section frames exactly like the view it
# extends; the int is the axis the plane fixes (x=0, y=1, z=2).
SECTION_VIEWS: dict[str, tuple[tuple[float, float, float], int]] = {
    "xy": ((0.0, 0.0, 0.0), 2),  # camera +Z: discard z > offset
    "xz": ((90.0, 0.0, 0.0), 1),  # camera -Y: discard y < offset
    "yz": ((90.0, 0.0, 90.0), 0),  # camera +X: discard x > offset
}


def _view_matrix(rot: tuple[float, float, float]) -> Any:
    """OpenSCAD's gimbal: the camera starts on +Z and is rotated X, then Y,
    then Z — a point's view-space image is therefore p @ (Rz @ Ry @ Rx)."""
    rx, ry, rz = (math.radians(a) for a in rot)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


def rasterize(
    vertices: Any,
    faces: Any,
    rot: tuple[float, float, float],
    *,
    center: Any,
    half_height: float,
    size: tuple[int, int] = IMAGE_SIZE,
    colors: Any = None,
) -> Any:
    """One orthographic view as an (H, W, 3) uint8 array.

    Winding-independent: a triangle's normal is flipped towards the camera
    before shading, so a model with inconsistent winding shades the same as a
    consistent one instead of rendering holes. Occlusion is a plain z-buffer;
    draw order carries no meaning.
    """
    width, height = size
    view = (np.asarray(vertices, dtype=np.float64) - center) @ _view_matrix(rot)
    scale = (height / 2.0) / half_height
    xs = view[:, 0] * scale + width / 2.0
    ys = height / 2.0 - view[:, 1] * scale
    zs = view[:, 2]

    img = np.empty((height, width, 3), dtype=np.uint8)
    img[:] = _BACKGROUND
    zbuf = np.full((height, width), -np.inf)
    light = np.asarray(_LIGHT) / np.linalg.norm(_LIGHT)

    tri = np.asarray(faces, dtype=np.int64)
    base_colors = (
        np.broadcast_to(np.asarray(_FACE, dtype=np.float64), (len(tri), 3))
        if colors is None
        else np.asarray(colors, dtype=np.float64)
    )
    ax, ay, az = xs[tri[:, 0]], ys[tri[:, 0]], zs[tri[:, 0]]
    bx, by, bz = xs[tri[:, 1]], ys[tri[:, 1]], zs[tri[:, 1]]
    cx, cy, cz = xs[tri[:, 2]], ys[tri[:, 2]], zs[tri[:, 2]]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    normals = np.cross((view[tri[:, 1]] - view[tri[:, 0]]), (view[tri[:, 2]] - view[tri[:, 0]]))
    lengths = np.linalg.norm(normals, axis=1)

    for i in range(len(tri)):
        if area[i] == 0.0 or lengths[i] == 0.0:
            continue  # edge-on or degenerate: no pixels, and nothing to shade
        x0 = max(math.floor(min(ax[i], bx[i], cx[i])), 0)
        x1 = min(math.ceil(max(ax[i], bx[i], cx[i])), width - 1)
        y0 = max(math.floor(min(ay[i], by[i], cy[i])), 0)
        y1 = min(math.ceil(max(ay[i], by[i], cy[i])), height - 1)
        if x1 < x0 or y1 < y0:
            continue
        px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = (bx[i] - ax[i]) * (py - ay[i]) - (by[i] - ay[i]) * (px - ax[i])
        w1 = (cx[i] - bx[i]) * (py - by[i]) - (cy[i] - by[i]) * (px - bx[i])
        w2 = (ax[i] - cx[i]) * (py - cy[i]) - (ay[i] - cy[i]) * (px - cx[i])
        if area[i] > 0.0:
            inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        else:
            inside = (w0 <= 0.0) & (w1 <= 0.0) & (w2 <= 0.0)
        if not inside.any():
            continue
        # Barycentric depth at each covered pixel.
        depth = (w1 * az[i] + w2 * bz[i] + w0 * cz[i]) / area[i]
        patch_z = zbuf[y0 : y1 + 1, x0 : x1 + 1]
        wins = inside & (depth > patch_z)
        if not wins.any():
            continue
        normal = normals[i] / lengths[i]
        if normal[2] < 0.0:
            normal = -normal
        shade = _AMBIENT + (1.0 - _AMBIENT) * max(float(normal @ light), 0.0)
        colour = np.clip(base_colors[i] * shade, 0, 255).astype(np.uint8)
        patch_z[wins] = depth[wins]
        img[y0 : y1 + 1, x0 : x1 + 1][wins] = colour
    return img


def write_png(path: Path, img: Any) -> None:
    """Truecolour 8-bit PNG via zlib — no image library in the loop."""
    height, width, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render_views(
    shape: Any, out_dir: Path
) -> tuple[dict[str, Path], dict[str, object], dict[str, list[float]]] | BuildError:
    """The canonical views of an OCCT-tier shape, plus the tessellation record.

    Mirrors `openscad.render_views` in view names and framing rules. NOT in
    stale-artifact discipline: since #223 and #224 the OpenSCAD tier renders
    into a scratch directory and moves the result, and this one still clears
    each destination first — the opposite trade, and safe to make here because
    the OCCT tier has no `surface()` to make a PNG a build input. The two were
    the same until this cycle and this sentence said so afterwards. Returns the
    view map, a
    ``{tolerance_mm, triangles}`` record — under D15 the tessellation is what
    was shown, so its quality rides with the images — and the framing bbox
    (`bbox_block`), the scale witness a visual diff needs (#21).
    """
    try:
        vertices, faces = shape.tessellate(TESSELLATION_TOLERANCE_MM)
    except ValueError:
        # build123d refuses to tessellate an empty shape; same answer either
        # way — nothing to show is a stated refusal, not four blank frames.
        vertices, faces = [], []
    except Exception as exc:  # noqa: BLE001 — see below
        # Everything else this ONE call can raise, classified rather than
        # allowed to escape. `bd_warehouse`'s `IsoThread(external=False)` nut,
        # whose thread vanishes during fusion, reached
        # `AttributeError: 'NoneType' object has no attribute 'NbNodes'` — OCCT
        # returns no triangulation for a face it cannot mesh and build123d
        # assumes one — and that came out as a stack trace where a classified
        # failure belongs (#191). `check` on the SAME part reaches a real
        # verdict, so the part is evaluable and only rendering it falls over.
        #
        # Broad on purpose, and not a mask: the `try` wraps a single call, so
        # any exception out of it IS a tessellation failure and the sentence is
        # true by construction. The underlying type and text ride along, so
        # nothing is hidden — including a partspec bug, which would name
        # itself here rather than vanish.
        return BuildError(
            f"this solid could not be tessellated for rendering: {type(exc).__name__}: {exc}",
            hint="a kernel that cannot triangulate a face usually has a degenerate or "
            "self-intersecting solid to work with — `check` with `watertight` and "
            "`self_intersection_free` says whether that is so, and answers on this part "
            "even though rendering does not",
        )
    if not faces:
        return BuildError("this shape contains no geometry, so there is nothing to render")
    points = np.array([(v.X, v.Y, v.Z) for v in vertices], dtype=np.float64)
    lo, hi = points.min(axis=0), points.max(axis=0)
    center = (lo + hi) / 2.0
    diagonal = float(np.linalg.norm(hi - lo))
    distance = max(2.2 * diagonal, 1.0)  # a degenerate flat part still gets a frame
    half_height = distance * math.tan(math.radians(22.5 / 2.0))

    renders: dict[str, Path] = {}
    for view, rot in VIEWS.items():
        png = out_dir / "renders" / f"{view}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        # Cleared before writing, so a failed view cannot leave the previous
        # run's image to be read as this run's. This said "same stale-artifact
        # rule as the STL" until v0.7.6's pre-tag audit: #223 deleted that rule,
        # and #224 was filed about exactly this kind of citation surviving the
        # thing it cites. The trade is the opposite of the OpenSCAD tier's and
        # safe to make here — this rasterizer serves the OCCT tier, which has no
        # `surface()` to make a PNG a build input.
        png.unlink(missing_ok=True)
        write_png(png, rasterize(points, faces, rot, center=center, half_height=half_height))
        renders[view] = png
    return (
        renders,
        {"tolerance_mm": TESSELLATION_TOLERANCE_MM, "triangles": len(faces)},
        bbox_block(lo, hi),
    )


def read_stl(path: Path) -> tuple[Any, Any]:
    """A binary STL as (vertices, faces) — vertices per-facet, float64.

    Binary specifically: the engine layer exports `binstl` by choice (its
    `render()` docstring owns that decision), so this reader matches the one
    format those files can be. The 50-byte facet layout mirrors
    `openscad._stl_bbox`."""
    data = path.read_bytes()
    (count,) = struct.unpack_from("<I", data, 80)
    facet = np.dtype([("normal", "<3f4"), ("verts", "<9f4"), ("attr", "<u2")])
    facets = np.frombuffer(data, dtype=facet, count=count, offset=84)
    coords = facets["verts"].astype(np.float64).reshape(count * 3, 3)
    faces = np.arange(count * 3, dtype=np.int64).reshape(count, 3)
    return coords, faces


def render_section(
    points: Any,
    faces: Any,
    plane: str,
    offset: float,
    frame_points: Any,
    out_dir: Path,
) -> tuple[Path, int]:
    """One section image of an already-cut mesh, cut faces in a distinct colour.

    `points`/`faces` are the CUT solid — the kernel that owns the geometry did
    the boolean, so the cap is real capped material, not a rasterizer trick.
    `frame_points` are the ORIGINAL part's vertices: a section frames exactly
    like the canonical view it extends, so iterations and views compare.

    Cut faces are found by coplanarity with the section plane. The tolerance
    scales with the offset because the OpenSCAD path round-trips through
    float32 STL; an interior face that happens to lie exactly on the plane
    will be coloured as cut — that is the true geometry of the section, not a
    misidentification. Returns the image path and the cut-facet count, which
    the payload records: zero states the plane passed only through voids."""
    rot, axis = SECTION_VIEWS[plane]
    frame = np.asarray(frame_points, dtype=np.float64)
    lo, hi = frame.min(axis=0), frame.max(axis=0)
    center = (lo + hi) / 2.0
    diagonal = float(np.linalg.norm(hi - lo))
    distance = max(2.2 * diagonal, 1.0)
    half_height = distance * math.tan(math.radians(22.5 / 2.0))

    pts = np.asarray(points, dtype=np.float64)
    tri = np.asarray(faces, dtype=np.int64)
    eps = 1e-5 * max(1.0, abs(offset))
    on_plane = np.asarray(np.abs(pts[:, axis] - offset) <= eps)
    cut = np.asarray(on_plane[tri].all(axis=1))
    colors = np.where(cut[:, None], np.asarray(_CUT, np.float64), np.asarray(_FACE, np.float64))

    png = out_dir / "renders" / f"section_{plane}.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.unlink(missing_ok=True)  # same stale-artifact rule as the views
    img = rasterize(pts, tri, rot, center=center, half_height=half_height, colors=colors)
    write_png(png, img)
    return png, int(cut.sum())
