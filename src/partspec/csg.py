"""A reader for OpenSCAD's `.csg` export — the constant-folded CSG tree.

Hand-rolled on the #118 prior-art survey's verdict: nothing to depend on
(sca2d is GPLv3 and geometry-blind; FreeCAD's importer is LGPL and welded to
its document model; the tree-sitter family are full-language parsers for what
is, here, a literal-only subset). The format is OpenSCAD's own re-serialized
tree: variables resolved, loops unrolled, modules flattened — identifiers,
literals, vectors, named arguments, braces, and the statement modifiers
`#%!*`. One tokenizer, one recursive-descent parser, stdlib only.

One stated limitation: the engines print string CONTENTS raw (a quote inside
a text() label is not escaped), so a file whose tree carries any string is
ambiguous at the format level — depending on the content, the parse either
fails as a CsgError or, worse, silently admits phantom nodes (demonstrated
in PR #125's review). No parse of such a file can be trusted, so a caller must refuse the whole
file. `lint.lint_scad_tier2` does that on the RAW BYTES (`if '"' in raw`)
rather than on the parsed tree: a tree-walking detector shipped here first
and was bypassable by hiding the string in a %-dropped statement (PR #125
re-review), so it was removed rather than left as a weaker second option.

The evaluation layer is the part no candidate provided at any price: analytic
volumes for the primitives (scaled by |det M| under `multmatrix`) and face
planes for cubes and cylinder caps (transformed by the inverse-transpose).
Node types outside the supported set are carried as `Unknown` so a rule can
refuse honestly instead of guessing — the survey absorbed FreeCAD's node
inventory as the checklist of what can appear.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

__all__ = ["CsgError", "Node", "parse_csg", "planes_of", "volume_of"]

_TOKEN = re.compile(
    r"""
    (?P<num>-?\d+\.?\d*(?:[eE][+-]?\d+)?)
  | (?P<name>\$?\w+)
  | (?P<str>"[^"\n]*")
  | (?P<punct>[\[\]{}();,=])
  | (?P<mod>[#%!*])
  | (?P<ws>\s+)
    """,
    re.X,
)


class CsgError(Exception):
    """The file is not the literal-only tree OpenSCAD exports."""


@dataclass
class Node:
    kind: str
    args: list[object] = field(default_factory=list)
    kwargs: dict[str, object] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


def parse_csg(text: str) -> list[Node]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise CsgError(f"unrecognisable input at offset {pos}: {text[pos : pos + 20]!r}")
        pos = m.end()
        if m.lastgroup != "ws":
            tokens.append((m.lastgroup or "", m.group(0)))

    i = 0

    def peek() -> tuple[str, str] | None:
        return tokens[i] if i < len(tokens) else None

    def take(expect: str | None = None) -> tuple[str, str]:
        nonlocal i
        if i >= len(tokens):
            raise CsgError("unexpected end of input")
        kind, value = tokens[i]
        if expect is not None and value != expect:
            raise CsgError(f"expected {expect!r}, got {value!r}")
        i += 1
        return kind, value

    def value() -> object:
        kind, tok = take()
        if kind == "num":
            return float(tok)
        if kind == "str":
            return tok[1:-1]
        if kind == "name":
            if tok == "true":
                return True
            if tok == "false":
                return False
            if tok == "undef":
                return None
            raise CsgError(f"unexpected identifier in value position: {tok!r}")
        if tok == "[":
            items: list[object] = []
            while peek() and peek()[1] != "]":  # type: ignore[index]
                items.append(value())
                if peek() and peek()[1] == ",":  # type: ignore[index]
                    take(",")
            take("]")
            return items
        raise CsgError(f"unexpected token in value position: {tok!r}")

    def statement() -> Node | None:
        kind, tok = take()
        if kind == "mod":
            # `#` (highlight) and `!` (root) keep their geometry; `%`
            # (background) and `*` (disable) EXCLUDE it from the render, so a
            # %-ed cutter is not part of the part and linting it produced
            # confident wrong findings (PR #125 review, F2).
            inner = statement()
            return None if tok in "%*" else inner
        if kind != "name":
            raise CsgError(f"expected a node name, got {tok!r}")
        node = Node(kind=tok)
        take("(")
        while peek() and peek()[1] != ")":  # type: ignore[index]
            nxt = peek()
            if nxt and nxt[0] == "name" and i + 1 < len(tokens) and tokens[i + 1][1] == "=":
                (_, name) = take()
                take("=")
                node.kwargs[name] = value()
            else:
                node.args.append(value())
            if peek() and peek()[1] == ",":  # type: ignore[index]
                take(",")
        take(")")
        nxt = peek()
        if nxt and nxt[1] == "{":
            take("{")
            while peek() and peek()[1] != "}":  # type: ignore[index]
                child = statement()
                if child is not None:
                    node.children.append(child)
            take("}")
        elif nxt and nxt[1] == ";":
            take(";")
        return node

    nodes = []
    while peek() is not None:
        top = statement()
        if top is not None:
            nodes.append(top)
    return nodes


# --------------------------------------------------------------------------
# evaluation: volumes and face planes, exact where the tree is
# --------------------------------------------------------------------------

_IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


def _compose(outer, inner):
    """outer @ inner for 3x4 affine rows (implicit last row 0 0 0 1)."""
    return tuple(
        tuple(
            sum(outer[r][k] * inner[k][c] for k in range(3)) + (outer[r][3] if c == 3 else 0.0)
            for c in range(4)
        )
        for r in range(3)
    )


def _det3(m) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _matrix_of(node: Node):
    rows = node.args[0] if node.args else None
    if not isinstance(rows, list) or len(rows) < 3:
        raise CsgError("multmatrix without a matrix")
    return tuple(tuple(float(x) for x in row[:4]) for row in rows[:3])


class Unknown(Exception):
    """A node the evaluator does not model; carries the node kind."""


def volume_of(node: Node, matrix=_IDENTITY) -> float:
    """Analytic volume of the subtree, scaled by |det| of the accumulated
    transform. Union/group volumes are the SUM of children — an upper bound
    when children overlap, and documented as such where a rule consumes it.
    Raises Unknown for any node outside the modelled set."""
    if node.kind == "multmatrix":
        inner = _matrix_of(node)
        m = _compose(matrix, inner)
        return sum(volume_of(c, m) for c in node.children)
    if node.kind in ("group", "union", "color", "render"):
        return sum(volume_of(c, matrix) for c in node.children)
    if node.kind == "difference":
        if not node.children:
            return 0.0
        return volume_of(node.children[0], matrix)
    if node.kind == "intersection":
        if not node.children:
            return 0.0
        return min(volume_of(c, matrix) for c in node.children)

    scale = abs(_det3(matrix))
    if node.kind == "cube":
        size = node.kwargs.get("size", node.args[0] if node.args else None)
        if isinstance(size, list):
            x, y, z = (float(v) for v in size)
        else:
            x = y = z = float(size)  # type: ignore[arg-type]
        return scale * x * y * z
    if node.kind == "cylinder":
        h = float(node.kwargs.get("h", 1.0))  # type: ignore[arg-type]
        r1 = node.kwargs.get("r1", node.kwargs.get("r"))
        r2 = node.kwargs.get("r2", node.kwargs.get("r"))
        if r1 is None or r2 is None:
            d = node.kwargs.get("d")
            r1 = r2 = (float(d) / 2.0) if d is not None else None  # type: ignore[arg-type]
        if r1 is None or r2 is None:
            raise Unknown(node.kind)
        a, b = float(r1), float(r2)  # type: ignore[arg-type]
        # The exact frustum for the IDEAL cylinder; the exported $fn polygon
        # is smaller, so order comparisons treat this as an upper bound.
        return scale * math.pi * h * (a * a + a * b + b * b) / 3.0
    if node.kind == "sphere":
        r = node.kwargs.get("r")
        if r is None:
            d = node.kwargs.get("d")
            r = (float(d) / 2.0) if d is not None else None  # type: ignore[arg-type]
        if r is None:
            raise Unknown(node.kind)
        return scale * 4.0 / 3.0 * math.pi * float(r) ** 3  # type: ignore[arg-type]
    if node.kind == "polyhedron":
        points = node.kwargs.get("points")
        faces = node.kwargs.get("faces", node.kwargs.get("triangles"))
        if not isinstance(points, list) or not isinstance(faces, list):
            raise Unknown(node.kind)
        total = 0.0
        for face in faces:
            if not isinstance(face, list) or len(face) < 3:
                continue
            p0 = points[int(face[0])]
            for k in range(1, len(face) - 1):
                p1, p2 = points[int(face[k])], points[int(face[k + 1])]
                total += (
                    p0[0] * (p1[1] * p2[2] - p2[1] * p1[2])
                    - p1[0] * (p0[1] * p2[2] - p2[1] * p0[2])
                    + p2[0] * (p0[1] * p1[2] - p1[1] * p0[2])
                )
        return scale * abs(total) / 6.0
    raise Unknown(node.kind)


def _apply(matrix, point):
    return tuple(sum(matrix[r][k] * point[k] for k in range(3)) + matrix[r][3] for r in range(3))


def _plane(normal, point) -> tuple[float, float, float, float]:
    length = math.sqrt(sum(n * n for n in normal))
    if length == 0:
        raise CsgError("degenerate plane normal")
    n = tuple(v / length for v in normal)
    offset = sum(n[k] * point[k] for k in range(3))
    # Round FIRST, then orient: deciding the flip on unrounded floats let two
    # planes identical after rounding canonicalize to opposite orientations
    # (PR #125 review, F5).
    rounded = (round(n[0], 9), round(n[1], 9), round(n[2], 9), round(offset, 9))
    for component in rounded:
        if component > 0:
            break
        if component < 0:
            rounded = tuple(-v if v != 0 else 0.0 for v in rounded)  # type: ignore[assignment]
            break
    return rounded  # type: ignore[return-value]


def planes_of(node: Node, matrix=_IDENTITY) -> set[tuple[float, float, float, float]]:
    """The flat face planes of the subtree: cube faces and cylinder caps,
    transformed. Raises Unknown for any node outside the modelled set —
    spheres contribute no flat faces and are fine."""
    if node.kind == "multmatrix":
        m = _compose(matrix, _matrix_of(node))
        out: set[tuple[float, float, float, float]] = set()
        for c in node.children:
            out |= planes_of(c, m)
        return out
    if node.kind in ("group", "union", "difference", "intersection", "color", "render"):
        out = set()
        for c in node.children:
            out |= planes_of(c, matrix)
        return out

    linear = tuple(tuple(matrix[r][k] for k in range(3)) for r in range(3))
    det = _det3(linear)
    if abs(det) < 1e-15:
        raise CsgError("singular transform")
    # inverse-transpose for normals (cofactor matrix / det; det cancels in
    # normalization, so the cofactor rows serve directly).
    cof = (
        (
            linear[1][1] * linear[2][2] - linear[1][2] * linear[2][1],
            linear[1][2] * linear[2][0] - linear[1][0] * linear[2][2],
            linear[1][0] * linear[2][1] - linear[1][1] * linear[2][0],
        ),
        (
            linear[0][2] * linear[2][1] - linear[0][1] * linear[2][2],
            linear[0][0] * linear[2][2] - linear[0][2] * linear[2][0],
            linear[0][1] * linear[2][0] - linear[0][0] * linear[2][1],
        ),
        (
            linear[0][1] * linear[1][2] - linear[0][2] * linear[1][1],
            linear[0][2] * linear[1][0] - linear[0][0] * linear[1][2],
            linear[0][0] * linear[1][1] - linear[0][1] * linear[1][0],
        ),
    )

    def plane(local_normal, local_point):
        world_normal = tuple(sum(cof[r][k] * local_normal[k] for k in range(3)) for r in range(3))
        return _plane(world_normal, _apply(matrix, local_point))

    if node.kind == "cube":
        size = node.kwargs.get("size", node.args[0] if node.args else None)
        if isinstance(size, list):
            x, y, z = (float(v) for v in size)
        else:
            x = y = z = float(size)  # type: ignore[arg-type]
        center = bool(node.kwargs.get("center", False))
        lo = (-x / 2, -y / 2, -z / 2) if center else (0.0, 0.0, 0.0)
        hi = (x / 2, y / 2, z / 2) if center else (x, y, z)
        return {
            plane((1, 0, 0), (lo[0], 0, 0)),
            plane((1, 0, 0), (hi[0], 0, 0)),
            plane((0, 1, 0), (0, lo[1], 0)),
            plane((0, 1, 0), (0, hi[1], 0)),
            plane((0, 0, 1), (0, 0, lo[2])),
            plane((0, 0, 1), (0, 0, hi[2])),
        }
    if node.kind == "cylinder":
        h = float(node.kwargs.get("h", 1.0))  # type: ignore[arg-type]
        center = bool(node.kwargs.get("center", False))
        z0, z1 = (-h / 2, h / 2) if center else (0.0, h)
        return {plane((0, 0, 1), (0, 0, z0)), plane((0, 0, 1), (0, 0, z1))}
    if node.kind == "sphere":
        return set()
    raise Unknown(node.kind)
