"""What a failing check SAYS about itself: which axis, and with what numbers.

Started as per-component attribution (#84) — which axis failed, and on what
evidence — collected here because #158 left that subject split across two
files. #210 extended it to the scalar case, where there is no axis to name and
the tool said nothing at all, so the file's subject is now the whole of a
failure's own account of itself.

Deliberately no counts in that sentence. This docstring said "four end-to-end
tests … and two unit ones [which] call `_components_of` and `_failing_axes`"
and was wrong within one PR of being written — the same rot `GEOMETRY_KINDS`
records ("it read 'topology and hole_diameter are the entries' long after there
were eight"), found by the adversarial review of #232.

The e2e ones run a real contract and read the report. The rest need no engine:
most call the renderers on hand-built measurements — where epsilon, interval
and number-format behaviour can be pinned — while a few drive
`_run_geometry_check` with a stub backend, or hold a constant against the
register it is derived from. (The replacement for a sentence that counted its
own tests; this one names shapes instead, because the count was wrong within
one PR and the first rewrite still described only two of the three shapes.)
`test_region_clauses_appear_as_components` stays with the region checks — its
subject is the region clause, not the attribution.
"""

from __future__ import annotations

from pathlib import Path

from support import needs_build123d, needs_openscad, needs_scad_tier

from partspec import Measurement, Part, Status, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
BLOCK = FIXTURES / "block_with_hole.scad"


@needs_scad_tier
def test_a_failing_envelope_names_the_failing_axis(tmp_path: Path):
    """The block is 30x20x10. Only z breaks its bound, and the report must say
    so as data — an agent acting on 'envelope failed' has to bisect; one acting
    on 'z=10 outside max=5' edits once."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 5))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.FAIL
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.FAIL}
    # `z=10.0`, not `z=10`: the axis value goes through `_number` since #232's
    # round-2 review, which found this path still collapsing at `:g` — a vector
    # `1000.0002` against `max=1000.0` printed `x=1000 outside max=1000.0`, a
    # failure line reading as an equality. The limit here is an int and prints
    # as one, which is the distinction `_number` exists to keep.
    assert check.detail == "z=10.0 outside max=5"


@needs_scad_tier
def test_components_are_recorded_on_pass_too(tmp_path: Path):
    """The 7.2 principle applied to attribution: drift analysis needs the
    passing shape as much as the failing one."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.PASS
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}
    assert check.detail is None


@needs_openscad
def test_a_scalar_check_carries_no_components(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).volume(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "volume")
    assert check.components is None
    assert "components" not in check.to_json()


@needs_build123d
def test_an_unconstrained_topology_axis_is_absent_from_components(tmp_path: Path):
    """faces= alone claims nothing about edges or vertices, so those axes must
    not appear — a status on an unmade claim would be an answer to a question
    nobody asked."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text("from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n")
    p = Part("cube", build123d(model)).topology(faces=6)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.PASS
    assert check.components == {"faces": Status.PASS}


def test_components_respect_the_same_epsilon_the_status_does():
    """The headline invariant, tested at the boundary where it can break: the
    binary-STL float32 round-trip that `epsilon()` exists for. A recompute of
    components with a naive comparison would fail x here while the folded
    status passes — a report contradicting its own attribution."""
    from partspec import Limit, adjudicate
    from partspec.runner import _components_of

    m = Measurement((120.30000305, 80.69999695, 40.09999847), "mm", axes=("x", "y", "z"))
    limit = Limit(max=(120.3, 80.7, 40.1))
    assert adjudicate(m, limit) is Status.PASS
    assert _components_of(m, limit) == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}


def test_an_approximate_axis_is_never_claimed_outside_its_bound():
    """'outside' is a conclusive claim. An axis whose error band straddles the
    limit is APPROXIMATE — the tool does not know — and the detail must stay
    silent about it rather than rounding indeterminate into violated. No
    backend emits vector bounds today; this pins the path before one does."""
    from partspec import Limit
    from partspec.runner import _components_of, _failing_axes

    m = Measurement(
        (5.0, 2.01),
        "mm",
        exact=False,
        bounds=((4.9, 5.1), (1.96, 2.06)),
        axes=("a", "b"),
    )
    limit = Limit(min=(6.0, 2.0))
    components = _components_of(m, limit)
    assert components == {"a": Status.FAIL, "b": Status.APPROXIMATE}
    assert components is not None
    assert _failing_axes(m, limit, components) == "a=5.0 outside min=6.0"


# --------------------------------------------------------------------------
# the scalar sibling (#210): a check with no axes to attribute still has
# two numbers, and said neither
# --------------------------------------------------------------------------


@needs_scad_tier
def test_a_failing_scalar_check_names_both_numbers(tmp_path: Path):
    """`FAIL solid_count` was the entire diagnostic.

    The vector case has named its numbers since `_failing_axes`; the scalar
    case named nothing, while `report.json` held `{"value": 1}` against
    `{"equals": 3}`. For this check the value IS the finding — too few means
    bodies fused, too many means something fragmented — and the bare line
    cannot tell those apart (#210).

    The fixture block is one solid, so `solid_count(3)` fails at a known
    measured value rather than at whatever the geometry happens to be.
    """
    p = Part("block", openscad(BLOCK)).solid_count(3)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "solid_count")
    assert check.status is Status.FAIL
    assert check.components is None, "premise: a scalar check has no axes"
    assert check.detail == "measured 1, limit equals=3"


@needs_scad_tier
def test_a_failing_scalar_check_carries_its_unit(tmp_path: Path):
    """`count` and `bool` are dropped and everything else is kept.

    A dimensioned number without its dimension is the ambiguity this project
    spends its output budget on; a dimensionless one wearing the word "count"
    is noise the check id already carried.
    """
    p = Part("block", openscad(BLOCK)).volume(min=1_000_000.0)
    report = run(p, out_dir=tmp_path)
    detail = next(c for c in report.checks if c.id == "volume").detail
    assert detail is not None and detail.endswith("mm3, limit min=1000000.0"), detail


def test_a_bool_check_with_an_equals_limit_gets_no_numbers_because_it_has_none():
    """The one kind where the generic renderer is noise, and the proof.

    For a two-valued measurement an `equals` limit plus `FAIL` DETERMINES the
    value, in both directions: failing `equals=true` means false, and failing
    `equals=false` means true. So `measured false, limit equals=false` restates
    the check id and the status and adds no fact — which is what the OCCT tier
    printed for `watertight`, having no `watertight_detail` to win ahead of it
    (adversarial review of #232).

    The mesh tier's hook is unaffected and still says the useful thing, because
    it is consulted first.
    """
    from partspec import Limit, adjudicate
    from partspec.runner import _failing_scalar

    for measured, bound in ((False, True), (True, False)):
        m = Measurement(measured, "bool")
        limit = Limit(equals=bound)
        assert adjudicate(m, limit) is Status.FAIL, "premise: this is the failing direction"
        assert _failing_scalar(m, limit) is None, (
            f"measured {measured} against equals={bound} is a tautology at FAIL"
        )


def test_a_boolean_still_renders_as_a_word_wherever_it_is_shown():
    """`bool` subclasses `int` in Python, so the obvious isinstance ordering
    renders `True` as `1` and a reader is told the part measured one of
    something. `scad_literal` carries a note about the same trap.

    Both sides, since #232's review found `measured false, limit equals=True`
    — one boolean, one sentence, two spellings — before `_number` became the
    single formatter.
    """
    from partspec import Limit
    from partspec.runner import _number, _render

    assert _number(True) == "true" and _number(False) == "false"
    assert _render(Limit(equals=True)) == "equals=true"


def test_a_conclusive_failure_on_an_approximate_measurement_keeps_its_interval():
    """An approximate measurement whose WHOLE interval sits outside the limit
    adjudicates to FAIL, not APPROXIMATE — so a backend that emits one arrives
    here with bounds in hand, and printing the point value alone would state a
    number it never claimed to know (SPEC-report 3.1).

    No primitive on this path emits `exact=False` today: `_min_wall_measurement`
    is the only such site in either backend and `min_wall` returns from its own
    runner first. The code and this test are on the `choices` branch's footing —
    written for the first caller — and #232's review corrected a docstring that
    called the path "not hypothetical".

    The bounds differ past the sixth significant figure on purpose: at `:g`
    they render as one number, so this also pins that the interval goes through
    the same formatter as the value. It did not, and the mutation survived.
    """
    from partspec import Limit, adjudicate
    from partspec.runner import _failing_scalar, _number

    lo, hi = 1234.56789, 1234.56791
    assert f"{lo:g}" == f"{hi:g}", "premise: :g collapses this interval to a point"
    m = Measurement(1234.5679, "mm3", exact=False, bounds=(lo, hi))
    limit = Limit(min=99999.0)
    assert adjudicate(m, limit) is Status.FAIL, "premise: conclusively outside"
    assert _failing_scalar(m, limit) == (
        "measured 1234.5679 mm3 (in [1234.56789, 1234.56791]), limit min=99999.0"
    )

    # A second interval, at a magnitude where a bare `str()` and `_number`
    # DIFFER. The constants above pin ":.9g or better" and nothing more, so
    # `f"[{lo}, {hi}]"` — the mutation this test's own docstring claims to have
    # killed — still passed (round-2 review of #232).
    big = Measurement(2e10, "mm3", exact=False, bounds=(1.5e10, 2.5e10))
    assert str(1.5e10) != _number(1.5e10), "premise: the two formatters disagree here"
    assert _failing_scalar(big, Limit(min=9e10)) == (
        "measured 2e+10 mm3 (in [1.5e+10, 2.5e+10]), limit min=9e+10"
    )


def test_the_measurement_and_the_limit_are_rendered_in_one_notation():
    """The line exists so a reader can compare two numbers; they have to be
    comparable.

    `_quantity` used `:.9g` and `_render` a bare `str()`, so a large value
    printed `measured 1.23456789e+09 mm3, limit min=10000000000.0` — two
    notations for one comparison, reachable from the public API with
    `volume(min=1e10)` (adversarial review of #232). One `_number` now serves
    both.
    """
    from partspec import Limit
    from partspec.runner import _failing_scalar

    rendered = _failing_scalar(Measurement(1234567890.0, "mm3"), Limit(min=1e10))
    assert rendered == "measured 1.23456789e+09 mm3, limit min=1e+10"
    assert ("e+" in rendered.split(", limit ")[0]) == ("e+" in rendered.split(", limit ")[1]), (
        "both halves must be in the same notation or the reader cannot compare them"
    )


def test_a_float_limit_does_not_print_as_an_integer():
    """`:.9g` renders 2.0 as "2", and the vector messages have always shown the
    difference (`z=10 outside max=5.0`). `solid_count` limits are ints and
    `volume` limits are floats; a reader uses that."""
    from partspec import Limit
    from partspec.runner import _number, _render

    assert _number(2.0) == "2.0" and _number(2) == "2"
    assert _render(Limit(max=5.0)) == "max=5.0"
    assert _number(0.1 + 0.2) == "0.3", "and :.9g still trims float noise"


def test_a_non_finite_limit_does_not_render_as_a_decimal():
    """`Measurement` refuses a non-finite VALUE. `Limit` validates nothing, and
    `_reject_non_finite` never looks at `bounds`.

    So `solid_count(float("inf"))` reaches the renderer from the public API,
    and without a guard the trailing-`.0` restoration made it `inf.0` — a
    number that is not one, wearing a decimal point (round-2 review of #232).
    """
    from partspec import Limit
    from partspec.runner import _number, _render

    assert _number(float("inf")) == "inf"
    assert _number(float("-inf")) == "-inf"
    assert _number(float("nan")) == "nan"
    assert _render(Limit(equals=float("inf"))) == "equals=inf"


def test_a_choice_renders_the_way_the_same_value_renders_anywhere_else():
    """`choices` joined with `str()` instead of `_number` survived the first
    round: every member the test used rendered identically either way.

    A bool and a large float do not, which is the whole point of having one
    formatter (round-2 review of #232).
    """
    from partspec import Limit
    from partspec.runner import _render

    assert _render(Limit(choices=(True, 1e10))) == "one of {true, 1e+10}"


def test_a_failing_parameter_check_uses_the_same_formatter_as_everything_else():
    """The regression round 2 found: routing only `_render` through `_number`
    made THIS line the two-notation case the change was meant to remove.

    `p.param("hole_d", max=1e9)` printed
    `hole_d=10000000000.0 outside max=1e+09` — the measurement in one notation
    and the bound it missed in another, in the one sentence that exists to let
    a reader compare them.
    """
    from partspec import Limit
    from partspec.contract import CheckSpec
    from partspec.runner import _run_parameter_check

    spec = CheckSpec(
        id="param:hole_d",
        kind="param_range",
        phase="parameter",
        expr="hole_d",
        limit=Limit(max=1e9),
    )
    check = _run_parameter_check(spec, {"hole_d": 1e10})
    assert check.status is Status.FAIL
    assert check.detail == "hole_d=1e+10 outside max=1e+09"


def test_the_dimensionless_units_are_still_the_ones_this_drops():
    """`MEASURANDS` is the register of units, and the SPEC unit table is
    generated from it precisely so a new check brings its own row.

    `DIMENSIONLESS` is a second, hand-kept list over that register, so it rots
    the same way — and this is a TRIPWIRE, not a proof. It fires when the
    register changes at all, classified or not, and `DIMENSIONLESS <= units`
    can only catch a fictional unit, never an unclassified one. The first
    version of this docstring claimed the stronger thing ("a NEW dimensionless
    unit must be classified here"); a unit added and left unclassified passes
    it, measured (round-2 review of #232). The tripwire is still worth having —
    it puts the decision in front of whoever adds a unit — but it does not make
    it for them.
    """
    from partspec.contract import MEASURANDS
    from partspec.runner import DIMENSIONLESS

    units = {m.unit for m in MEASURANDS.values() if m.unit}
    assert units == {"mm", "mm2", "mm3", "deg", "count", "bool", "rel"}, (
        f"a unit was added or removed; decide whether it is dimensionless: {sorted(units)}"
    )
    assert units >= DIMENSIONLESS, "DIMENSIONLESS must name real units"


def test_the_rendered_numbers_survive_a_difference_g_would_collapse():
    """`:g` stops at six significant figures, so a measurement and the bound it
    missed render identically and the line describes no failure at all.
    `hole_diameter` records the same reason for its own `:.9g` — there the
    collapse turns a tight band into an empty interval.

    The pair is one that really FAILs. This test used `2.0000001` against
    `max=2.0` until #232's review pointed out that `epsilon(2.0)` is 1.2e-6, so
    that pair adjudicates PASS and `_failing_scalar` can never be reached with
    it — a format defended by an example the tool declares equal.
    """
    from partspec import Limit, adjudicate
    from partspec.runner import _failing_scalar

    value, bound = 1000.0002, 1000.0
    m, limit = Measurement(value, "mm"), Limit(max=bound)
    assert adjudicate(m, limit) is Status.FAIL, (
        "premise: this pair is a real failure, not one epsilon calls equal"
    )
    assert f"{value:g}" == f"{bound:g}" == "1000", (
        "premise: at :g the two numbers are the same string, which is the "
        "whole reason the format is pinned"
    )
    assert _failing_scalar(m, limit) == "measured 1000.0002 mm, limit max=1000.0"


def test_the_limit_renderer_covers_every_form_its_type_defines():
    """`Limit` is a closed set of four forms and `_render` handled three.

    `choices` is unreachable through the contract API today, which is exactly
    why this is worth pinning: the first check to use one would otherwise
    render the empty string, and `measured 'x', limit ` states a bound that is
    not there.
    """
    from dataclasses import fields

    from partspec import Limit
    from partspec.runner import _render

    # Every form named once here and once as a Limit below. The set equality
    # is what makes this test grow: adding a fifth form to `Limit` fails here
    # rather than quietly rendering to nothing at the first call site.
    one_of_each = {
        "min": Limit(min=1.0),
        "max": Limit(max=2.0),
        "equals": Limit(equals=3),
        "choices": Limit(choices=("a", "b")),
    }
    assert set(one_of_each) == {f.name for f in fields(Limit)}, (
        "a form was added to Limit; _render must learn it too"
    )
    # The exact string, not truthiness. `assert _render(limit)` passed with the
    # `one of ` prefix deleted, rendering `limit 'a', 'b'` — a bound with no
    # relation stated, which is precisely the "states a bound that is not
    # there" failure this test exists to prevent (adversarial review of #232).
    assert [_render(limit) for limit in one_of_each.values()] == [
        "min=1.0",
        "max=2.0",
        "equals=3",
        "one of {a, b}",
    ], "every form must render, and say what relation it is"

    # Joined with `and`, because the caller puts a comma between the
    # measurement and the limit and one separator cannot do both jobs.
    assert _render(Limit(min=1.0, max=2.0)) == "min=1.0 and max=2.0"


def test_a_backend_that_declines_to_explain_falls_back_to_the_numbers():
    """`<kind>_detail` is typed `-> str | None`, and no hook exercises that
    today.

    This docstring asserted that `watertight_detail` "really does return None
    for a case it cannot characterise". It returns None iff the mesh IS
    watertight, which is a pass — `test_watertight_detail_is_none_when_fine`
    next door pins exactly that. The correction was applied to the runner
    comment, the CHANGELOG and the commit message and missed here, which is the
    artifact a reader consults to learn what the chain is for (round-2 review
    of #232).

    Chained rather than `elif`-ed for the first hook that does decline: as an
    `elif` it left `detail` None and restored #210's emptiness one layer up.
    Same footing as `_render`'s `choices` branch — written for a caller that
    does not exist yet, and labelled as such.
    """
    from partspec import Limit
    from partspec.contract import CheckSpec
    from partspec.runner import _run_geometry_check

    class Silent:
        kind = "stub"

        def capabilities(self):
            return {"solid_count"}

        def solid_count(self, a):
            return Measurement(4, "count")

        def solid_count_detail(self, a):
            return None

    spec = CheckSpec(id="solid_count", kind="solid_count", phase="geometry", limit=Limit(equals=1))
    result = _run_geometry_check(spec, Silent(), object())
    assert result.status is Status.FAIL
    assert result.detail == "measured 4, limit equals=1"
