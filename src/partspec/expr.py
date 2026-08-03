"""Evaluate a `requires` predicate and record what it read.

Parameter predicates are not measurements (SPEC-contract.md 5). A `requires`
check reports the expression and the *values of the operands it read*, so a
failure states the inputs that produced it rather than a bare `false` the reader
has to re-derive.

The restricted grammar is a **legibility** boundary, not a security one — the
contract is already arbitrary Python (D6), so there is nothing here to protect.
The point is that an expression the tool can print operands for is worth more
than one it can only report as false.

Spec: SPEC-contract.md section 5.1.
"""

from __future__ import annotations

import ast
from typing import Any

from .status import ContractError

__all__ = ["evaluate", "operands_of"]

_ALLOWED = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    # arithmetic
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    # logic and comparison
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

_REJECTION_HINTS = {
    ast.Call: "calls are not allowed; compute the value in Python and pass it as a parameter",
    ast.Attribute: "attribute access is not allowed; the namespace is the declared parameters",
    ast.Subscript: "indexing is not allowed; declare the component as its own parameter",
    ast.Lambda: "lambdas are not allowed",
    ast.IfExp: "conditional expressions are not allowed; declare two checks instead",
}


def _parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ContractError(f"could not parse expression {expr!r}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, _ALLOWED):
            continue
        hint = next(
            (h for kind, h in _REJECTION_HINTS.items() if isinstance(node, kind)),
            f"{type(node).__name__} is not allowed in a requires expression",
        )
        raise ContractError(f"in {expr!r}: {hint}")
    return tree


def operands_of(expr: str) -> tuple[str, ...]:
    """Names the expression reads, in source order.

    Sorted by source position rather than taken from `ast.walk`, which is
    breadth-first and therefore yields names by tree depth: `z + a * z + m`
    would come back as (z, m, a). The order reaches a report that gets diffed,
    so it should match what the author wrote.
    """
    names = [n for n in ast.walk(_parse(expr)) if isinstance(n, ast.Name)]
    names.sort(key=lambda n: (n.lineno, n.col_offset))
    seen: dict[str, None] = {}
    for node in names:
        seen.setdefault(node.id, None)
    return tuple(seen)


def evaluate(expr: str, params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Evaluate `expr` against `params`, returning (result, operands read).

    An expression referencing an undeclared name is a **contract error**, not a
    failing check: a claim the tool cannot evaluate has not been disproven, and
    reporting it as a failure would be a different lie from the one this project
    is built to prevent, but a lie all the same.
    """
    tree = _parse(expr)
    names = operands_of(expr)

    missing = [n for n in names if n not in params]
    if missing:
        known = ", ".join(sorted(params)) or "none"
        raise ContractError(
            f"in {expr!r}: undeclared parameter(s) {', '.join(missing)} (declared: {known})"
        )

    namespace = {name: params[name] for name in names}
    try:
        # No builtins: the grammar above already excludes calls, so there is
        # nothing to call, and an empty builtins dict keeps that true if the
        # grammar is ever widened carelessly.
        result = eval(compile(tree, "<requires>", "eval"), {"__builtins__": {}}, namespace)  # noqa: S307
    except ZeroDivisionError as exc:
        raise ContractError(f"in {expr!r}: division by zero") from exc
    except TypeError as exc:
        raise ContractError(f"in {expr!r}: {exc}") from exc

    return bool(result), namespace


def describe(expr: str, operands: dict[str, Any]) -> str:
    """A one-line explanation of an evaluated predicate, for `detail`."""
    values = ", ".join(f"{k}={v!r}" for k, v in operands.items())
    return f"{expr} is false with {values}" if values else f"{expr} is false"
