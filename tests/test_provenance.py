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
from support import needs_mesh, needs_openscad

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


def test_referenced_survives_pickle_and_deepcopy():
    """Every copy protocol re-calls __new__; without __getnewargs__ a cached
    contract or a multiprocessing hand-off crashed with a message naming
    nothing (PR #95 review)."""
    import copy
    import pickle

    v = Referenced(22.0, _SRC)
    for clone in (pickle.loads(pickle.dumps(v)), copy.copy(v), copy.deepcopy(v)):
        assert clone == 22.0
        assert clone.source == _SRC
    b = copy.deepcopy(iso15.bearing(608))
    assert b.od.source["standard"] == "ISO 15"


# --------------------------------------------------------------------------
# fragments (#93)
# --------------------------------------------------------------------------


def test_mount_declares_the_pattern_with_the_standards_authority():
    """The split that matters: the pattern is the standard's and carries the
    citation; the clearance diameters are the designer's and stay theirs — a
    fragment must never launder the caller's numbers into a standard's."""
    from partspec.refs import nema17

    p = _part()
    nema17.mount(p)
    pilot, circle = p.checks
    assert pilot.id == "nema17:pilot"
    assert pilot.source is None, "the pilot clearance is the designer's number"
    assert circle.id == "nema17:bolt_circle"
    assert circle.source is not None
    assert circle.source["bcd"]["standard"] == "NEMA ICS 16"
    assert "1.725 in" in circle.source["bcd"]["note"]


def test_the_table_states_what_the_standard_states():
    """NEMA ICS 16 speaks in inches and gives the pitch circle DIRECTLY
    (AJ = 1.725 in); the 31 mm square is the catalogue's rounding. The first
    cut had the derivation backwards — 25.6 um off the standard's own number
    with a note claiming the opposite (PR #96 review, against the document's
    text). Values must be exact conversions of the stated figures."""
    import math

    from partspec.refs import nema17

    assert float(nema17.BOLT_CIRCLE_DIAMETER) == pytest.approx(1.725 * 25.4, abs=1e-12)
    assert float(nema17.HOLE_SQUARE) == pytest.approx(1.725 * 25.4 / math.sqrt(2), abs=1e-12)
    assert float(nema17.PILOT_BOSS) == pytest.approx(0.8661 * 25.4, abs=1e-12)
    assert float(nema17.FACEPLATE) == pytest.approx(1.7 * 25.4, abs=1e-12)
    assert "reference" in nema17.FACEPLATE.source["note"]
    assert "1.725 in" in nema17.BOLT_CIRCLE_DIAMETER.source["note"]
    assert "derived" in nema17.HOLE_SQUARE.source["note"]


def test_two_fragment_calls_collide_loudly():
    from partspec.refs import nema17

    p = _part()
    nema17.mount(p)
    with pytest.raises(ContractError, match="duplicate check id"):
        nema17.mount(p)


def test_the_seat_fragment_generalises_the_shape():
    p = _part()
    iso15.seat(p, 608)
    check = p.checks[0]
    assert check.id == "iso15:608:seat"
    assert check.source is not None and check.source["d"]["standard"] == "ISO 15"
    assert check.hole == {"d": 22.0, "count": 1}


_BRACKET_MODEL = (
    "import math\n"
    "from build123d import Box, Cylinder, Location, Align\n\n"
    "A = (Align.CENTER, Align.CENTER, Align.MIN)\n\n\n"
    "def make_part(offset=0.0):\n"
    "    plate = Box(60, 60, 6, align=(Align.MIN, Align.MIN, Align.MIN))\n"
    "    part = plate - (Location((30, 30, -1)) * Cylinder(11.15, 8, align=A))\n"
    "    for sx in (-1, 1):\n"
    "        for sy in (-1, 1):\n"
    "            x = 30 + sx * 15.5 + (offset if (sx, sy) == (1, 1) else 0)\n"
    "            part = part - (Location((x, 30 + sy * 15.5, -1)) * Cylinder(1.7, 8, align=A))\n"
    "    return part\n"
)

needs_build123d_frag = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("build123d") is None,
    reason="occt extra not installed",
)


@needs_build123d_frag
def test_a_conforming_bracket_passes_the_mount_fragment(tmp_path: Path):
    from partspec import build123d
    from partspec.refs import nema17
    from partspec.runner import run

    model = tmp_path / "bracket.py"
    model.write_text(_BRACKET_MODEL)
    p = Part("bracket", build123d(model))
    nema17.mount(p)
    report = run(p, out_dir=tmp_path)
    assert report.verdict.value == "pass", [c.to_json() for c in report.checks]
    circle = next(c for c in report.checks if c.id == "nema17:bolt_circle")
    assert circle.measurement is not None
    # The bracket is modelled on the catalogue's 31 mm square; the claim is the
    # standard's 43.815 pitch circle; the 25.6 um difference sits inside the
    # default positional tol, as it must for both conventions to coexist.
    assert circle.measurement.value == pytest.approx(43.8406, abs=1e-3)


@needs_build123d_frag
def test_a_hole_off_pattern_fails_with_the_standard_named(tmp_path: Path):
    """#93 acceptance: one hole 1 mm off — the failing check's id and source
    name the standard, so the agent knows whose number it missed."""
    from partspec import build123d
    from partspec.refs import nema17
    from partspec.runner import run

    model = tmp_path / "bracket.py"
    model.write_text(_BRACKET_MODEL)
    p = Part("bracket", build123d(model, offset=1.0))
    nema17.mount(p)
    report = run(p, out_dir=tmp_path)
    circle = next(c for c in report.checks if c.id == "nema17:bolt_circle")
    assert circle.status.value == "fail"
    assert circle.source is not None and circle.source["bcd"]["standard"] == "NEMA ICS 16"


def test_two_mounts_coexist_with_instances_and_a_total_pilot_count():
    from partspec.refs import nema17

    p = _part()
    nema17.mount(p, instance="left", pilot_count=2)
    nema17.mount(p, instance="right", pilot_count=2)
    ids = [c.id for c in p.checks]
    assert ids == [
        "nema17:left:pilot",
        "nema17:left:bolt_circle",
        "nema17:right:pilot",
        "nema17:right:bolt_circle",
    ]


def test_a_failed_mount_leaves_the_part_untouched():
    """Atomic declaration: a bad argument must not half-land checks, or the
    corrected retry dies on a collision with the failed attempt's leavings
    (PR #96 review, S2)."""
    from partspec.refs import nema17

    p = _part()
    with pytest.raises(ContractError, match="bcd > d"):
        nema17.mount(p, bolt_holes=50.0)
    assert p.checks == [], "nothing may land from a failed declaration"
    nema17.mount(p)  # the corrected retry must not collide
    assert len(p.checks) == 2


# --------------------------------------------------------------------------
# the unattributed-limit warning (#50)
# --------------------------------------------------------------------------

CIRCULAR_MODEL = Path(__file__).parent / "fixtures" / "circular" / "model.py"


def _circular_part(plate_y: float) -> Part:
    """The circular contract, after the #50 repro: every bound is computed
    from the same constants the model is built from (the repro's genus and
    envelope-min claims are dropped as immaterial to the table)."""
    import math

    from partspec import build123d

    px, pz, bore = 40.0, 6.0, 8.0
    p = Part(
        "circular",
        build123d(
            CIRCULAR_MODEL, method="plate", plate_x=px, plate_y=plate_y, plate_z=pz, bore_d=bore
        ),
    )
    v = px * plate_y * pz - math.pi * (bore / 2) ** 2 * pz
    p.volume(min=v * 0.99, max=v * 1.01)
    p.envelope(max=(px + 0.1, plate_y + 0.1, pz + 0.1))
    p.watertight()
    p.solid_count(1)
    return p


@needs_build123d
@pytest.mark.parametrize(("plate_y", "expected_exit"), [(30.0, 0), (25.0, 0), (5.0, 1)])
def test_the_circular_contract_regression_table(tmp_path: Path, plate_y, expected_exit):
    """The #50 repro's table, pinned: a contract whose every bound is derived
    from the model's own constants passes green however the plate shrinks.
    At plate_y=5 it finally fails on two fronts at once: topology
    (solid_count — absolute, cannot be circular) and volume — whose circular
    formula stops modelling the geometry once the bore breaches the plate.
    Circularity protects a bound only while the derivation stays valid."""
    from partspec.runner import run
    from partspec.status import Status

    report = run(_circular_part(plate_y), out_dir=tmp_path)
    assert report.exit_code == expected_exit, [c.to_json() for c in report.checks]
    if expected_exit == 1:
        failing = {c.id for c in report.checks if c.status is Status.FAIL}
        assert failing == {"volume", "solid_count"}


@needs_build123d
def test_a_fully_unattributed_run_draws_the_warning(tmp_path: Path, capsys):
    """The warning is the run-level signal the per-check absence adds up to:
    every dimensional bound self-derived means the green proved the model
    matches itself. Same channel as the empty-contract warning."""
    from partspec.cli import main

    contract = tmp_path / "spec.py"
    contract.write_text(
        "import math\n"
        "from partspec import Part, build123d\n\n"
        f"MODEL = {str(CIRCULAR_MODEL)!r}\n"
        "PX, PY, PZ, BORE = 40.0, 30.0, 6.0, 8.0\n\n\n"
        "def circular() -> Part:\n"
        "    p = Part('circular', build123d(MODEL, method='plate',\n"
        "             plate_x=PX, plate_y=PY, plate_z=PZ, bore_d=BORE))\n"
        "    v = PX * PY * PZ - math.pi * (BORE / 2) ** 2 * PZ\n"
        "    p.volume(min=v * 0.99, max=v * 1.01)\n"
        "    p.envelope(max=(PX + 0.1, PY + 0.1, PZ + 0.1))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    code = main(["check", f"{contract}:circular", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert code == 0, err
    # Counting the phrase, not the word: pytest's tmp dir is named after this
    # very test, so the report path itself contains "unattributed".
    assert err.count("is unattributed:") == 1, "one line, never a chorus"
    assert "every dimensional limit on 'circular' is unattributed" in err
    assert "partspec.refs" in err


@needs_build123d
def test_one_attributed_bound_quiets_the_warning(tmp_path: Path, capsys):
    from partspec.cli import main

    contract = tmp_path / "spec.py"
    contract.write_text(
        "from partspec import Part, build123d\n"
        "from partspec.refs import iso15\n\n"
        f"MODEL = {str(CIRCULAR_MODEL)!r}\n\n\n"
        "def housing() -> Part:\n"
        "    p = Part('housing', build123d(MODEL, method='plate', bore_d=22.0))\n"
        "    p.hole_diameter(iso15.bearing(608).od, tol=0.05)\n"
        "    p.envelope(max=(40.1, 30.1, 6.1))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    code = main(["check", f"{contract}:housing", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "unattributed" not in err


@needs_mesh
@needs_openscad
def test_a_topology_only_contract_never_warns(tmp_path: Path, capsys):
    """Topological claims are absolute and cannot be circular; a contract made
    of them has no attribution question to answer."""
    from partspec.cli import main

    scad = tmp_path / "p.scad"
    scad.write_text(
        "difference() { cube([30, 20, 10]); translate([12, 7, -1]) cube([6, 6, 12]); }\n"
    )
    contract = tmp_path / "spec.py"
    contract.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def block() -> Part:\n"
        f"    p = Part('block', openscad({str(scad)!r}))\n"
        "    p.watertight()\n"
        "    p.solid_count(1)\n"
        "    p.genus(1)\n"
        "    return p\n"
    )
    code = main(["check", f"{contract}:block", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "unattributed" not in err


@needs_mesh
@needs_openscad
def test_param_bounds_count_toward_attribution(tmp_path: Path, capsys):
    """#50's acceptance names param explicitly, and a mutant dropping
    param_range from DIMENSIONAL_KINDS survived the suite (PR #97 review):
    a bare param bound must warn, a referenced one must not."""
    from partspec.cli import main

    scad = tmp_path / "p.scad"
    scad.write_text("w = 5;\ncube([10, 10, w]);\n")
    contract = tmp_path / "spec.py"
    contract.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def bare() -> Part:\n"
        f"    p = Part('bare', openscad({str(scad)!r}, w=7.0))\n"
        "    p.param('w', min=1.0)\n"
        "    return p\n\n\n"
        "def cited() -> Part:\n"
        "    from partspec.refs import iso15\n"
        f"    p = Part('cited', openscad({str(scad)!r}, w=7.0))\n"
        "    p.param('w', max=iso15.bearing(608).width)\n"
        "    return p\n"
    )
    assert main(["check", f"{contract}:bare", "--out", str(tmp_path / "a")]) == 0
    assert "unattributed" in capsys.readouterr().err
    assert main(["check", f"{contract}:cited", "--out", str(tmp_path / "b")]) == 0
    assert "unattributed" not in capsys.readouterr().err


def test_the_attribution_block_is_in_the_artifact(tmp_path: Path):
    """The report is the product surface: an MCP consumer never sees stderr,
    and #50's motivating agent must find the signal in the JSON (PR #97
    review blocker)."""
    from partspec.report import CheckResult, Report
    from partspec.status import Limit, Status

    r = Report(part_id="p", contract="c", tool_version="t")
    r.checks = [
        CheckResult(
            id="volume", kind="volume", phase="geometry", status=Status.PASS, limit=Limit(min=1.0)
        ),
        CheckResult(
            id="hole_d22",
            kind="hole_diameter",
            phase="geometry",
            status=Status.PASS,
            limit=Limit(min=21.95, max=22.05),
            source={"d": _SRC},
        ),
        CheckResult(id="watertight", kind="watertight", phase="geometry", status=Status.PASS),
    ]
    doc = r.to_json()
    assert doc["attribution"] == {"dimensional": 2, "attributed": 1}
    keys = list(doc)
    assert keys.index("attribution") == keys.index("counts") + 1
