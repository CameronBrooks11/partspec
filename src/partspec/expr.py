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


def _predicate_names(node: ast.expr, expr: str) -> list[ast.Name]:
    """Check `node` is a predicate, returning the bare Names in boolean position.

    A `requires` claim must be a *predicate*, because the result is adjudicated
    as true or false and Python will happily coerce anything. `requires("1")`
    passed. So did `requires("bore_d + 2*wall - plate_y")`, which reads like a
    clearance and is truthy for every value except exact equality — the check
    was decorative, and green.

    The rule is recursive, not top-level. `not (a - b)` is a `UnaryOp(Not)` and
    `a <= b and c` is a `BoolOp`, so a rule that inspected only the outermost
    node admitted both, and `not X` always returns a genuine `bool` so no
    result-type guard downstream can ever catch it.

    A bare `Name` is a predicate, because bool parameters are a supported type
    (`openscad.py` renders them as `true`/`false`) and `is_threaded and pitch > 0`
    is an honest claim. Those names are returned so the caller can verify they
    really are bools *before* evaluating — a post-hoc check cannot, since
    `and`/`or` short-circuit and never bind the right-hand name.
    """
    if isinstance(node, ast.Compare):
        # Pairwise over a possibly-chained comparison: `0 < x < 10` is
        # (0, x) then (x, 10), so the left operands are left + all but the last
        # comparator.
        for left, op, right in zip(
            [node.left, *node.comparators[:-1]], node.ops, node.comparators, strict=True
        ):
            if isinstance(op, ast.Eq | ast.GtE | ast.LtE) and ast.dump(left) == ast.dump(right):
                raise ContractError(
                    f"in {expr!r}: {ast.unparse(left)} is compared with itself, which is "
                    f"true whatever it equals; compare it against the value it must hold"
                )
        return []
    if isinstance(node, ast.BoolOp):
        return [n for value in node.values for n in _predicate_names(value, expr)]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _predicate_names(node.operand, expr)
    if isinstance(node, ast.Name):
        return [node]
    raise ContractError(
        f"in {expr!r}: a requires expression must be a predicate — a comparison, a bool "
        f"parameter, or those combined with and/or/not. {ast.unparse(node)!r} is a value, "
        f"and testing it for truthiness would pass for almost every input. Write the "
        f"comparison you mean, e.g. {ast.unparse(node)} >= 0"
    )


def _check_predicate(expr: str, tree: ast.Expression, params: dict[str, Any]) -> None:
    """Enforce the predicate grammar, and that boolean leaves are really bools."""
    bare = _predicate_names(tree.body, expr)
    for node in bare:
        value = params.get(node.id)
        if not isinstance(value, bool):
            raise ContractError(
                f"in {expr!r}: {node.id} is used as a condition but is "
                f"{type(value).__name__}, not a bool; compare it instead, e.g. {node.id} > 0"
            )


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

    if not names:
        raise ContractError(
            f"in {expr!r}: this reads no declared parameter, so it claims nothing about "
            f"the part and its result is the same on every run"
        )

    _check_predicate(expr, tree, params)

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

    # Backstop. The grammar above should make a non-bool result unreachable, so
    # this firing means the grammar has a hole — say so rather than coercing.
    if not isinstance(result, bool):
        raise ContractError(
            f"in {expr!r}: evaluated to {type(result).__name__}, not a bool; "
            f"a requires expression must state a condition"
        )
    return result, namespace


def describe(expr: str, operands: dict[str, Any]) -> str:
    """A one-line explanation of an evaluated predicate, for `detail`."""
    values = ", ".join(f"{k}={v!r}" for k, v in operands.items())
    return f"{expr} is false with {values}" if values else f"{expr} is false"
