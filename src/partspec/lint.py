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

__all__ = ["Finding", "LINT_SCHEMA_VERSION", "LintError", "RULES", "lint_path"]

LINT_SCHEMA_VERSION = 1

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
    "py-magic-number": "a numeric literal in a call inside a factory",
    "py-function-size": f"a function body over {FUNCTION_LINE_LIMIT} lines",
}


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
    if path.suffix == ".scad":
        return _lint_scad(path)
    if path.suffix == ".py":
        return _lint_python(path)
    raise LintError(f"{path.name}: lint reads .scad and .py sources, not {path.suffix or 'this'}")


# --------------------------------------------------------------------------
# OpenSCAD — over the noise-stripped text the engine helpers already produce
# --------------------------------------------------------------------------


def _lint_scad(path: Path) -> list[Finding]:
    from .engines.openscad import _strip_noise, top_level_variables

    raw = path.read_text(encoding="utf-8", errors="replace")
    stripped = _strip_noise(raw)
    findings: list[Finding] = []

    declared = top_level_variables(path)
    for name in sorted(declared):
        if name.startswith("$"):
            continue  # $fn etc. are read by the engine, not the text
        # Everything except this variable's own assignment lines; a reference
        # anywhere else (geometry, another assignment's right side) is a use.
        others = "\n".join(
            ln for ln in stripped.splitlines() if not re.match(rf"\s*{re.escape(name)}\s*=", ln)
        )
        if not re.search(rf"\b{re.escape(name)}\b", others):
            line = next(
                (i + 1 for i, ln in enumerate(raw.splitlines()) if re.match(rf"\s*{name}\s*=", ln)),
                1,
            )
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
    number = re.compile(r"(?<![\w.])-?\d+\.?\d*(?![\w.])")
    for i, line_text in enumerate(_strip_noise(raw).splitlines(), start=1):
        if assignment.match(line_text) or re.match(r"\s*(include|use)\b", line_text):
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
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            for top_arg in node.args:
                for arg in ast.walk(top_arg):
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, int | float)
                        and not isinstance(arg.value, bool)
                        and abs(arg.value) > MAGIC_EXEMPT
                    ):
                        findings.append(
                            Finding(
                                "py-magic-number",
                                str(path),
                                arg.lineno,
                                f"{arg.value} has no name; hoist it to a parameter with a "
                                f"default (skills/build123d-authoring rule 1)",
                            )
                        )
    return sorted(findings, key=lambda f: (f.line, f.rule))
