"""Per-component attribution (#84): which axis failed, and on what evidence.

Collected here because #158 left the subject split across two files — four
end-to-end tests in the regions file, whose fixture they had borrowed, and two
unit tests in `test_runner.py`. Neither location was wrong so much as partial:
a reader asking "what does the tool say about WHICH component failed?" had to
know both.

The four e2e ones run a real contract and read `components` out of the report;
the two unit ones call `_components_of` and `_failing_axes` on hand-built
measurements, which is where the epsilon and interval behaviour can be pinned
without an engine. `test_region_clauses_appear_as_components` stays with the
region checks — its subject is the region clause, not the attribution.
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
    assert check.detail == "z=10 outside max=5"


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
    assert _failing_axes(m, limit, components) == "a=5 outside min=6.0"


# --------------------------------------------------------------------------
# the scalar sibling (#210): a check with no axes to attribute still has
# two numbers, and said neither
# --------------------------------------------------------------------------


@needs_scad_tier
def test_a_failing_scalar_check_names_both_numbers(tmp_path: Path):
    """`FAIL solid_count` was the entire diagnostic.

    The vector case has named its numbers since `_failing_axes`; the scalar
    case named nothing, while `report.json` held `{"value": 2}` against
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


def test_a_boolean_measurement_does_not_render_as_a_number():
    """`bool` subclasses `int` in Python, so the obvious isinstance ordering
    renders `True` as `1` and a reader is told the part measured one of
    something. `scad_literal` carries a note about the same trap; this pins
    the other place it can bite.

    Reordering the two branches in `_quantity` leaves every other test in this
    suite green, which is why this one exists.
    """
    from partspec import Limit
    from partspec.runner import _failing_scalar

    m = Measurement(False, "bool")
    assert _failing_scalar(m, Limit(equals=True)) == "measured false, limit equals=True"


def test_a_conclusive_failure_on_an_approximate_measurement_keeps_its_interval():
    """An approximate measurement whose WHOLE interval sits outside the limit
    adjudicates to FAIL, not APPROXIMATE — so this path is reached with bounds
    in hand, and printing the point value alone would state a number the
    backend never claimed to know (SPEC-report 3.1).
    """
    from partspec import Limit, adjudicate
    from partspec.runner import _failing_scalar

    m = Measurement(1.5, "mm", exact=False, bounds=(1.4, 1.6))
    limit = Limit(min=2.0)
    assert adjudicate(m, limit) is Status.FAIL, "premise: conclusively outside"
    assert _failing_scalar(m, limit) == "measured 1.5 mm (in [1.4, 1.6]), limit min=2.0"


def test_the_rendered_numbers_survive_a_difference_in_the_seventh_figure():
    """`:g` stops at six significant figures, so a measurement and the bound
    it missed by a micron render identically and the line describes no failure
    at all. `bolt_circle` records the same reason for its own `:.9g`.
    """
    from partspec import Limit
    from partspec.runner import _failing_scalar

    value, bound = 2.0000001, 2.0
    assert f"{value:g}" == f"{bound:g}", (
        "premise: at :g these two numbers are the same string, which is the "
        "whole reason the format is pinned"
    )
    rendered = _failing_scalar(Measurement(value, "mm"), Limit(max=bound))
    assert rendered == "measured 2.0000001 mm, limit max=2.0"


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
    for form, limit in one_of_each.items():
        assert _render(limit), f"_render says nothing about a {form} limit"


def test_a_backend_that_declines_to_explain_falls_back_to_the_numbers():
    """`<kind>_detail` is typed `-> str | None`, and `watertight_detail`
    really does return None for a case it cannot characterise.

    Chained rather than `elif`-ed for that reason: as an `elif`, a hook
    returning None left `detail` None and restored #210's emptiness one layer
    up — an emptiness that only a hook's own declining could produce, so no
    check without a hook would ever have exposed it.
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
