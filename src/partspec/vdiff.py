"""Visual diff between two runs of one part (#21).

Pairs with the semantic `diff`: that verb says what changed in the *claims*,
this one what changed in the *part's appearance*. It consumes the artifacts
renders leave on disk — `render.json` from the `render` verb, or a report
carrying `renders` — and compares per-view pixels, refusing everything that
would let noise read as change:

- differing image sizes are refused, never silently rescaled;
- a differing engine kind or version is refused: 7.68% of pixels differ
  across OpenSCAD versions for *identical* geometry (the recorded audit
  measurement), and reporting renderer noise as change would be the tool
  lying with numbers;
- differing part ids or view sets are refused — there is no honest pixel
  pairing between different questions.

Pure scale is invisible to pixels: the bbox-derived framing renders a 20 mm
and a 20.4 mm cube byte-identical. The recorded `render_bbox` is therefore
compared alongside the images, and a bbox delta with identical pixels is
still `different`, stated as scale-only with `measure` as the referral —
never silence.

The scalar: `magnitude` is the larger of the worst per-view changed-pixel
fraction and the bbox delta normalised by the old diagonal — 0.0 exactly
when nothing changed, and the formula is stated here so the number can be
reproduced rather than trusted.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

from .report import SCHEMA_VERSION

__all__ = [
    "VDIFF_SCHEMA_VERSION",
    "VdiffUsageError",
    "diff_renders",
    "exit_code_of",
    "load_run",
    "read_png",
    "summary_of",
]

VDIFF_SCHEMA_VERSION = 1

_EXIT = {"identical": 0, "different": 1, "indeterminate": 2}

_HIGHLIGHT = (230, 0, 126)  # magenta: pixels that changed, unmissable on both palettes


class VdiffUsageError(Exception):
    """The inputs cannot be visually diffed at all — exit 64 territory."""


def exit_code_of(outcome: str) -> int:
    return _EXIT[outcome]


def load_run(path: Path) -> dict[str, Any]:
    """A run's render metadata: `render.json`, or a report with `renders`.

    A directory resolves to `render.json` then `report.json` inside it. The
    returned dict gains `_dir` (for resolving relative image paths) and
    `_file` (for messages). Raises `VdiffUsageError` for anything unusable —
    the ask is malformed, nothing was compared.
    """
    candidate = path
    if path.is_dir():
        for name in ("render.json", "report.json"):
            if (path / name).is_file():
                candidate = path / name
                break
        else:
            raise VdiffUsageError(
                f"{path} contains no render.json or report.json — run "
                "`partspec render` (or `check --render`) there first"
            )
    try:
        doc = json.loads(candidate.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VdiffUsageError(f"cannot read {candidate}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise VdiffUsageError(f"{candidate} is not a render artifact: {exc}") from None
    if not isinstance(doc, dict) or "renders" not in doc:
        raise VdiffUsageError(
            f"{candidate} carries no renders — a visual diff needs images to compare"
        )
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise VdiffUsageError(
            f"this diff understands schema {SCHEMA_VERSION} and must not guess at "
            f"{doc.get('schema_version')!r} ({candidate})"
        )
    doc["_dir"] = candidate.parent
    doc["_file"] = str(candidate)
    return doc


def read_png(path: Path) -> Any:
    """Any 8-bit truecolour(±alpha) PNG as an (H, W, 3) uint8 array.

    A full five-filter decoder, because the OpenSCAD tier's images come from
    the engine, which filters as it pleases — the rasterizer's own filter-0
    output is just the easy case. Interlaced or paletted PNGs are refused:
    nothing partspec compares produces them, and guessing would be worse.
    """
    import numpy as np

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise VdiffUsageError(f"{path} is not a PNG")
    width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise VdiffUsageError(
            f"{path} is not an 8-bit truecolour PNG (depth {depth}, colour type "
            f"{colour}, interlace {interlace}) — nothing partspec renders produces this"
        )
    channels = 3 if colour == 2 else 4
    idat = b""
    pos = 8
    while pos < len(data):
        (length,), kind = struct.unpack(">I", data[pos : pos + 4]), data[pos + 4 : pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    img = np.zeros((height, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(height):
        row = raw[y * (stride + 1) : (y + 1) * (stride + 1)]
        kind, line = row[0], np.frombuffer(row[1:], np.uint8).astype(np.int32)
        if kind == 0:
            cur = line
        elif kind == 2:  # Up
            cur = (line + prev) % 256
        else:  # Sub, Average, Paeth: sequential in x, vectorless but exact
            cur = line.copy()
            for i in range(stride):
                a = int(cur[i - channels]) if i >= channels else 0
                b = int(prev[i])
                c = int(prev[i - channels]) if i >= channels else 0
                if kind == 1:
                    cur[i] = (cur[i] + a) % 256
                elif kind == 3:
                    cur[i] = (cur[i] + (a + b) // 2) % 256
                elif kind == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    nearest = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                    cur[i] = (cur[i] + nearest) % 256
                else:
                    raise VdiffUsageError(f"{path}: unknown PNG filter {kind}")
        prev = cur
        img[y] = cur.astype(np.uint8)
    pixels = img.reshape(height, width, channels)
    return pixels[:, :, :3].copy()


def _bbox_delta(old: dict | None, new: dict | None) -> tuple[float, float]:
    """(max component delta in mm, old diagonal in mm); (0, diag) when either
    side has no recorded bbox — absence of the witness is stated, not scored."""
    if not old or not new:
        return 0.0, 1.0
    deltas = [abs(a - b) for key in ("min", "max") for a, b in zip(old[key], new[key], strict=True)]
    spans = [b - a for a, b in zip(old["min"], old["max"], strict=True)]
    diagonal = max(sum(s * s for s in spans) ** 0.5, 1.0)
    return max(deltas), diagonal


def diff_renders(
    old: dict[str, Any], new: dict[str, Any], out_dir: Path, *, tool_version: str
) -> dict[str, Any]:
    """The visual diff document. `outcome`: identical | different |
    indeterminate — indeterminate carries `refused` with the reason, because
    a diff that cannot honestly compare must say so rather than report 0."""
    import numpy as np

    from .raster import write_png

    doc: dict[str, Any] = {
        "vdiff_schema_version": VDIFF_SCHEMA_VERSION,
        "tool": {"name": "partspec", "version": tool_version},
        "inputs": {
            "old": {"file": old["_file"], "part": old["part"]["id"], "engine": old["engine"]},
            "new": {"file": new["_file"], "part": new["part"]["id"], "engine": new["engine"]},
        },
    }

    def refuse(reason: str, hint: str | None = None) -> dict[str, Any]:
        doc["outcome"] = "indeterminate"
        doc["refused"] = {"reason": reason, **({"hint": hint} if hint else {})}
        return doc

    if old["part"]["id"] != new["part"]["id"]:
        return refuse(
            f"these are different parts ({old['part']['id']!r} vs {new['part']['id']!r}) "
            "— a visual diff compares two runs of one part"
        )
    for key in ("kind", "version"):
        if old["engine"].get(key) != new["engine"].get(key):
            return refuse(
                f"the runs used different engine {key}s "
                f"({old['engine'].get(key)!r} vs {new['engine'].get(key)!r})",
                hint="renderer noise across engine versions is measurable (7.68% of "
                "pixels for identical geometry) and would read as change; re-render "
                "one side on the other's engine",
            )
    if set(old["renders"]) != set(new["renders"]):
        return refuse(
            f"the runs rendered different view sets "
            f"({sorted(old['renders'])} vs {sorted(new['renders'])})"
        )

    views: dict[str, Any] = {}
    worst = 0.0
    for view in sorted(old["renders"]):
        images = []
        for run in (old, new):
            img_path = Path(run["renders"][view])
            if not img_path.is_absolute():
                img_path = run["_dir"] / img_path
            if not img_path.is_file():
                return refuse(f"{run['_file']} names a missing image: {img_path}")
            images.append(read_png(img_path))
        a, b = images
        if a.shape != b.shape:
            return refuse(
                f"the {view} images are different sizes ({a.shape[1]}x{a.shape[0]} vs "
                f"{b.shape[1]}x{b.shape[0]}) — rescaling would manufacture or bury change"
            )
        changed = (a != b).any(axis=2)
        count = int(changed.sum())
        fraction = count / changed.size
        worst = max(worst, fraction)
        # The diff image: the new run faded to grey, what moved in magenta.
        grey = (b.astype(np.uint16).sum(axis=2) // 6 + 128).astype(np.uint8)
        overlay = np.stack([grey, grey, grey], axis=2)
        overlay[changed] = _HIGHLIGHT
        out_png = out_dir / f"{view}.diff.png"
        out_png.parent.mkdir(parents=True, exist_ok=True)
        write_png(out_png, overlay)
        views[view] = {
            "pixels_changed": count,
            "fraction": round(fraction, 6),
            "image": str(out_png),
        }

    delta_mm, diagonal = _bbox_delta(old.get("render_bbox"), new.get("render_bbox"))
    doc["views"] = views
    doc["bbox_delta_mm"] = round(delta_mm, 6)
    # The stated formula: worst view fraction, or the bbox delta over the old
    # diagonal — whichever is larger. Pure scale changes pixels not at all
    # (framing scales with the part), so the bbox term is what keeps a
    # 20 vs 20.4 mm cube from diffing to zero.
    doc["magnitude"] = round(max(worst, delta_mm / diagonal), 6)
    if delta_mm > 1e-6 and worst == 0.0:
        doc["note"] = (
            "the images are pixel-identical but the bounding box moved: uniform "
            "scale is invisible to a framed render — `partspec measure` has the numbers"
        )
    doc["outcome"] = "different" if doc["magnitude"] > 0.0 else "identical"
    return doc


def summary_of(doc: dict[str, Any]) -> str:
    if doc["outcome"] == "indeterminate":
        return f"vdiff: indeterminate — {doc['refused']['reason']}"
    if doc["outcome"] == "identical":
        return "vdiff: identical — every view byte-equal, bbox unchanged"
    parts = [
        f"{view}: {entry['fraction']:.2%}"
        for view, entry in doc["views"].items()
        if entry["pixels_changed"]
    ]
    if doc["bbox_delta_mm"] > 1e-6:
        parts.append(f"bbox moved {doc['bbox_delta_mm']:g} mm")
    return f"vdiff: different (magnitude {doc['magnitude']:g}) — " + (
        "; ".join(parts) or "no per-view change"
    )
