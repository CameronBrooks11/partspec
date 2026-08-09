"""The contract API, the expression evaluator, and target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from partspec import Part, openscad
from partspec.contract import GEOMETRY_KINDS
from partspec.expr import evaluate, operands_of
from partspec.status import ContractError
from partspec.target import Target, TargetError, resolve

FIXTURES = Path(__file__).parent / "fixtures"


def _part(**params) -> Part:
    return Part("p", openscad("x.scad", **params))


# --------------------------------------------------------------------------
# expression evaluation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "why"),
    [
        ("bore_d + 2 * wall - plate_y", "reads like a clearance; truthy for all but equality"),
        ("a - b", "an arithmetic value, not a claim"),
        ("not (a - b)", "UnaryOp(Not) always yields a real bool, so no result guard sees it"),
        (
            "a <= b and c",
            "BoolOp with a non-bool leaf; short-circuits, so a post-hoc check misses it",
        ),
        ("a == a", "compared with itself — true whatever it equals"),
        ("b >= b", "the same tautology through a different operator"),
    ],
)
def test_a_requires_that_is_not_a_predicate_is_refused(expr: str, why: str):
    """`requires("1")` passed. So did `requires("bore_d + 2*wall - plate_y")`,
    which reads like a clearance and is truthy for every value except exact
    equality — decorative, and green.

    The rule has to be recursive: a top-level-node rule admits both `not (...)`
    and `... and c`, and `not X` always returns a genuine bool so nothing
    downstream can catch it. Rejection must also be value-independent, which is
    why the bool-leaf check runs before eval rather than on the result.
    """
    with pytest.raises(ContractError):
        evaluate(expr, {"a": 1, "b": 2, "c": 3, "bore_d": 40, "wall": 2, "plate_y": 30})


def test_a_bool_leaf_is_a_predicate_but_a_number_is_not():
    """Bool parameters are a supported type, so `is_threaded and pitch > 0` is an
    honest claim and must not be caught by the net above."""
    ok, _ = evaluate("is_threaded and pitch > 0", {"is_threaded": True, "pitch": 1.5})
    assert ok is True
    with pytest.raises(ContractError, match="not a bool"):
        evaluate("pitch and is_threaded", {"is_threaded": True, "pitch": 1.5})


def test_the_bool_leaf_check_does_not_depend_on_the_values():
    """`a <= b and c` short-circuits, so whether `c` is ever bound depends on the
    parameters. A guard that fired only sometimes would be worse than none."""
    for binding in ({"a": 1, "b": 2, "c": 3}, {"a": 3, "b": 2, "c": 3}):
        with pytest.raises(ContractError, match="not a bool"):
            evaluate("a <= b and c", binding)


def test_a_requires_that_reads_no_parameter_claims_nothing():
    with pytest.raises(ContractError, match="reads no declared parameter"):
        evaluate("1 > 0", {"a": 1})


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
    assert [c.id for c in p.checks] == ["watertight", "a_gt_0", "solid_count"]


def test_the_builds_id_is_reserved(tmp_path):
    """#134: the runner emits its own `builds` check; a contract shadowing
    the id put two same-id checks in one report and let a passing parameter
    check impersonate a failed build to check --render's gate."""
    p = _part(w=5.0)
    with pytest.raises(ContractError, match="reserved for the runner"):
        p.requires("w > 0", id="builds")
    with pytest.raises(ContractError, match="reserved for the runner"):
        p.watertight(id="builds")


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


# --------------------------------------------------------------------------
# topology — the one check a tier cannot answer
# --------------------------------------------------------------------------


def test_topology_records_the_axes_it_was_given():
    p = _part()
    p.topology(faces=6, edges=12, vertices=8)
    assert p.checks[0].kind == "topology"
    assert p.checks[0].limit is not None
    assert p.checks[0].limit.equals == (6, 12, 8)


def test_topology_may_constrain_a_subset():
    """A face count is often the whole claim; edge and vertex counts move with
    modelling choices that are not intent."""
    p = _part()
    p.topology(faces=6)
    assert p.checks[0].limit is not None
    assert p.checks[0].limit.equals == (6, None, None)


def test_topology_claiming_nothing_is_refused():
    """Caught at declaration, not left to adjudication: `equals=(None, None,
    None)` is a limit that constrains nothing, and a check that claims nothing
    must never be able to report pass."""
    p = _part()
    with pytest.raises(ContractError, match="at least one of faces"):
        p.topology()


def test_the_tier_specific_kinds_are_exactly_the_declared_ones():
    """v0 shipped `topology` as the single deliberate tier-gated kind, to make
    the capability-refusal path reachable; `hole_diameter` is the first BREP
    dimension that machinery existed for. Everything else must stay
    tier-neutral — a kind that silently becomes OCCT-only is a portability
    regression this pins."""
    from partspec.backends.mesh import CAPABILITIES as MESH
    from partspec.backends.occt import CAPABILITIES as OCCT

    occt_only = {
        "topology",
        "hole_diameter",
        "bolt_circle",
        "fillet_radius",
        "draft_angle",
    }
    for kind in occt_only:
        assert GEOMETRY_KINDS[kind] in OCCT
        assert GEOMETRY_KINDS[kind] not in MESH
    others = {v for k, v in GEOMETRY_KINDS.items() if k not in occt_only}
    assert others <= MESH & OCCT, "no other check may depend on the tier"


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


# --------------------------------------------------------------------------
# requires() slugs (#38)
# --------------------------------------------------------------------------


def test_each_comparison_operator_slugs_distinctly():
    # The id is the join key a future diff relies on; two different claims
    # must never alias. Pinned per operator.
    from partspec.contract import _slug

    assert _slug("x > 5") == "x_gt_5"
    assert _slug("x < 5") == "x_lt_5"
    assert _slug("x >= 5") == "x_ge_5"
    assert _slug("x <= 5") == "x_le_5"
    assert _slug("x == 5") == "x_eq_5"
    assert _slug("x != 5") == "x_ne_5"


def test_a_bracketing_pair_of_bounds_coexists():
    p = _part(x=1.0)
    p.requires("x > 0").requires("x < 10")
    assert [c.id for c in p.checks] == ["x_gt_0", "x_lt_10"]


def test_a_residual_collision_names_both_expressions():
    p = _part(x=1.0)
    long = "x > " + "0" * 80
    p.requires(long)
    with pytest.raises(ContractError) as exc:
        p.requires(long + "1")  # same 60-char prefix after truncation
    message = str(exc.value)
    assert long in message and long + "1" in message


# --------------------------------------------------------------------------
# hole_diameter declaration (#80)
# --------------------------------------------------------------------------


def test_hole_diameter_records_band_and_count():
    p = _part()
    p.hole_diameter(8.0, count=2, tol=0.1)
    spec = p.checks[0]
    assert spec.kind == "hole_diameter"
    assert spec.id == "hole_d8"
    assert spec.hole == {"d": 8.0, "count": 2}
    assert spec.limit is not None
    assert spec.limit.min == pytest.approx(7.9) and spec.limit.max == pytest.approx(8.1)


def test_hole_diameter_default_band_is_the_comparison_epsilon():
    from partspec.status import epsilon

    p = _part()
    p.hole_diameter(8.5)
    spec = p.checks[0]
    assert spec.id == "hole_d8_5", "a dot in an id would break the diff join key style"
    assert spec.limit is not None
    assert spec.limit.max - spec.limit.min == pytest.approx(2 * epsilon(8.5))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"d": 0}, "d > 0"),
        ({"d": -8.0}, "d > 0"),
        ({"d": float("nan")}, "d > 0"),
        ({"d": 8.0, "count": 0}, "count >= 1"),
        ({"d": 8.0, "count": 2.0}, "count >= 1"),
        ({"d": 8.0, "count": True}, "count >= 1"),
        ({"d": 8.0, "tol": 0.0}, "tol must be > 0"),
        ({"d": 8.0, "tol": float("nan")}, "tol must be > 0"),
    ],
)
def test_degenerate_hole_claims_are_refused(kwargs, match):
    with pytest.raises(ContractError, match=match):
        _part().hole_diameter(kwargs.pop("d"), **kwargs)


def test_hole_diameter_gates_on_the_bores_primitive():
    assert GEOMETRY_KINDS["hole_diameter"] == "bores"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"d": 0, "count": 4, "bcd": 40.0}, "d > 0"),
        ({"d": 5.0, "count": 1, "bcd": 40.0}, "count >= 2"),
        ({"d": 5.0, "count": True, "bcd": 40.0}, "count >= 2"),
        ({"d": 5.0, "count": 4, "bcd": 4.0}, "bcd > d"),
        ({"d": 5.0, "count": 4, "bcd": 40.0, "tol": 0.0}, "tol must be > 0"),
    ],
)
def test_degenerate_bolt_circle_claims_are_refused(kwargs, match):
    with pytest.raises(ContractError, match=match):
        _part().bolt_circle(kwargs.pop("d"), **kwargs)


def test_bolt_circle_records_the_callout():
    p = _part()
    p.bolt_circle(5.0, count=4, bcd=40.0, tol=0.2)
    spec = p.checks[0]
    assert spec.id == "bolt_circle_4x_d5"
    assert spec.hole == {"d": 5.0, "count": 4, "bcd": 40.0}
    assert spec.limit is not None
    assert spec.limit.min == pytest.approx(39.8) and spec.limit.max == pytest.approx(40.2)


def test_a_positional_band_wider_than_the_hole_is_refused():
    """PR #89 review, blocker 2: with no datum the claim is existential, and a
    wide band is satisfiable by circles no drawing describes — a cherry-picked
    centre passed 8-on-the-circle as 'exactly 4' at tol=21."""
    with pytest.raises(ContractError, match="must not exceed d"):
        _part().bolt_circle(5.0, count=4, bcd=40.0, tol=21.0)


def test_fillet_radius_must_bound_something():
    with pytest.raises(ContractError, match="claims nothing"):
        _part().fillet_radius()
    with pytest.raises(ContractError, match="min must be > 0"):
        _part().fillet_radius(min=0)
