"""The ISO metric coarse series and basic profile (#194).

This is a DATA module, so the tests are shaped differently from the rest of the
suite: there is no behaviour to mutate, only numbers to be wrong. Three kinds of
assertion earn their place here.

1. **Cross-checks against independently sourced figures.** Six basic dimensions
   are pinned against values three fleet-01 modules arrived at separately — one
   deriving them from ISO 965-1 grades, two transcribing them from published
   limit tables. Agreement to the last digit across three sourcings is the
   strongest evidence available for a table nobody here can open the standard
   for.
2. **Internal consistency the standard implies.** A pitch series must not
   decrease with diameter; every pitch must be one the standard actually uses;
   the three derived diameters must be ordered `d3 < D1 < d2 < d`. These catch
   transcription errors that no single-value check can — a swapped digit in one
   row breaks monotonicity even when the value looks plausible.
3. **The provenance contract** (SPEC-contract.md §10): a citation on every
   dimension, shed by arithmetic, and naming the standard that actually says the
   thing.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from support import needs_build123d

from partspec import Part, Status, run
from partspec.refs import iso_metric_thread as iso_thread
from partspec.status import ContractError

# ---------------------------------------------------------------------------
# the series
# ---------------------------------------------------------------------------


def test_the_coarse_pitch_never_decreases_as_the_diameter_grows():
    """A monotonicity a transcription error cannot satisfy by accident.

    Single-value checks cannot cover 35 rows, and a wrong digit usually still
    looks like a plausible pitch. It almost never preserves the ordering: an
    M14 typed as 1.5 instead of 2 sits below M12's 1.75 and fails here.
    """
    diameters = iso_thread.sizes()
    pitches = [iso_thread.coarse(d).pitch for d in diameters]
    assert pitches == sorted(pitches), (
        f"pitch decreases somewhere in {list(zip(diameters, pitches, strict=True))}"
    )
    assert diameters == tuple(sorted(diameters))


def test_every_pitch_is_one_the_standard_actually_uses():
    """The pitch series is a closed set, so a value outside it is a typo.

    Catches the transposition monotonicity misses — 1.52 for 1.25 keeps the
    ordering and is not a pitch that exists.
    """
    published = {
        0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0, 1.25, 1.5,
        1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
    }  # fmt: skip
    used = {float(iso_thread.coarse(d).pitch) for d in iso_thread.sizes()}
    assert used <= published, f"not ISO pitches: {sorted(used - published)}"


def test_the_three_sizes_the_fleet_verified():
    """M3, M5 and M8 are the only diameters with independent corroboration.

    All three arm-C modules carry M3x0.5 and M8x1.25; c2's `calibrate.py`
    implies M5x0.8 from a 6g major max of 4.976. Everything else in the table
    rests on a single sourcing, which the module docstring says.
    """
    assert iso_thread.coarse(3).pitch == 0.5
    assert iso_thread.coarse(5).pitch == 0.8
    assert iso_thread.coarse(8).pitch == 1.25


def test_the_two_diameters_people_misremember():
    """M14 is 2, not 1.5 (that is M10); M39 is 4, not 4.5 (that is M42).

    Both sit between neighbours that pull the wrong way, and both were flagged
    as the classic traps when the series was sourced. Pinned by name so a future
    edit has to disagree on purpose.
    """
    assert iso_thread.coarse(14).pitch == 2.0
    assert iso_thread.coarse(39).pitch == 4.0


def test_the_series_stops_where_the_coarse_series_stops():
    """Above M64 the standard tabulates fine pitches only.

    There is no coarse column to extrapolate into, so a lookup must refuse
    rather than continue the pattern — the failure mode is a plausible wrong
    answer, which is the one this project exists to prevent.
    """
    assert max(iso_thread.sizes()) == 64.0
    with pytest.raises(ContractError, match="no coarse pitch at this diameter"):
        iso_thread.coarse(72)


def test_the_choice_rank_partitions_the_series():
    first, second, third = (iso_thread.sizes(choice=c) for c in (1, 2, 3))
    assert set(first) | set(second) | set(third) == set(iso_thread.sizes())
    assert not (set(first) & set(second)) and not (set(second) & set(third))
    # The sizes a reader expects to be preferred.
    for d in (3, 4, 5, 6, 8, 10, 12, 16, 20, 24):
        assert d in first, f"M{d} should be first choice"
    assert 14.0 in second and 7.0 in third


# ---------------------------------------------------------------------------
# the basic profile
# ---------------------------------------------------------------------------


def test_the_basic_dimensions_match_the_published_table():
    """Six values, against figures three independent fleet sourcings agreed on.

    They are computed here rather than transcribed, so this is the check that
    the RELATIONS are right — ISO 724 tabulates these rounded to three decimals
    and the exact values must round to them.
    """
    published = {
        # designation: (d2, D1, d3) as ISO 724 prints them
        8: (7.188, 6.647, 6.466),
        3: (2.675, 2.459, 2.387),
    }
    for nominal, (d2, d1, d3) in published.items():
        t = iso_thread.coarse(nominal)
        assert round(t.pitch_diameter, 3) == d2, f"M{nominal} d2"
        assert round(t.minor_internal, 3) == d1, f"M{nominal} D1"
        assert round(t.minor_external, 3) == d3, f"M{nominal} d3"


def test_the_profile_constants_are_derived_not_typed():
    """`sqrt(3)/2` to the last bit a double holds.

    The prior art is the argument: one fleet module truncated the `5H/4`
    coefficient to `1.082531754` where the correct round is `...755`, and
    another carried a minor diameter 1 um off its own formula. A constant you
    can derive should never be typed in, so this asserts the relations against
    the arithmetic rather than against a decimal literal.
    """
    h = math.sqrt(3) / 2
    for d in iso_thread.sizes():
        t = iso_thread.coarse(d)
        p = float(t.pitch)
        # `rel=1e-15`, not bit-exact: the module and this test associate the
        # multiplications differently, so the last bit legitimately differs.
        # Every error worth catching is 1e-9 relative or larger — c3's
        # truncated `1.082531754` is 7e-10 out, and a wrong fraction is a
        # percent.
        assert t.height == pytest.approx(h * p, rel=1e-15)
        assert t.pitch_diameter == pytest.approx(d - 2 * (3 * h * p / 8), rel=1e-15)
        assert t.minor_internal == pytest.approx(d - 2 * (5 * h * p / 8), rel=1e-15)
        assert t.minor_external == pytest.approx(d - 2 * (17 * h * p / 24), rel=1e-15)

    # And the constants themselves carry every bit `sqrt(3)/2` has, which is
    # the specific thing the prior art lost.
    assert math.sqrt(3) / 2 == iso_thread._H_PER_PITCH
    assert iso_thread._D1_PER_PITCH != 1.082531754, "c3's truncation, 7e-10 out"


def test_the_three_derived_diameters_are_ordered_and_distinct():
    """`d3 < D1 < d2 < d`, and the two minors are NOT the same number.

    The profile truncates the external root by `17H/24` and the internal by
    `5H/8`; using one for the other is a `0.144·P` error — 0.18 mm at M8, which
    is a tapped hole that does not fit its bolt. The gap is asserted, not just
    the ordering, because `<` alone passes if they differ by a rounding error.
    """
    for d in iso_thread.sizes():
        t = iso_thread.coarse(d)
        p = float(t.pitch)
        assert t.minor_external < t.minor_internal < t.pitch_diameter < t.nominal
        assert t.minor_internal - t.minor_external == pytest.approx(0.1443 * p, rel=1e-3)


# ---------------------------------------------------------------------------
# provenance (SPEC-contract.md 10)
# ---------------------------------------------------------------------------


def test_every_dimension_cites_the_standard_that_says_it():
    """Two of the three fleet modules mis-attributed the basic dimensions.

    ISO 261 clause 1: *"Basic dimensions are given in ISO 724."* So the
    diameter/pitch pair cites 261, the profile height cites 68-1, and the three
    derived diameters cite 724. Citing the wrong document is the same defect as
    a wrong number: a reader who goes looking does not find it.
    """
    t = iso_thread.coarse(8)
    expected = {
        "nominal": ("ISO 261", "nominal_diameter"),
        "pitch": ("ISO 261", "coarse_pitch"),
        "height": ("ISO 68-1", "fundamental_triangle_height"),
        "pitch_diameter": ("ISO 724", "basic_pitch_diameter"),
        "minor_internal": ("ISO 724", "basic_minor_diameter_internal"),
        "minor_external": ("ISO 724", "basic_minor_diameter_external"),
    }
    for field, (standard, name) in expected.items():
        source = getattr(t, field).source
        assert source == {"standard": standard, "subject": "M8", "field": name}, field


def test_arithmetic_sheds_the_citation():
    """§10 rule 2. The derived diameters carry one because the standard performs
    that operation and prints the result; anything the AUTHOR does to them does
    not.
    """
    t = iso_thread.coarse(8)
    assert not hasattr(t.minor_internal + 0.1, "source")
    assert type(t.minor_internal + 0.1) is float


@needs_build123d
def test_a_thread_dimension_reaches_the_report_as_a_citation(tmp_path):
    """End to end: the point of the table is that a check records its authority.

    OCCT, because `hole_diameter` is an exact-tier check — the mesh backend
    refuses it, correctly, and a refusal carries no measurement to attribute.
    """
    from partspec import build123d

    model = tmp_path / "m.py"
    # Bored at the exact basic minor diameter the table derives, so a PASS is
    # evidence the number the contract asserted is the number the model has.
    model.write_text(
        "from build123d import Align, Box, Cylinder, Location\n\n\n"
        "def make_part():\n"
        "    plate = Box(20, 20, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
        "    bore = Location((10, 10, -1)) * Cylinder(\n"
        "        6.646835307 / 2, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)\n"
        "    )\n"
        "    return plate - bore\n"
    )
    p = Part("plate", build123d(model))
    iso_thread.tapped_hole(p, 8, tol=0.05)
    report = run(p, out_dir=tmp_path / "out")
    check = next(c for c in report.checks if c.id == "iso_metric_thread:M8:tapped")
    assert check.status is Status.PASS, check.detail
    assert check.to_json()["source"] == {
        "d": {"standard": "ISO 724", "subject": "M8", "field": "basic_minor_diameter_internal"}
    }


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_an_unknown_diameter_names_what_the_table_carries():
    """A table must not guess (SPEC-contract.md §10.1)."""
    with pytest.raises(ContractError) as exc:
        iso_thread.coarse(13)
    message = str(exc.value)
    assert "no coarse pitch at this diameter" in message
    assert "M12" in message and "M14" in message


def test_a_wrong_type_and_an_unknown_number_are_different_mistakes():
    """The distinction #240 spent three review rounds establishing on `iso15`.

    A list is not an unknown diameter, it is not a diameter — and the lookup is
    asked first, so anything hashing equal to a key resolves rather than being
    pre-screened out.
    """
    from decimal import Decimal
    from fractions import Fraction

    with pytest.raises(ContractError, match="not list"):
        iso_thread.coarse([8])  # type: ignore[arg-type]
    # No `type: ignore` here, and that is the point: `bool` IS a `float` to a
    # type checker (bool -> int -> float), so `coarse(True)` type-checks clean
    # and only the runtime guard stands between it and a lookup that would
    # succeed — `True == 1` and 1.0 is not in the table today, but `hash(True)`
    # equalling `hash(1)` is the shape of the trap.
    with pytest.raises(ContractError, match="not bool"):
        iso_thread.coarse(True)

    # All of these hash equal to a table key and must resolve.
    for equivalent in (8, 8.0, Decimal(8), Fraction(16, 2)):
        assert iso_thread.coarse(equivalent).designation == "M8"  # type: ignore[arg-type]


def test_the_unattributed_advisory_names_every_table_refs_carries():
    """The one place the tool routes an author to an attributed number.

    It named "iso15, nema17" as a hardcoded string, so adding a table left the
    advisory pointing at two of three — stale in the direction that matters,
    since its whole job is to route someone to a table they did not know
    existed, and nothing in the suite would have noticed. It asks the package
    now, and this is the test that keeps it asking.
    """
    from partspec import refs
    from partspec.cli import _refs_carried

    carried = _refs_carried()
    assert "iso_metric_thread" in carried
    for module in refs.__all__:
        assert module in carried, f"{module} is carried and the advisory omits it"

    # And the documents that repeat the same list by hand.
    root = Path(__file__).resolve().parents[1]
    for doc, needle in (
        ("README.md", "iso15, iso_metric_thread, nema17"),
        ("docs/SPEC-contract.md", "from partspec.refs import iso15, iso_metric_thread, nema17"),
    ):
        assert needle in (root / doc).read_text(), f"{doc} lists the tables by hand and is stale"


def test_the_designation_reads_as_it_is_written():
    assert iso_thread.coarse(8).designation == "M8"
    assert iso_thread.coarse(2.5).designation == "M2.5"
    assert iso_thread.coarse(1.6).designation == "M1.6"
