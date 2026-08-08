"""Referenced values and the first reference table (#92).

The claims under test: a Referenced value IS its number everywhere a number is
expected; attribution flows into the report when a table value reaches a bound
and never appears for a bare literal; arithmetic sheds it; and the F16 case —
the dogfood finding this table exists for — fails against the standard's number
with the citation in the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partspec import Part, Referenced, openscad
from partspec.provenance import source_map
from partspec.refs import iso15
from partspec.status import ContractError

_SRC = {"standard": "TEST", "subject": "x", "field": "f"}


# --------------------------------------------------------------------------
# the value type
# --------------------------------------------------------------------------


def test_a_referenced_value_is_its_number():
    v = Referenced(22.0, _SRC)
    assert v == 22.0
    assert v * 2 == 44.0
    assert json.dumps(v) == "22.0"
    assert repr(v) == "22.0", "reports and error messages must stay plain"
    assert v.source == _SRC


def test_arithmetic_sheds_attribution():
    """A derived number is the author's, not the standard's — carrying the
    citation across an operation the document never performed would launder
    authority."""
    v = Referenced(22.0, _SRC)
    assert type(v + 0.1) is float
    assert type(v / 2) is float
    assert type(-v) is float


def test_source_map_collects_scalars_and_tuple_components():
    v = Referenced(7.0, _SRC)
    assert source_map(min=v, max=2.0) == {"min": _SRC}
    assert source_map(max=(50.0, v, None)) == {"max.1": _SRC}
    assert source_map(min=1.0, max=2.0) is None, "absent, never empty"


# --------------------------------------------------------------------------
# the table
# --------------------------------------------------------------------------


def test_the_608_carries_iso15s_numbers():
    b = iso15.bearing(608)
    assert (float(b.bore), float(b.od), float(b.width)) == (8.0, 22.0, 7.0)
    assert b.od.source == {"standard": "ISO 15", "subject": "608", "field": "outside_diameter"}


@pytest.mark.parametrize(
    ("designation", "dims"),
    [(625, (5.0, 16.0, 5.0)), (6000, (10.0, 26.0, 8.0)), (6204, (20.0, 47.0, 14.0))],
)
def test_table_spot_checks(designation, dims):
    b = iso15.bearing(designation)
    assert (float(b.bore), float(b.od), float(b.width)) == dims


def test_an_unknown_designation_is_refused_naming_what_the_table_carries():
    with pytest.raises(ContractError, match="608"):
        iso15.bearing(999)


def test_refs_import_pulls_no_engine():
    """In a fresh interpreter — this process has already imported engines for
    other tests, so the assertion is only meaningful from cold."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import partspec.refs; "
            "banned = {'trimesh', 'build123d', 'OCP', 'manifold3d'} & set(sys.modules); "
            "assert not banned, banned",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# capture into checks and the report
# --------------------------------------------------------------------------


def _part() -> Part:
    return Part("p", openscad("a.scad"))


def test_a_referenced_bound_is_recorded_and_a_literal_is_not():
    p = _part()
    p.hole_diameter(iso15.bearing(608).od, tol=0.05)
    p.volume(min=1000.0)
    referenced, literal = p.checks
    assert referenced.source == {
        "d": {"standard": "ISO 15", "subject": "608", "field": "outside_diameter"}
    }
    assert literal.source is None


def test_a_referenced_tuple_component_is_recorded_with_its_position():
    p = _part()
    p.envelope(max=(50.0, 50.0, iso15.bearing(608).width))
    assert p.checks[0].source == {
        "max.2": {"standard": "ISO 15", "subject": "608", "field": "width"}
    }


def test_source_serialises_between_hole_and_detail():
    from partspec.report import CheckResult, Report
    from partspec.status import Limit, Status

    r = Report(part_id="p", contract="c", tool_version="t")
    r.checks = [
        CheckResult(
            id="hole_d22",
            kind="hole_diameter",
            phase="geometry",
            status=Status.PASS,
            limit=Limit(min=21.95, max=22.05),
            hole={"d": 22.0, "count": 1},
            source={"d": _SRC},
        )
    ]
    check = r.to_json()["checks"][0]
    assert check["source"] == {"d": _SRC}
    assert list(check) == [
        "id",
        "kind",
        "phase",
        "status",
        "measurement",
        "limit",
        "hole",
        "source",
        "detail",
    ]


# --------------------------------------------------------------------------
# end to end — F16, the finding this table exists for
# --------------------------------------------------------------------------

needs_build123d = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)

_SEAT_MODEL = (
    "from build123d import Box, Cylinder, Location, Align\n\n\n"
    "def make_part():\n"
    "    housing = Box(40, 40, 10, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    return housing - (Location((20, 20, -1)) * Cylinder(\n"
    "        {r}, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)))\n"
)


@needs_build123d
def test_f16_a_seat_modelled_off_standard_fails_with_the_citation(tmp_path: Path):
    """The dogfood's bearing(608) measured 22.5 mm where ISO 15 says 22.0, and
    catching it took a human who knew the standard. Now the table catches it,
    and the failing check names its authority."""
    from partspec import build123d
    from partspec.runner import run

    model = tmp_path / "housing.py"
    model.write_text(_SEAT_MODEL.format(r=11.25))  # the bad seat: Ø22.5
    p = Part("housing", build123d(model))
    p.hole_diameter(iso15.bearing(608).od, tol=0.05, id="seat")
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "seat")
    assert check.status.value == "fail"
    assert check.detail is not None and "Ø22.5" in check.detail
    assert check.source is not None and check.source["d"]["standard"] == "ISO 15"

    model.write_text(_SEAT_MODEL.format(r=11.0))  # the conforming seat: Ø22.0
    q = Part("housing", build123d(model))
    q.hole_diameter(iso15.bearing(608).od, tol=0.05, id="seat")
    good = run(q, out_dir=tmp_path / "b")
    check = next(c for c in good.checks if c.id == "seat")
    assert check.status.value == "pass"
    assert check.source is not None, "attribution is recorded on pass too"


def test_a_skipped_check_still_carries_its_source(tmp_path: Path):
    pytest.importorskip("trimesh", reason="mesh extra not installed")
    from partspec.runner import run

    scad = tmp_path / "p.scad"
    scad.write_text("cube([10, 10, 10]);\n")
    p = Part("p", openscad(scad, w=-1.0))
    p.requires("w > 0")
    p.envelope(max=(50.0, 50.0, iso15.bearing(608).width))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.kind == "envelope")
    assert check.status.value == "skipped"
    assert check.source is not None, "a refusal still states whose number went unanswered"
