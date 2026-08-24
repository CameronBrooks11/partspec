"""Spatial regions a contract can claim empty or solid (SPEC-contract.md 4.4).

Pure data, stdlib only: the core must stay importable without a CAD engine
(SPEC-contract.md 1.1), so a region is declared here and *materialized* inside
each backend from the geometry this module computes.

The one non-obvious decision, made once here so both tiers inherit it: **a
cylinder region IS a circumscribed n-gon prism**, on every tier. Both backends
build the same polyhedron from the same vertex list, so one contract adjudicates
the identical region everywhere — and because the polygon circumscribes the
declared circle (region ⊇ declared cylinder), an "empty" verdict is earned: no
material can hide between the polygon and the circle it stands for. The cost is
over-approximation by `sec(pi/n) - 1` radially (~0.12% at the default 64
segments), which fails a feature whose clearance to the declared region is below
micrometres — a margin no manufacturing process holds, and a zero-margin
declaration is a claim the author should not be making.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .provenance import Referenced
from .status import ContractError, short_repr

__all__ = ["BoxRegion", "CylinderRegion", "Region", "box", "cylinder"]

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _finite(value: float, what: str) -> float:
    """Validate finiteness without flattening a `Referenced`.

    `Referenced` is a float SUBCLASS, so `float(value)` strips the citation. It
    mattered on exactly the paths that write the validated value BACK — a box's
    corners, and a cylinder's `at` — and not on a cylinder's `d`/`h`, which
    `__post_init__` validates and then discards the result of. #250 reads as one
    cause ("their values pass through geometric validation that normalises to
    plain floats"); measured, it is two, and the tree's own exemplar sits on the
    half that never lost anything. Its citation was intact all along and only
    `_region_spec` failed to record it.
    """
    v = float(value)
    if not math.isfinite(v):
        raise ContractError(f"{what} is {value!r}, which is not a number")
    return value if isinstance(value, Referenced) else v


@dataclass(frozen=True, slots=True)
class BoxRegion:
    """An axis-aligned box, declared by its two corners."""

    min: tuple[float, float, float]
    max: tuple[float, float, float]

    def __post_init__(self) -> None:
        lo = tuple(_finite(v, "a box region corner coordinate") for v in self.min)
        hi = tuple(_finite(v, "a box region corner coordinate") for v in self.max)
        if len(lo) != 3 or len(hi) != 3:
            raise ContractError("a box region takes 3-component min and max corners")
        for axis, a, b in zip("xyz", lo, hi, strict=True):
            if not a < b:
                raise ContractError(
                    f"box region min must be strictly below max on every axis; "
                    f"{axis}: {a} vs {b} encloses no volume, and a region that "
                    f"encloses nothing can claim nothing"
                )
        object.__setattr__(self, "min", lo)
        object.__setattr__(self, "max", hi)

    def expand(self, t: float) -> BoxRegion:
        return BoxRegion(
            min=tuple(v - t for v in self.min),  # type: ignore[arg-type]
            max=tuple(v + t for v in self.max),  # type: ignore[arg-type]
        )

    def inradius(self) -> float:
        """The largest inward offset that leaves anything behind.

        `expand(-r)` moves every face inward by `r`, so this is the radius at
        which the region erodes to nothing — and therefore the ceiling on how
        deep material can sit inside it (#207).
        """
        return min((b - a) / 2 for a, b in zip(self.min, self.max, strict=True))

    def volume(self) -> float:
        return math.prod(b - a for a, b in zip(self.min, self.max, strict=True))

    def eroded_volume(self, t: float) -> float:
        """`expand(-t).volume()`, without building the eroded region.

        Arithmetic on the EXTENTS, which is what the answer depends on, rather
        than on the coordinates, which it does not. `expand(-t)` moves both
        faces toward each other, so at a large offset `min + t` and `max - t`
        round to the same double long before the extent does, and the
        constructor rejects its own eroded copy — measured, a legal 8 mm-thin
        keep-out at x = 1e5 raised `ContractError` from a search that had
        already paid every boolean (round-3 review of #207).

        `t` is checked rather than clamped: `max(0.0, nan)` is `0.0`, so a NaN
        offset graded as "erodes to nothing" — an answer — where `expand(-nan)`
        raises. This was the only region entry point accepting a non-finite
        argument (#245).
        """
        t = _finite(t, "an erosion offset")
        return math.prod(max(0.0, (b - a) - 2 * t) for a, b in zip(self.min, self.max, strict=True))

    def mesh(self) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
        (x0, y0, z0), (x1, y1, z1) = self.min, self.max
        v = [
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        ]
        f = [
            (0, 2, 1),
            (0, 3, 2),  # bottom (-z)
            (4, 5, 6),
            (4, 6, 7),  # top (+z)
            (0, 1, 5),
            (0, 5, 4),  # -y
            (2, 3, 7),
            (2, 7, 6),  # +y
            (1, 2, 6),
            (1, 6, 5),  # +x
            (3, 0, 4),
            (3, 4, 7),  # -x
        ]
        return v, f

    def to_json(self) -> dict[str, Any]:
        return {"shape": "box", "min": list(self.min), "max": list(self.max)}


@dataclass(frozen=True, slots=True)
class CylinderRegion:
    """The circumscribed n-gon prism standing for a cylinder of diameter `d`.

    `at` is the centre of the base circle. `axis` names the axis the prism stands
    on — the string `'x'`, `'y'` or `'z'`, not a direction vector — and the prism
    extends `h` from `at` in that axis's positive direction.
    """

    d: float
    h: float
    at: tuple[float, float, float]
    axis: str = "z"
    segments: int = 64

    def __post_init__(self) -> None:
        _finite(self.d, "a cylinder region diameter")
        _finite(self.h, "a cylinder region height")
        if self.d <= 0 or self.h <= 0:
            raise ContractError("a cylinder region needs d > 0 and h > 0; it must enclose volume")
        at = tuple(_finite(v, "a cylinder region centre coordinate") for v in self.at)
        if len(at) != 3:
            raise ContractError("a cylinder region centre takes 3 components")
        object.__setattr__(self, "at", at)
        # The type BEFORE the membership test. `x not in <dict>` hashes `x`,
        # and an unhashable value dies inside the guard rather than at it:
        # `axis=[0, 0, 1]` raised `cannot use 'list' as a dict key`, which is
        # partspec's own implementation detail — that `_AXES` happens to be a
        # dict — offered as the diagnosis for a user error one keystroke from
        # the one #193 exists to document (#199). Two fleet agents wrote
        # `axis=(0, 0, 1)`; a tuple is hashable and reached the message, a list
        # is not and did not.
        if not isinstance(self.axis, str) or self.axis not in _AXES:
            raise ContractError(
                f"cylinder region axis must be the string 'x', 'y' or 'z', "
                f"not {short_repr(self.axis)}"
            )
        if not isinstance(self.segments, int) or self.segments < 8:
            raise ContractError("a cylinder region needs at least 8 segments")

    def expand(self, t: float) -> CylinderRegion:
        """Grow by `t` in every direction: wider by `2t`, longer by `2t`.

        Same segment count and same vertex angles, so the expansion is a radial
        scaling of the same polygon about the same axis — the original region is
        strictly contained, which the shell arithmetic in the runner relies on.
        """
        ax = _AXES[self.axis]
        return CylinderRegion(
            d=self.d + 2 * t,
            h=self.h + 2 * t,
            at=tuple(c - t * a for c, a in zip(self.at, ax, strict=True)),  # type: ignore[arg-type]
            axis=self.axis,
            segments=self.segments,
        )

    def axis_vector(self) -> tuple[float, float, float]:
        return _AXES[self.axis]

    def _polygon_2d(self) -> list[tuple[float, float]]:
        """The circumscribed n-gon, in the plane's own (u, v) coordinates.

        Vertices at angles `(2k+1)·pi/n`, radius `(d/2)·sec(pi/n)`: each flat's
        midpoint (at angle `2k·pi/n`) touches the declared circle, and every
        point of the circle lies inside the polygon.
        """
        n = self.segments
        r = (self.d / 2) / math.cos(math.pi / n)
        return [
            (r * math.cos((2 * k + 1) * math.pi / n), r * math.sin((2 * k + 1) * math.pi / n))
            for k in range(n)
        ]

    def base_polygon(self) -> list[tuple[float, float, float]]:
        """The base polygon as 3D points, wound counter-clockwise about `+axis`."""
        cx, cy, cz = self.at
        if self.axis == "z":
            return [(cx + u, cy + v, cz) for u, v in self._polygon_2d()]
        if self.axis == "x":
            return [(cx, cy + u, cz + v) for u, v in self._polygon_2d()]
        return [(cx + v, cy, cz + u) for u, v in self._polygon_2d()]

    def inradius(self) -> float:
        """The largest inward offset that leaves anything behind.

        `d / 2` is the polygon's INRADIUS, not its circumradius: the flats are
        tangent to the declared circle (`_polygon_2d`), so `expand(-r)` moves
        every side plane inward by exactly `r`. Axially the caps each move in
        by `r`, hence `h / 2`.
        """
        return min(self.d / 2, self.h / 2)

    def facet_floor(self) -> float:
        """The intrusion DEPTH a perfectly circular feature of this diameter
        would show against this region.

        The polygon CIRCUMSCRIBES the declared cylinder, so its corners stand
        `r·(sec(pi/n) - 1)` proud of it — but that is a radial distance, and the
        number it is compared against is an EROSION depth. `expand(-t)` shrinks
        the inradius by `t` and the corner radius by `t·sec(pi/n)`, so the
        corners clear a circle of radius `r` at `t = r·(1 - cos(pi/n))`: the
        sagitta, smaller than the radial excess by exactly `sec(pi/n)`.

        This returned the radial excess until the round-4 review of #207, which
        is 0.12% high at 64 segments and 8.2% at 8 — and the mismatch had been
        rationalised three times in this file's own history as the modelled
        bore's faceting. Measured against a Ø41 `$fn=128` bore, the depth is
        1.560399 mm at 8 region segments and 0.024684 at 64, against sagittas
        of 1.560470 and 0.024693 and radial excesses of 1.689040 and 0.024723.
        The sagitta predicts every phase-aligned measurement to 1e-4; the
        radial excess is out by 8% at the coarse end.

        Quadratic in the segment count: 0.3939 mm at 16 segments, 0.02469 at
        64, 0.006174 at 128. It is a SCALE for a reported intrusion depth and
        not a decomposition of one: the modelled feature carries a term of its
        own that the contract cannot see, how the two combine depends on how
        the polygons are phased, and on an exact backend the feature's term is
        zero. Reported beside the depth, never subtracted from it.
        """
        return (self.d / 2) * (1 - math.cos(math.pi / self.segments))

    def volume(self) -> float:
        n = self.segments
        r = (self.d / 2) / math.cos(math.pi / n)
        return (n * r * r * math.sin(2 * math.pi / n) / 2) * self.h

    def eroded_volume(self, t: float) -> float:
        """`expand(-t).volume()`, without building the eroded region.

        See `BoxRegion.eroded_volume`: the coordinates cannot affect the answer
        and at a large `at` they defeat the constructor's own guard.
        """
        t = _finite(t, "an erosion offset")
        n = self.segments
        r = max(0.0, (self.d - 2 * t) / 2) / math.cos(math.pi / n)
        return (n * r * r * math.sin(2 * math.pi / n) / 2) * max(0.0, self.h - 2 * t)

    def mesh(self) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
        n = self.segments
        ax, ay, az = _AXES[self.axis]
        base = self.base_polygon()
        top = [(x + ax * self.h, y + ay * self.h, z + az * self.h) for x, y, z in base]
        vertices = base + top
        faces: list[tuple[int, int, int]] = []
        for k in range(n):
            j = (k + 1) % n
            faces.append((k, j, n + j))
            faces.append((k, n + j, n + k))
        for k in range(1, n - 1):
            faces.append((0, k + 1, k))  # base cap, facing -axis
            faces.append((n, n + k, n + k + 1))  # top cap, facing +axis
        return vertices, faces

    def to_json(self) -> dict[str, Any]:
        return {
            "shape": "cylinder",
            "d": self.d,
            "h": self.h,
            "at": list(self.at),
            "axis": self.axis,
            "segments": self.segments,
        }


Region = BoxRegion | CylinderRegion


def box(*, min: tuple[float, float, float], max: tuple[float, float, float]) -> BoxRegion:
    """An axis-aligned box region, from its min and max corners."""
    return BoxRegion(min=min, max=max)


def cylinder(
    *,
    d: float,
    h: float,
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    axis: str = "z",
    segments: int = 64,
) -> CylinderRegion:
    """A cylinder region: diameter `d`, extending `h` from `at` along one axis.

    `at` is the centre of the BASE face, not the centroid: the prism spans `h`
    from `at`, so reading it as the centroid displaces the region by `h/2`
    (SPEC-contract.md 4.4), which no check can catch.

    `axis` is the string `'x'`, `'y'` or `'z'` — the axis to extend along, not a
    direction vector — and the prism grows in that axis's positive direction.

    Materialized as a circumscribed polygon prism — see the module docstring for
    why, and what the over-approximation costs.
    """
    return CylinderRegion(d=d, h=h, at=at, axis=axis, segments=segments)
