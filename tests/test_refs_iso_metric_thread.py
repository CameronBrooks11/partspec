"""The ISO metric coarse series and the ISO 724 dimensions (#194).

Mostly a DATA module, so most of these tests are shaped differently from the
rest of the suite: there is no behaviour to mutate, only numbers to be wrong.
Four kinds of assertion earn their place.

1. **The standard's own tables, transcribed as fixtures.** `_ISO_724_TABLE_1`
   is ISO 724:2023 Table 1's coarse rows, and every one of the 40 rows and 120
   derived values is checked against it; the choice ranks are checked against
   ISO 261:1998 Table 2 the same way. This is the primary assertion of the
   file. An earlier draft had no such fixture — it pinned two rows out of
   thirty-five and leaned on the consistency checks below — and three rows were
   wrong.
2. **Consistency the standard implies**, which is now a supplement rather than
   the defence: the pitch must not decrease with diameter, every pitch must be
   one ISO 261 uses, and the derived diameters must be ordered
   `d3 < D1 < d2 < d`. These are worth keeping because they fail on a whole
   class of edit at once, but they are demonstrably not sufficient — four of
   four plausible wrong pitches walked straight through the monotonicity check.
3. **The boundary, from both sides.** A diameter ISO 261 gives no coarse pitch
   must be refused, and a diameter it does give one must not be. An omission is
   as much a defect as a wrong digit, and dropping a row used to be invisible.
4. **The behaviour that is here**: the lookup guard, the provenance contract
   (SPEC-contract.md §10), the `tapped_hole` fragment, and the CLI advisory
   that routes an author to this table in the first place.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from support import FIXTURES, needs_build123d

from partspec import Part, Status, run
from partspec.refs import iso_metric_thread as iso_thread
from partspec.status import ContractError

# ---------------------------------------------------------------------------
# the series
# ---------------------------------------------------------------------------


def test_the_coarse_pitch_never_decreases_as_the_diameter_grows():
    """A monotonicity a transcription error cannot satisfy by accident.

    Single-value checks cannot cover 40 rows, and a wrong digit usually still
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
    # ISO 261 Table 2's pitch columns, ALL of them. The first draft's set
    # started at 0.35 and omitted 0.2, 0.25 and 0.3 — it was the module's own
    # pitch set rather than the standard's, so the test that was meant to catch
    # a missing row would itself have failed when the missing rows were added
    # (round 1 of #194's review).
    published = {
        0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.75, 0.8, 1.0, 1.25,
        1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 8.0,
    }  # fmt: skip
    used = {float(iso_thread.coarse(d).pitch) for d in iso_thread.sizes()}
    assert used <= published, f"not ISO pitches: {sorted(used - published)}"


def test_the_three_sizes_the_fleet_verified():
    """M3, M5 and M8, the three the prior art corroborates independently.

    Subsumed by `test_every_row_matches_iso_724_table_1` now that the primary
    table is a fixture, and kept only as the record of what was checkable
    before it was: all three arm-C modules carry M3x0.5 and M8x1.25, and c2's
    `calibrate.py` implies M5x0.8 from a 6g major max of 4.976.
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
    """M68x6 is the last coarse row; M70 is the first diameter with none.

    The first draft stopped at M64 and asserted that as the end of the series,
    so `coarse(68)` was a false refusal and three artefacts stated the wrong
    boundary. ISO 261 Table 2 puts 68 in Col. 2 with a coarse pitch of 6 and
    gives 72 fine pitches only (round 1 of #194's review).
    """
    assert max(iso_thread.sizes()) == 68.0
    assert iso_thread.coarse(68).pitch == 6.0
    assert min(iso_thread.sizes()) == 1.0
    for beyond in (72, 76, 80):
        with pytest.raises(ContractError, match="no coarse pitch at this diameter"):
            iso_thread.coarse(beyond)


def test_the_choice_rank_partitions_the_series():
    first, second, third = (iso_thread.sizes(choice=c) for c in (1, 2, 3))
    assert set(first) | set(second) | set(third) == set(iso_thread.sizes())
    assert not (set(first) & set(second)) and not (set(second) & set(third))
    # The sizes a reader expects to be preferred. Every rank is pinned
    # individually by `test_the_choice_rank_of_every_row_matches_iso_261_table_2`;
    # this asserts the partition and a few landmarks.
    for d in (3, 4, 5, 6, 8, 10, 12, 16, 20, 24):
        assert d in first, f"M{d} should be first choice"
    assert 14.0 in second and 9.0 in third


# ---------------------------------------------------------------------------
# the ISO 724 dimensions
# ---------------------------------------------------------------------------


# ISO 724:2023 Table 1, coarse rows, as the standard prints them: (d, P) ->
# (d2, D1, d3). Transcribed from the free iTeh preview, which carries the
# complete table. This is the fixture the first draft of this file did not
# have — it pinned two of thirty-five rows and called the rest covered by a
# monotonicity check, which four plausible wrong pitches walked straight
# through (round 1 of #194's review).
_ISO_724_TABLE_1 = {
    (1, 0.25): (0.838, 0.729, 0.693),
    (1.1, 0.25): (0.938, 0.829, 0.793),
    (1.2, 0.25): (1.038, 0.929, 0.893),
    (1.4, 0.3): (1.205, 1.075, 1.032),
    (1.6, 0.35): (1.373, 1.221, 1.171),
    (1.8, 0.35): (1.573, 1.421, 1.371),
    (2, 0.4): (1.74, 1.567, 1.509),
    (2.2, 0.45): (1.908, 1.713, 1.648),
    (2.5, 0.45): (2.208, 2.013, 1.948),
    (3, 0.5): (2.675, 2.459, 2.387),
    (3.5, 0.6): (3.11, 2.85, 2.764),
    (4, 0.7): (3.545, 3.242, 3.141),
    (4.5, 0.75): (4.013, 3.688, 3.58),
    (5, 0.8): (4.48, 4.134, 4.019),
    (6, 1.0): (5.35, 4.917, 4.773),
    (7, 1.0): (6.35, 5.917, 5.773),
    (8, 1.25): (7.188, 6.647, 6.466),
    (9, 1.25): (8.188, 7.647, 7.466),
    (10, 1.5): (9.026, 8.376, 8.16),
    (11, 1.5): (10.026, 9.376, 9.16),
    (12, 1.75): (10.863, 10.106, 9.853),
    (14, 2.0): (12.701, 11.835, 11.546),
    (16, 2.0): (14.701, 13.835, 13.546),
    (18, 2.5): (16.376, 15.294, 14.933),
    (20, 2.5): (18.376, 17.294, 16.933),
    (22, 2.5): (20.376, 19.294, 18.933),
    (24, 3.0): (22.051, 20.752, 20.319),
    (27, 3.0): (25.051, 23.752, 23.319),
    (30, 3.5): (27.727, 26.211, 25.706),
    (33, 3.5): (30.727, 29.211, 28.706),
    (36, 4.0): (33.402, 31.67, 31.093),
    (39, 4.0): (36.402, 34.67, 34.093),
    (42, 4.5): (39.077, 37.129, 36.479),
    (45, 4.5): (42.077, 40.129, 39.479),
    (48, 5.0): (44.752, 42.587, 41.866),
    (52, 5.0): (48.752, 46.587, 45.866),
    (56, 5.5): (52.428, 50.046, 49.252),
    (60, 5.5): (56.428, 54.046, 53.252),
    (64, 6.0): (60.103, 57.505, 56.639),
    (68, 6.0): (64.103, 61.505, 60.639),
}


def test_every_row_matches_iso_724_table_1():
    """All 40 rows and all 120 derived diameters, against the printed table.

    The module computes these from the clause 5 formulae, so this is the check
    that both the pitch series and the relations are right — a wrong pitch
    moves all three derived values and cannot hide, and a wrong coefficient
    moves one column across every row.
    """
    assert set(iso_thread.sizes()) == {float(d) for d, _ in _ISO_724_TABLE_1}, (
        "the module's diameters and ISO 724's coarse rows must be the same set"
    )
    for (d, pitch), (d2, d1, d3) in _ISO_724_TABLE_1.items():
        t = iso_thread.coarse(d)
        assert t.pitch == pitch, f"M{d} pitch"
        assert round(t.pitch_diameter, 3) == d2, f"M{d} d2"
        assert round(t.minor_internal, 3) == d1, f"M{d} D1"
        assert round(t.minor_external, 3) == d3, f"M{d} d3"


def test_the_choice_rank_of_every_row_matches_iso_261_table_2():
    """ISO 261:1998 Table 2, columns 1/2/3, transcribed.

    22 of 35 ranks had no test at all in the first draft, and one of them —
    M7, which Table 2 puts in Col. 2 — was wrong, with the error pinned by
    name in a test (round 1 of #194's review).
    """
    ranks = {
        1: 1, 1.1: 2, 1.2: 1, 1.4: 2, 1.6: 1, 1.8: 2, 2: 1, 2.2: 2, 2.5: 1,
        3: 1, 3.5: 2, 4: 1, 4.5: 2, 5: 1, 6: 1, 7: 2, 8: 1, 9: 3, 10: 1,
        11: 3, 12: 1, 14: 2, 16: 1, 18: 2, 20: 1, 22: 2, 24: 1, 27: 2,
        30: 1, 33: 2, 36: 1, 39: 2, 42: 1, 45: 2, 48: 1, 52: 2, 56: 1,
        60: 2, 64: 1, 68: 2,
    }  # fmt: skip
    assert set(ranks) == {int(d) if d == int(d) else d for d in iso_thread.sizes()}
    for d, rank in ranks.items():
        assert iso_thread.coarse(d).choice == rank, f"M{d}"


def test_the_diameters_iso_261_lists_without_a_coarse_pitch_are_refused():
    """An omission is as much a defect as a wrong digit, so the boundary is
    tested from both sides.

    These are all in ISO 261 Table 2 with FINE pitches only, so refusing them
    is correct — but the first draft justified their absence with a rule
    ("third-choice diameters above M12 are omitted rather than guessed") that
    described neither M5.5 nor the four sizes below M1.6 it had also dropped,
    two of which are first choice.
    """
    for d in (5.5, 15, 17, 25, 26, 28, 32, 35, 38, 40, 50, 55, 58, 62, 65, 70, 72):
        with pytest.raises(ContractError, match="no coarse pitch at this diameter"):
            iso_thread.coarse(d)


def test_the_profile_constants_are_derived_not_typed():
    """The relations, to the last bit a double holds.

    The argument is the standards' own: ISO 68-1:2023 clause 5 says its
    dimensions "have been calculated by the following formulae, and rounded",
    and prints `H1 = 0,541 265 877 P`. Doubling a printed figure inherits its
    rounding — `1,082 531 754` against a correctly rounded `...755` — so this
    asserts the relations against the arithmetic rather than against any
    decimal literal, the standard's included.

    An earlier draft argued from the prior art instead and called those figures
    a truncation and a 1 um error. Both were falsified: the doubling is
    faithful to what ISO 68-1 prints, and the 1 um is one fleet module's own
    disclosed tolerance band. The module docstring retracted them and this one
    did not, which is the fix-here-leave-there fossil these reviews keep
    finding (round 2 of #194's review).
    """
    h = math.sqrt(3) / 2
    for d in iso_thread.sizes():
        t = iso_thread.coarse(d)
        p = float(t.pitch)
        # `rel=1e-15`, not bit-exact: the module and this test associate the
        # multiplications differently, so the last bit legitimately differs.
        # Every error worth catching is 1e-9 relative or larger — doubling ISO
        # 68-1's printed 9-decimal figure lands 7e-10 out, and a wrong fraction
        # is a percent.
        assert t.height == pytest.approx(h * p, rel=1e-15)
        assert t.pitch_diameter == pytest.approx(d - 2 * (3 * h * p / 8), rel=1e-15)
        assert t.minor_internal == pytest.approx(d - 2 * (5 * h * p / 8), rel=1e-15)
        assert t.minor_external == pytest.approx(d - 2 * (17 * h * p / 24), rel=1e-15)

    # And the constants themselves carry every bit `sqrt(3)/2` has, which is
    # the specific thing the prior art lost.
    assert math.sqrt(3) / 2 == iso_thread._H_PER_PITCH
    assert iso_thread._D1_PER_PITCH != 1.082531754, (
        "ISO 68-1's printed H1 doubled: faithful to the standard, 7e-10 out"
    )
    assert iso_thread._D2_PER_PITCH != 0.649519052, "the same, for 3H/8"


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
        "nominal": ("ISO 261:1998", "nominal_diameter"),
        "pitch": ("ISO 261:1998", "coarse_pitch"),
        "height": ("ISO 68-1:2023", "fundamental_triangle_height"),
        "pitch_diameter": ("ISO 724:2023", "pitch_diameter"),
        "minor_internal": ("ISO 724:2023", "minor_diameter_internal"),
        "minor_external": ("ISO 724:2023", "minor_diameter_external"),
    }
    for field, (standard, name) in expected.items():
        source = dict(getattr(t, field).source)
        note = source.pop("note", None)
        assert source == {"standard": standard, "subject": "M8", "field": name}, field
        # The three ISO 724 values are the exact formula, not the printed
        # digits, so the citation has to say so (SPEC-contract.md 11 rule 3).
        assert (note is not None) == (standard == "ISO 724:2023"), field

    # DATED, because the edition is load-bearing: `d3` exists only from ISO
    # 724:2023, and ISO 261:1998 normatively references ISO 724:1993, which has
    # no d3 at all. A bare "ISO 724" sends a reader following this module's own
    # citation chain to an edition without the number.
    assert all(":" in getattr(t, f).source["standard"] for f in expected)


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
    source = check.to_json()["source"]["d"]
    assert source["standard"] == "ISO 724:2023"
    assert source["subject"] == "M8"
    assert source["field"] == "minor_diameter_internal"
    assert "rounds to 3 decimals" in source["note"]


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
    # `complex(8)` hashes and compares EQUAL to 8, so it passes the membership
    # test and is caught only by the conversion inside the guard. Moving that
    # conversion back outside restores a raw `TypeError` and passed the whole
    # file (round 2 of #194's review).
    with pytest.raises(ContractError, match="not complex"):
        iso_thread.coarse(complex(8))  # type: ignore[arg-type]
    # And a `Number` that is not a `Real`: `Decimal` resolves when it is in the
    # table, so an unknown one is an unknown DIAMETER, not a wrong type. The
    # wording branch narrowing to `numbers.Real` is #240's round-3 defect.
    with pytest.raises(ContractError, match="no coarse pitch at this diameter"):
        iso_thread.coarse(Decimal("1.6"))  # type: ignore[arg-type]
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


def test_the_unattributed_advisory_names_every_table_refs_carries(tmp_path, capsys, monkeypatch):
    """The one place the tool routes an author to an attributed number.

    It named "iso15, nema17" as a hardcoded string, so adding a table left the
    advisory pointing at two of three — stale in the direction that matters,
    since its whole job is to route someone to a table they did not know
    existed. It asks the package now.

    Through the CLI, not through `_refs_carried()` in isolation: the first
    draft of this test exercised the helper and never the message, so reverting
    the f-string to the hardcoded list passed all sixteen tests in this file
    (round 1 of #194's review). The advisory is the artifact; test the artifact.
    """
    from partspec import refs
    from partspec.cli import main

    (tmp_path / "m.scad").write_text("cube([20, 20, 10], center = true);\n")
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, openscad\n\n\n"
        "def main():\n"
        '    return Part("blk", openscad("m.scad")).volume(min=1.0)\n'
    )
    monkeypatch.chdir(tmp_path)
    main(["check", "spec.py:main", "--out", "out"])

    printed = capsys.readouterr().err
    assert "is unattributed" in printed, "premise: the advisory fired"
    carried = printed.split("carries (")[1].split(")")[0]
    assert carried == ", ".join(sorted(refs.__all__)), (
        f"the advisory says {carried!r}; refs carries {sorted(refs.__all__)}"
    )
    assert "iso_metric_thread" in carried


def test_the_documents_that_list_the_tables_by_hand_are_current():
    """Four files repeat the list in prose, and nothing pinned two of them.

    Adding a table means editing five places; the two the first draft left
    unpinned would have gone stale silently — the same failure this slice set
    out to close, one layer out.
    """
    from partspec import refs

    root = Path(__file__).resolve().parents[1]
    inline = ", ".join(sorted(refs.__all__))
    # Every needle DERIVED from `refs.__all__`, or the pin is inert for the
    # next table: simulating a fourth entry, the two hardcoded needles below
    # still passed while the two derived ones failed (round 2 of #194's
    # review), which is the exact failure this test claims to close.
    backticked = ", ".join(f"`{m}`" for m in sorted(refs.__all__))
    for doc, needle in (
        ("README.md", f"carries ({inline})"),
        ("docs/SPEC-contract.md", f"from partspec.refs import {inline}"),
        ("docs/AGENT-CONTRACT.md", backticked),
    ):
        collapsed = " ".join((root / doc).read_text().split())
        assert needle in collapsed, f"{doc} lists the tables by hand and is stale"

    # SKILL.md names them as calls rather than as a list, so the pin is that
    # each one is named at all — still derived, still fails on a new table.
    skill = (root / "skills/contract-authoring/SKILL.md").read_text()
    for module in refs.__all__:
        assert module in skill, f"SKILL.md never names {module}"


def test_sizes_refuses_a_rank_iso_261_does_not_have():
    """A table must not guess (§10.1), and an empty tuple is a guess.

    `sizes(choice=4)` returning `()` reads as "ISO 261 ranks no diameters
    fourth", which is a statement and a wrong one. `sizes(choice=True)` was
    worse: `True == 1`, so it returned the whole first-choice list.
    """
    for bad in (0, 4, -1, True, False, "1", 2.5, [1], complex(1)):
        with pytest.raises(ContractError, match="pass 1, 2 or 3"):
            iso_thread.sizes(choice=bad)  # type: ignore[arg-type]
    # `1.0` IS accepted, the same way `coarse(8.0)` is: the test is on the
    # value, not the type, and a float rank equal to an int rank is that rank.
    assert iso_thread.sizes(choice=1.0) == iso_thread.sizes(choice=1)  # type: ignore[arg-type]
    assert len(iso_thread.sizes(choice=1)) == 21
    assert len(iso_thread.sizes(choice=2)) == 17
    assert len(iso_thread.sizes(choice=3)) == 2


def test_the_tapped_hole_fragment_honours_every_parameter():
    """Fast, engine-free, and covering what the OCCT test cannot reach.

    The fragment's only test was `needs_build123d`-gated, so on a machine
    without the OCCT extra it had zero coverage — and mutations ignoring
    `count`, `tol` and `instance` all survived the suite (round 1 of #194's
    review). `iso15.seat` and `nema17.mount` both have declaration-level tests
    of exactly this shape; this one had none.
    """
    from partspec import Part, openscad

    def declared(**kwargs):
        p = Part("plate", openscad(FIXTURES / "parametric_plate.scad"))
        iso_thread.tapped_hole(p, 8, **kwargs)
        return p.checks[-1]

    def hole(**kwargs):
        got = declared(**kwargs).hole
        assert got is not None
        return got

    def limit(**kwargs):
        got = declared(**kwargs).limit
        assert got is not None
        return got

    assert declared().id == "iso_metric_thread:M8:tapped"
    assert hole()["d"] == pytest.approx(iso_thread.coarse(8).minor_internal)
    assert hole()["count"] == 1
    assert hole(count=3)["count"] == 3
    assert declared(instance="left").id == "iso_metric_thread:M8:left:tapped"

    # `tol` is the author's fit allowance, and it reaches the bound as the
    # half-width of the limit rather than as a field of its own.
    nominal = float(iso_thread.coarse(8).minor_internal)
    wide = limit(tol=0.2)
    assert wide.min == pytest.approx(nominal - 0.2)
    assert wide.max == pytest.approx(nominal + 0.2)
    assert limit().min == pytest.approx(nominal - 0.05)

    # Two instances coexist; two without collide loudly (§11).
    p = Part("plate", openscad(FIXTURES / "parametric_plate.scad"))
    iso_thread.tapped_hole(p, 8, instance="left", count=2)
    iso_thread.tapped_hole(p, 8, instance="right", count=2)
    assert [c.id for c in p.checks] == [
        "iso_metric_thread:M8:left:tapped",
        "iso_metric_thread:M8:right:tapped",
    ]
    with pytest.raises(ContractError, match="duplicate check id"):
        iso_thread.tapped_hole(p, 8, instance="left")


def test_the_designation_reads_as_it_is_written():
    assert iso_thread.coarse(8).designation == "M8"
    assert iso_thread.coarse(2.5).designation == "M2.5"
    assert iso_thread.coarse(1.6).designation == "M1.6"
