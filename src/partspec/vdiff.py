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
from .status import comparison_exit_code

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


_HIGHLIGHT = (230, 0, 126)  # magenta: pixels that changed, unmissable on both palettes


class VdiffUsageError(Exception):
    """The inputs cannot be visually diffed at all — exit 64 territory."""


def exit_code_of(outcome: str) -> int:
    """The shared policy (`status.comparison_exit_code`), re-exported so both
    verbs keep their own name for it."""
    return comparison_exit_code(outcome)


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

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise VdiffUsageError(f"{path} is not a PNG")
    if len(data) < 29:
        # A write interrupted before the header finished: the signature
        # alone must not reach the unpack as a crash (PR #131 review, F6).
        raise VdiffUsageError(f"{path} is not a decodable PNG (truncated in the header)")
    width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise VdiffUsageError(
            f"{path} is not an 8-bit truecolour PNG (depth {depth}, colour type "
            f"{colour}, interlace {interlace}) — nothing partspec renders produces this"
        )
    channels = 3 if colour == 2 else 4
    try:
        return _decode_idat(path, data, width, height, channels)
    except (struct.error, zlib.error, IndexError, ValueError) as exc:
        # A truncated or corrupt stream is unusable INPUT, not a partspec
        # failure: it must surface as usage, never a traceback at exit 4
        # (PR #131 review, F2).
        raise VdiffUsageError(f"{path} is not a decodable PNG ({exc})") from None


def _decode_idat(path: Path, data: bytes, width: int, height: int, channels: int) -> Any:
    import numpy as np

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


def _bbox_delta(old: dict, new: dict) -> tuple[float, float]:
    """(max component delta in mm, old diagonal in mm). Callers handle an
    absent witness before this runs — stated, never scored as 0.0 (F3)."""
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

    # `schema_version` under the name every other partspec artifact uses, and
    # `payload` saying which artifact it is (#295). This document spelled its
    # version `vdiff_schema_version` alone, so a consumer reading
    # `doc["schema_version"]` — the key SPEC-report.md 7 tells it to key on —
    # raised KeyError here and nowhere else. The old spelling is emitted
    # alongside for one release so a reader of it keeps working; both carry the
    # same integer, from one constant, so they cannot drift apart.
    doc: dict[str, Any] = {
        "schema_version": VDIFF_SCHEMA_VERSION,
        "payload": "vdiff",
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

    doc["views"] = views
    missing = [name for name, run in (("old", old), ("new", new)) if not run.get("render_bbox")]
    if missing:
        # The witness is absent (a pre-draft-12 artifact): scale was NOT
        # checked, and that is stated, never scored as 0.0 (PR #131 review,
        # F3). Pixel change still proves difference; pixel identity proves
        # nothing an unwitnessed scale could not fake.
        doc["bbox_delta_mm"] = None
        doc["bbox_unavailable"] = (
            f"{' and '.join(missing)} recorded no render_bbox — pure scale is "
            "invisible to framed pixels and was not checked"
        )
        if worst > 0.0:
            doc["magnitude"] = _visible(worst)
            doc["outcome"] = "different"
            return doc
        doc["magnitude"] = 0.0
        return refuse(
            "every view is pixel-identical, but neither that nor this tool can "
            "see pure scale without a recorded render_bbox — identity cannot "
            "be asserted",
            hint="re-render both runs with a partspec that records render_bbox",
        )

    delta_mm, diagonal = _bbox_delta(old["render_bbox"], new["render_bbox"])
    doc["bbox_delta_mm"] = _visible(delta_mm)
    # The stated formula: worst view fraction, or the bbox delta over the old
    # diagonal — whichever is larger. Pure scale changes pixels not at all
    # (framing scales with the part), so the bbox term is what keeps a
    # 20 vs 20.4 mm cube from diffing to zero. The outcome derives from the
    # UNROUNDED value: a delta that display-rounding flattens to 0.0 must
    # still read as different, or the doc contradicts itself (PR #131, F1).
    magnitude = max(worst, delta_mm / diagonal)
    doc["magnitude"] = _visible(magnitude)
    if delta_mm > 0.0 and worst == 0.0:
        doc["note"] = (
            "the images are pixel-identical but the bounding box moved: uniform "
            "scale is invisible to a framed render — `partspec measure` has the numbers"
        )
    doc["outcome"] = "different" if magnitude > 0.0 else "identical"
    return doc


def _visible(value: float) -> float:
    """Display rounding that cannot flatten a real change to 0.0: six places
    normally, full precision when rounding would erase a nonzero value."""
    rounded = round(value, 6)
    return value if value > 0.0 and rounded == 0.0 else rounded


def summary_of(doc: dict[str, Any]) -> str:
    if doc["outcome"] == "indeterminate":
        return f"vdiff: indeterminate — {doc['refused']['reason']}"
    if doc["outcome"] == "identical":
        # Reached only with the witness present and unmoved (F1/F3): both
        # halves of the claim are verified facts by the time this prints.
        return "vdiff: identical — every view byte-equal, bbox unchanged"
    parts = [
        f"{view}: {entry['fraction']:.2%}"
        for view, entry in doc["views"].items()
        if entry["pixels_changed"]
    ]
    if doc.get("bbox_unavailable"):
        parts.append("scale unchecked (no render_bbox)")
    elif doc["bbox_delta_mm"] > 0.0:
        parts.append(f"bbox moved {doc['bbox_delta_mm']:g} mm")
    return f"vdiff: different (magnitude {doc['magnitude']:g}) — " + (
        "; ".join(parts) or "no per-view change"
    )
