"""Advisory lint over CAD source — about the source, never the part (#26).

The audit-settled scope: tier 1 is ENGINE-FREE and ships here — rules a static
read of the source can decide. Tier 2 (coincident-face epsilon, `difference()`
ordering) needs the engine's constant-folded `.csg` tree and is deferred behind
its prior-art survey (see docs/LINT.md).

Findings are advisory and never a verdict on the part: the exit code says the
lint RAN; the findings are data. A lint that failed a build over a style
observation would be a verdict the source never earned — and one that stayed
silent about a rule it could not evaluate would be the other failure, so
anything tier 2 will own is absent from the registry entirely rather than
half-present.

Every rule's exact predicate, rationale, and a real example live in
docs/LINT.md; the registry here and that document are held together by test.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "LINT_SCHEMA_VERSION",
    "RULES",
    "TIER2_RULES",
    "Finding",
    "LintError",
    "lint_path",
    "lint_scad_tier2",
]

LINT_SCHEMA_VERSION = 2

MAGIC_EXEMPT = 2.0
"""Numeric literals with |value| <= 2 are never magic: 0/1 are structure, and
the -1/+2 boolean-overshoot idiom (skills/openscad-authoring rule 3) must not
be flagged by the tool whose own skills teach it."""

MODULE_LINE_LIMIT = 40
FUNCTION_LINE_LIMIT = 60

RULES = {
    "scad-unused-top-level": "a top-level variable the geometry never reads",
    "scad-magic-number": "a numeric literal in geometry with no name",
    "scad-module-size": f"a module body over {MODULE_LINE_LIMIT} lines",
    "py-magic-number": "a numeric literal in a call inside a function body",
    "py-function-size": f"a function body over {FUNCTION_LINE_LIMIT} lines",
    "csg-difference-order": "a difference() whose first child is not the largest",
    "csg-coincident-face": "a subtrahend sharing a face plane with its minuend",
}

TIER2_RULES = ("csg-difference-order", "csg-coincident-face")
"""Geometry-dependent rules over the engine's constant-folded `.csg` export
(#118). They MAY require the engine and MUST report `unsupported` — never
silent absence — when it is missing (the audit's honesty shape). Findings
carry line 0: the tree is constant-folded, so no source line exists to name;
the message describes the geometry instead."""


class LintError(Exception):
    """The input cannot be linted: missing file or unknown source kind."""


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    file: str
    line: int
    message: str

    def to_json(self) -> dict[str, object]:
        return {"rule": self.rule, "file": self.file, "line": self.line, "message": self.message}


def lint_path(path: Path) -> list[Finding]:
    if not path.is_file():
        raise LintError(f"no source at {path}")
    try:
        path.read_bytes()
    except OSError as exc:
        raise LintError(f"cannot read {path}: {exc}") from None
    if path.suffix == ".scad":
        return _lint_scad(path)
    if path.suffix == ".py":
        return _lint_python(path)
    raise LintError(f"{path.name}: lint reads .scad and .py sources, not {path.suffix or 'this'}")


# --------------------------------------------------------------------------
# OpenSCAD — over the noise-stripped text the engine helpers already produce
# --------------------------------------------------------------------------


def _strip_preserving_lines(raw: str) -> str:
    """Comments and strings blanked, NEWLINES KEPT.

    A character scan, not ordered regexes: the first draft stripped `//`
    before strings, so a URL inside a string swallowed the rest of the line
    and the dangling quote blanked real code — the exact hazard the engine's
    `_strip_noise` docstring warns about, reintroduced one module over
    (PR #119 re-review, N2). And unlike `_strip_noise`, block comments keep
    their newlines: findings carry file:line, and the line must be the
    author's line (F3)."""
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == '"':
            out.append('"')
            i += 1
            while i < n and raw[i] != '"':
                if raw[i] == "\\":
                    i += 1
                elif raw[i] == "\n":
                    out.append("\n")
                i += 1
            if i < n:
                out.append('"')
                i += 1
        elif raw.startswith("//", i):
            while i < n and raw[i] != "\n":
                i += 1
        elif raw.startswith("/*", i):
            end = raw.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("\n" * raw.count("\n", i, end))
            i = end
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _entry_top_level(stripped: str) -> dict[str, int]:
    """name -> line of the ENTRY file's own top-level assignments.

    Deliberately narrower than the -D guard's closure-wide walk: lint speaks
    about the file it was pointed at, and flagging a parameter library's
    internals at the entry's include line taught nothing (PR #119, F4).
    """
    names: dict[str, int] = {}
    depth = 0
    for i, line in enumerate(stripped.splitlines(), start=1):
        if depth == 0:
            m = re.match(r"\s*(\$?\w+)\s*=", line)
            if m:
                names.setdefault(m.group(1), i)
        # ALL bracket kinds, like the engine's walker: a brace-only count
        # mistook named arguments in multi-line parenthesized calls for
        # top-level assignments (PR #119 re-review, N1 — live on the repo's
        # own open_box fixture).
        depth += sum(line.count(b) for b in "{([") - sum(line.count(b) for b in "})]")
    return names


def _lint_scad(path: Path) -> list[Finding]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    stripped = _strip_preserving_lines(raw)
    findings: list[Finding] = []

    declared = _entry_top_level(stripped)
    for name, line in sorted(declared.items()):
        if name.startswith("$"):
            continue  # $fn etc. are read by the engine, not the text
        # Everything except this variable's own assignment lines; a reference
        # anywhere else (geometry, another assignment's right side) is a use.
        others = "\n".join(
            ln for ln in stripped.splitlines() if not re.match(rf"\s*{re.escape(name)}\s*=", ln)
        )
        if not re.search(rf"\b{re.escape(name)}\b", others):
            findings.append(
                Finding(
                    "scad-unused-top-level",
                    str(path),
                    line,
                    f"'{name}' is declared but the geometry never reads it "
                    f"(legitimate when it exists only for a contract's `requires` — "
                    f"then say so in a comment)",
                )
            )

    assignment = re.compile(r"^\s*\$?\w+\s*=")
    # Whole scientific literals match as one number (1e-3 is 0.001, not a
    # magic 3 — PR #119, F5); a bare digit right after e/E is never a number.
    number = re.compile(r"(?<![\w.])(?<![eE])(?<![eE][+-])-?\d+\.?\d*(?:[eE][+-]?\d+)?(?![\w.])")

    # The exemption is the STATEMENT's, not the line's. This matched
    # `^\s*\w+\s*=` per line, so an assignment wrapped across lines — the normal
    # formatting for a lookup table — was exempt on its first line and flagged
    # on every other:
    #
    #     plate = [60, 40, 4];        -> 0 findings
    #     plate = [                   -> 3 findings
    #       60, 40, 4                    (same constant, same name)
    #     ];
    #
    # The rule's own rationale is that a magic number is *unnameable*; these are
    # named, so the code was wrong rather than the doc (v0.7.0 pre-tag audit).
    #
    # Opening only at `depth == 0`, exactly as `_entry_top_level` does above and
    # for the same reason. `name =` inside brackets is a NAMED ARGUMENT or a
    # module signature default, not an assignment statement, and treating one as
    # an opener suppressed everything up to the next `;`. Measured on the repo's
    # own `tests/fixtures/open_box.scad`, whose `points = [` is an argument of
    # `polyhedron(`: all 28 findings vanished (PR #160 review). That is the
    # third time this fixture has caught a brace-blind scan; the depth counter
    # exists because of the first two.
    #
    # An assignment then runs to its terminating `;`, which is how OpenSCAD
    # parses it — but only while brackets are balanced, so a statement that
    # never terminates cannot silence the rest of the file.
    depth = 0
    in_assignment = False
    for i, line_text in enumerate(stripped.splitlines(), start=1):
        looks_like_assignment = bool(assignment.match(line_text))
        # Only a TOP-LEVEL one continues onto later lines. A `name =` inside
        # brackets exempts its own line, as it always has — that is the named
        # argument and signature-default case — but claims nothing about what
        # follows.
        opens = depth == 0 and not in_assignment and looks_like_assignment
        skip = looks_like_assignment or in_assignment
        # Parens and brackets ONLY, unlike `_entry_top_level` above, which also
        # counts braces because it wants the file's top-level names. The
        # question here is different: an assignment STATEMENT is legal at any
        # brace depth — a module-local constant is ordinary OpenSCAD — but can
        # never appear inside `(` or `[`, which is exactly where a named
        # argument and a signature default live. So paren/bracket depth IS the
        # predicate, and counting braces made the exemption top-level-only:
        #
        #     module plate() { spec = [
        #         60, 40, 400
        #       ]; cube(spec); }        -> 3 findings on a named constant
        #
        # which `docs/LINT.md` says cannot happen. A stray `}` also drove the
        # counter negative and disabled the exemption for the rest of the file
        # (PR #160 review, R1).
        depth += sum(line_text.count(b) for b in "([") - sum(line_text.count(b) for b in ")]")
        if skip:
            # Closed by its `;`, and abandoned once brackets rebalance, so a
            # statement that never terminates cannot silence the rest of the
            # file (`x = 5` with no semicolon did, briefly).
            in_assignment = (opens or in_assignment) and ";" not in line_text and depth > 0
            continue
        if re.match(r"\s*(include|use)\b", line_text):
            continue
        for m in number.finditer(line_text):
            value = float(m.group(0))
            if abs(value) <= MAGIC_EXEMPT:
                continue
            findings.append(
                Finding(
                    "scad-magic-number",
                    str(path),
                    i,
                    f"{m.group(0)} has no name; a magic number is unnameable by -D, "
                    f"`param`, or a report (skills/openscad-authoring rule 1)",
                )
            )

    for m in re.finditer(r"\bmodule\s+(\w+)\s*\([^)]*\)\s*\{", stripped):
        depth, pos = 1, m.end()
        while depth and pos < len(stripped):
            if stripped[pos] == "{":
                depth += 1
            elif stripped[pos] == "}":
                depth -= 1
            pos += 1
        body_lines = stripped.count("\n", m.end(), pos)
        if body_lines > MODULE_LINE_LIMIT:
            findings.append(
                Finding(
                    "scad-module-size",
                    str(path),
                    stripped.count("\n", 0, m.start()) + 1,
                    f"module '{m.group(1)}' spans {body_lines} lines "
                    f"(limit {MODULE_LINE_LIMIT}); split at feature boundaries "
                    f"(skills/openscad-authoring rule 5)",
                )
            )

    return sorted(findings, key=lambda f: (f.line, f.rule))


# --------------------------------------------------------------------------
# Python models — stdlib ast, the same machinery expr.py already relies on
# --------------------------------------------------------------------------


def _lint_python(path: Path) -> list[Finding]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(raw, filename=str(path))
    except SyntaxError as exc:
        raise LintError(f"{path.name}: not parseable Python: {exc}") from None

    findings: list[Finding] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        span = (fn.body[-1].end_lineno or fn.lineno) - fn.body[0].lineno + 1
        if span > FUNCTION_LINE_LIMIT:
            findings.append(
                Finding(
                    "py-function-size",
                    str(path),
                    fn.lineno,
                    f"'{fn.name}' spans {span} lines (limit {FUNCTION_LINE_LIMIT}); "
                    f"decompose features into named functions",
                )
            )
        seen: set[tuple[int, int]] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            # Positional AND keyword arguments — build123d/CadQuery idiom is
            # keyword-heavy (radius=, depth=), and the first draft was silent
            # exactly there (PR #119 review, F1). Traversal prunes at nested
            # Call boundaries (each call reports its own arguments once, F2)
            # and at Lambda (a lambda body's constants are its own affair).
            exprs = list(node.args) + [kw.value for kw in node.keywords]
            for value, where in _numeric_constants(exprs):
                key = (where.lineno, where.col_offset)
                if abs(value) <= MAGIC_EXEMPT or key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        "py-magic-number",
                        str(path),
                        where.lineno,
                        f"{value} has no name; hoist it to a parameter with a "
                        f"default (skills/build123d-authoring rule 1)",
                    )
                )
    return sorted(findings, key=lambda f: (f.line, f.rule))


def _numeric_constants(exprs: list[ast.expr]):
    """(value, node) for every numeric literal in the expressions, signs kept
    (`-90` reports as -90, not 90), pruned at Call and Lambda boundaries."""
    stack: list[ast.AST] = list(exprs)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call | ast.Lambda):
            continue
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, int | float)
            and not isinstance(node.operand.value, bool)
        ):
            yield -node.operand.value, node.operand
            continue
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            yield node.value, node
            continue
        stack.extend(ast.iter_child_nodes(node))


# --------------------------------------------------------------------------
# tier 2 — over the engine's constant-folded .csg export (#118)
# --------------------------------------------------------------------------


def lint_scad_tier2(path: Path, executable: str | None) -> tuple[list[Finding], list[dict]]:
    """The two geometry rules, or honest refusals.

    Returns (findings, unsupported) where each unsupported entry is
    {"rule", "reason"} — a rule that could not run says so per file, because
    a rule silently absent reads as a clean bill (#118, audit bullet 1).
    """
    import subprocess
    import tempfile

    from . import csg

    if executable is None:
        reason = "openscad is not installed; the rule reads the engine's .csg export"
        return [], [{"rule": r, "reason": reason} for r in TIER2_RULES]

    with tempfile.TemporaryDirectory(prefix="partspec-lint-") as tmp:
        out = Path(tmp) / "tree.csg"
        try:
            proc = subprocess.run(
                [executable, "-o", str(out), str(path)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # A bad PARTSPEC_OPENSCAD or a hung export must be an entry, not
            # an exit-4 crash that eats every file's tier-1 findings too
            # (PR #125 review, F1).
            reason = f"the .csg export could not run: {exc}"
            return [], [{"rule": r, "reason": reason} for r in TIER2_RULES]
        if proc.returncode != 0 or not out.is_file():
            stderr_lines = (proc.stderr or "").strip().splitlines()
            detail = stderr_lines[-1] if stderr_lines else f"openscad exited {proc.returncode}"
            reason = f"the .csg export failed: {detail}"
            return [], [{"rule": r, "reason": reason} for r in TIER2_RULES]
        raw = out.read_text(encoding="utf-8", errors="replace")
        if '"' in raw:
            # BEFORE the parse, on the raw bytes: the format does not escape
            # string interiors (text(), import()), so a quote can silently
            # reshape the parse — and a detector running over the parsed tree
            # was bypassable by hiding the string in a %-dropped statement
            # (PR #125 re-review). A quote can only ever become a string
            # token or a parse error, so refusing on the character itself is
            # airtight and loses nothing on quote-free files.
            reason = (
                "the export carries string content, which the .csg format does "
                "not escape — no parse of it can be trusted, so the file is "
                "refused whole"
            )
            return [], [{"rule": r, "reason": reason} for r in TIER2_RULES]
        try:
            nodes = csg.parse_csg(raw)
        except csg.CsgError as exc:
            return [], [{"rule": r, "reason": f"unreadable .csg: {exc}"} for r in TIER2_RULES]

    findings: list[Finding] = []
    unsupported: list[dict] = []
    refused: set[str] = set()

    def walk(items: list, matrix) -> None:
        for node in items:
            inner = matrix
            if node.kind == "multmatrix":
                inner = csg._compose(matrix, csg._matrix_of(node))
            if node.kind == "difference" and len(node.children) >= 2:
                _judge_difference(node, matrix)
            walk(node.children, inner)

    def _judge_difference(node, matrix) -> None:
        minuend, *cutters = node.children
        try:
            first = csg.volume_of(minuend, matrix)
            rest = [csg.volume_of(c, matrix) for c in cutters]
            # The volumes are analytic upper bounds (union = sum of children,
            # cylinders as ideal solids of revolution); the order verdict
            # only fires when a cutter's bound exceeds the minuend's, which
            # under upper-bound-vs-upper-bound is a heuristic and says so.
            biggest = max(rest)
            if biggest > first:
                findings.append(
                    Finding(
                        "csg-difference-order",
                        str(path),
                        0,
                        f"a difference() subtracts from a {first:.6g} mm3 first child "
                        f"while a later child measures {biggest:.6g} mm3 — the first "
                        f"child is the material (skills/openscad-authoring rule 2); "
                        f"volumes are analytic upper bounds over the folded tree",
                    )
                )
        except (csg.Unknown, csg.CsgError, TypeError, ValueError, IndexError, KeyError) as exc:
            if "csg-difference-order" not in refused:
                refused.add("csg-difference-order")
                reason = (
                    f"the tree contains {exc.args[0]}(), which the volume model does not cover"
                    if isinstance(exc, csg.Unknown)
                    else f"the tree could not be evaluated: {exc}"
                )
                unsupported.append({"rule": "csg-difference-order", "reason": reason})
        try:
            base = csg.planes_of(minuend, matrix)
            for cutter in cutters:
                shared = base & csg.planes_of(cutter, matrix)
                for plane in sorted(shared):
                    findings.append(
                        Finding(
                            "csg-coincident-face",
                            str(path),
                            0,
                            f"a cutter ends exactly on the material's face plane "
                            f"(normal ({plane[0]:g}, {plane[1]:g}, {plane[2]:g}), "
                            f"offset {plane[3]:g}) — overshoot it "
                            f"(skills/openscad-authoring rule 3; FAILURE-MODES entry 2)",
                        )
                    )
        except (csg.Unknown, csg.CsgError, TypeError, ValueError, IndexError, KeyError) as exc:
            if "csg-coincident-face" not in refused:
                refused.add("csg-coincident-face")
                reason = (
                    f"the tree contains {exc.args[0]}(), which the plane model does not cover"
                    if isinstance(exc, csg.Unknown)
                    else f"the tree could not be evaluated: {exc}"
                )
                unsupported.append({"rule": "csg-coincident-face", "reason": reason})

    try:
        walk(nodes, csg._IDENTITY)
    except (csg.CsgError, TypeError, ValueError, IndexError, KeyError) as exc:
        for rule in TIER2_RULES:
            if rule not in refused:
                unsupported.append({"rule": rule, "reason": f"the tree could not be walked: {exc}"})
    return findings, unsupported
