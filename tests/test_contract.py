"""The contract API, the expression evaluator, and target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from partspec import Part, openscad
from partspec.expr import evaluate, operands_of
from partspec.status import ContractError
from partspec.target import Target, TargetError, resolve

FIXTURES = Path(__file__).parent / "fixtures"


def _part(**params) -> Part:
    return Part("p", openscad("x.scad", **params))


# --------------------------------------------------------------------------
# expression evaluation
# --------------------------------------------------------------------------


def test_evaluate_returns_result_and_operands():
    ok, operands = evaluate("a + b <= c", {"a": 1, "b": 2, "c": 5, "unused": 99})
    assert ok is True
    assert operands == {"a": 1, "b": 2, "c": 5}, "only the names actually read"


def test_chained_comparisons_record_every_operand():
    ok, operands = evaluate("0 < angle < 360 / pins", {"angle": 40, "pins": 2})
    assert ok is True
    assert operands == {"angle": 40, "pins": 2}


def test_operand_order_follows_the_source():
    """Not ast.walk order, which is breadth-first and would give (z, m, a).
    The order reaches a report that gets diffed, so it should match what the
    author wrote."""
    assert operands_of("z + a * z + m") == ("z", "a", "m")


def test_failure_reports_the_inputs_that_caused_it():
    ok, operands = evaluate("r + t/2 <= shell", {"r": 1.0, "t": 0.2, "shell": 1.0})
    assert ok is False
    assert operands == {"r": 1.0, "t": 0.2, "shell": 1.0}


def test_undeclared_name_is_a_contract_error_not_a_failure():
    """A claim the tool cannot evaluate has not been disproven."""
    with pytest.raises(ContractError, match="undeclared"):
        evaluate("a < b", {"a": 1})


@pytest.mark.parametrize(
    "expr",
    [
        "max(a, b) > 1",  # calls
        "a.b > 1",  # attribute access
        "a[0] > 1",  # subscript
        "(lambda: 1)() > 0",  # lambda
        "1 if a else 2",  # conditional
    ],
)
def test_grammar_is_restricted_for_legibility(expr):
    """Not a security boundary — the contract is already arbitrary Python. The
    point is that an expression whose operands can be printed is worth more than
    one that can only be reported as false."""
    with pytest.raises(ContractError):
        evaluate(expr, {"a": 1, "b": 2})


def test_syntax_error_is_reported_with_the_expression():
    with pytest.raises(ContractError, match="could not parse"):
        evaluate("a <", {"a": 1})


def test_division_by_zero_is_a_contract_error():
    with pytest.raises(ContractError, match="division by zero"):
        evaluate("1 / n > 0", {"n": 0})


# --------------------------------------------------------------------------
# declaration
# --------------------------------------------------------------------------


def test_checks_record_their_phase():
    p = _part(a=1.0)
    p.requires("a > 0")
    p.envelope(max=(10, 10, 10))
    assert [c.phase for c in p.checks] == ["parameter", "geometry"]


def test_declaration_order_is_preserved():
    """The report lists checks in declaration order, so this is load-bearing."""
    p = _part(a=1.0)
    p.watertight().requires("a > 0").solid_count(1)
    assert [c.id for c in p.checks] == ["watertight", "a_0", "solid_count"]


def test_duplicate_ids_are_refused():
    """Ids are the join key a report diff relies on."""
    p = _part()
    p.watertight()
    with pytest.raises(ContractError, match="duplicate check id"):
        p.watertight()


def test_duplicate_kinds_are_fine_with_explicit_ids():
    p = _part()
    p.volume(min=1).volume(max=99, id="volume_ceiling")
    assert len(p.checks) == 2


def test_param_must_name_a_declared_parameter():
    """Catches a typo at declaration rather than reporting a mystery failure."""
    p = _part(bore_d=8.0)
    with pytest.raises(ContractError, match="not a declared parameter"):
        p.param("bore_diameter", min=1)


def test_a_part_needs_an_id():
    with pytest.raises(ContractError):
        Part("", openscad("x.scad"))


def test_source_records_the_engine_explicitly():
    """Never inferred from the file extension: a .py could be either Python
    engine, and guessing is the implicitness this project removes."""
    assert openscad("a.scad").engine == "openscad"


# --------------------------------------------------------------------------
# target resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "path", "factory"),
    [
        ("a/b.py:lock", "a/b.py", "lock"),
        ("a/b.py", "a/b.py", None),
        ("./rel.py:x", "rel.py", "x"),  # Path normalises the leading ./
    ],
)
def test_target_parse(spec, path, factory):
    t = Target.parse(spec)
    assert (str(t.path), t.factory) == (path, factory)


def test_target_slug_distinguishes_factories():
    """So co-located targets never clobber each other's report."""
    assert Target.parse("a/spec.py:lock").slug == "spec-lock"
    assert Target.parse("a/spec.py:pin").slug == "spec-pin"


def test_missing_contract_is_a_target_error():
    with pytest.raises(TargetError, match="not found"):
        resolve("does/not/exist.py")


def test_ambiguity_lists_the_available_factories(tmp_path: Path):
    """The error message is the discovery mechanism — no separate list verb."""
    module = tmp_path / "many.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def first() -> Part: return Part('a', openscad('x.scad'))\n"
        "def second() -> Part: return Part('b', openscad('x.scad'))\n"
    )
    with pytest.raises(TargetError) as exc:
        resolve(str(module))
    assert "many.py:first" in str(exc.value)
    assert "many.py:second" in str(exc.value)


def test_a_lone_factory_needs_no_name(tmp_path: Path):
    module = tmp_path / "one.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def only() -> Part: return Part('a', openscad('x.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.id == "a"


def test_unannotated_helpers_are_not_factories(tmp_path: Path):
    """The `-> Part` annotation is the declaration; a helper that happens to
    build a Part stays private to the contract."""
    module = tmp_path / "helper.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def helper(): return Part('h', openscad('x.scad'))\n"
        "def real() -> Part: return Part('r', openscad('x.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.id == "r"


def test_no_factories_is_a_target_error(tmp_path: Path):
    module = tmp_path / "none.py"
    module.write_text("VALUE = 1\n")
    with pytest.raises(TargetError, match="no part factories"):
        resolve(str(module))


def test_relative_source_anchors_to_the_contract_not_the_cwd(tmp_path: Path):
    """Otherwise a contract works or fails depending on the shell's history."""
    (tmp_path / "model.scad").write_text("cube(1);\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        "def p() -> Part: return Part('p', openscad('model.scad'))\n"
    )
    part, _ = resolve(str(module))
    assert part.source.path == (tmp_path / "model.scad").resolve()
    assert part.source.path.is_file()


def test_absolute_source_is_left_alone(tmp_path: Path):
    target = tmp_path / "abs.scad"
    target.write_text("cube(1);\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n"
        f"def p() -> Part: return Part('p', openscad({str(target)!r}))\n"
    )
    part, _ = resolve(str(module))
    assert part.source.path == target


def test_contract_raising_on_import_is_a_target_error(tmp_path: Path):
    module = tmp_path / "boom.py"
    module.write_text("raise ValueError('bang')\n")
    with pytest.raises(TargetError, match="raised on import"):
        resolve(str(module))
