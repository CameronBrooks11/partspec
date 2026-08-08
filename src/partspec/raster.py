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

from .backend import BuildError
from .engines.openscad import IMAGE_SIZE, VIEWS

__all__ = ["TESSELLATION_TOLERANCE_MM", "rasterize", "render_views", "write_png"]

# The same tolerance the OCCT backend's `triangles` capability uses: one
# tessellation is the measurand (D15), not one per consumer.
TESSELLATION_TOLERANCE_MM = 0.1

_BACKGROUND = (255, 255, 229)  # OpenSCAD's Cornfield background
_FACE = (249, 215, 44)  # Cornfield's face colour, shaded below
_AMBIENT = 0.35
_LIGHT = (0.35, 0.30, 0.89)  # towards the camera, upper-left — fixed, in view space


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
    ax, ay, az = xs[tri[:, 0]], ys[tri[:, 0]], zs[tri[:, 0]]
    bx, by, bz = xs[tri[:, 1]], ys[tri[:, 1]], zs[tri[:, 1]]
    cx, cy, cz = xs[tri[:, 2]], ys[tri[:, 2]], zs[tri[:, 2]]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    normals = np.cross((view[tri[:, 1]] - view[tri[:, 0]]), (view[tri[:, 2]] - view[tri[:, 0]]))
    lengths = np.linalg.norm(normals, axis=1)

    for i in range(len(tri)):
        if area[i] == 0.0 or lengths[i] == 0.0:
            continue  # edge-on or degenerate: no pixels, and nothing to shade
        x0 = max(int(math.floor(min(ax[i], bx[i], cx[i]))), 0)
        x1 = min(int(math.ceil(max(ax[i], bx[i], cx[i]))), width - 1)
        y0 = max(int(math.floor(min(ay[i], by[i], cy[i]))), 0)
        y1 = min(int(math.ceil(max(ay[i], by[i], cy[i]))), height - 1)
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
        colour = np.clip(np.asarray(_FACE) * shade, 0, 255).astype(np.uint8)
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
) -> tuple[dict[str, Path], dict[str, object]] | BuildError:
    """The canonical views of an OCCT-tier shape, plus the tessellation record.

    Mirrors `openscad.render_views`: same view names, same framing rules, same
    stale-artifact discipline. Returns the view map and a
    ``{tolerance_mm, triangles}`` record — under D15 the tessellation is what
    was shown, so its quality rides with the images.
    """
    try:
        vertices, faces = shape.tessellate(TESSELLATION_TOLERANCE_MM)
    except ValueError:
        # build123d refuses to tessellate an empty shape; same answer either
        # way — nothing to show is a stated refusal, not four blank frames.
        vertices, faces = [], []
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
        png.unlink(missing_ok=True)  # same stale-artifact rule as the STL
        write_png(png, rasterize(points, faces, rot, center=center, half_height=half_height))
        renders[view] = png
    return renders, {
        "tolerance_mm": TESSELLATION_TOLERANCE_MM,
        "triangles": len(faces),
    }
