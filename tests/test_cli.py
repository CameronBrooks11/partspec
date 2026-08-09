"""The CLI surface: `measure`'s output shape and `check`'s exit code.

D5 makes the report schema plus the exit code the product contract, not the
verbs — which is precisely why the verbs need tests. Everything below asserts
something a consumer would break on.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from support import needs_openscad

from partspec.cli import main
from partspec.status import Verdict, exit_code

pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"


def _contract(tmp_path: Path, scad: str, body: str) -> str:
    """Write a contract module next to a copy of its source, return its target."""
    shutil.copy(FIXTURES / scad, tmp_path / scad)
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part('subject', openscad({scad!r}))\n"
        f"{body}"
        "    return p\n"
    )
    return f"{module}:make"


def _measure(target: str, capsys) -> dict:
    assert main(["measure", target]) == 0, "measure never produces a verdict"
    return json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# measure — the adoption path
# --------------------------------------------------------------------------


@needs_openscad
def test_measure_reports_the_quantities_it_can_answer(tmp_path: Path, capsys):
    doc = _measure(_contract(tmp_path, "block_with_hole.scad", ""), capsys)
    assert doc["engine"]["backend"] == "mesh"
    assert doc["measurements"]["volume"]["value"] == pytest.approx(30 * 20 * 10 - 6 * 6 * 10)
    assert "refused" not in doc, "a sound part refuses nothing"


@needs_openscad
def test_measure_says_why_it_refused_rather_than_omitting_the_quantity(tmp_path: Path, capsys):
    """The bug this replaced, and the reason it mattered.

    `measure` dropped every `Unsupported` silently. That was honest while a
    refusal only ever meant "this tier cannot answer this quantity" — a static
    fact, the same for every part. Since D17 it also means "this part is
    broken, and here is the defect", and the two arrived identically: absent.

    On an open box that leaves a reader looking at area, bbox and solid_count
    with no volume line, in the verb whose whole job is showing you the numbers
    before you decide which are intent. They would write a contract that
    declines to claim a volume, and the omission would have taught them that.
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)

    assert set(doc["refused"]) == {"volume", "center_of_mass", "genus"}
    for name, reason in doc["refused"].items():
        assert "boundary edge" in reason, f"{name} must name the defect, not just decline"
        assert name not in doc["measurements"], "a refusal must not also carry a number"

    assert doc["measurements"]["watertight"]["value"] is False
    assert doc["measurements"]["area"]["value"] == pytest.approx(500.0)


@needs_openscad
def test_measure_shows_cavities(tmp_path: Path, capsys):
    """#113: the number distinguishing a sealed enclosure from an open tray
    was absent from the verb whose job is showing every claimable number."""
    doc = _measure(_contract(tmp_path, "block_with_hole.scad", ""), capsys)
    assert doc["measurements"]["cavities"]["value"] == 0


@needs_openscad
def test_measure_separates_a_tier_gap_from_a_broken_part(tmp_path: Path, capsys):
    """Two different silences, and conflating them is what went wrong before.

    `unavailable` is a property of the backend and identical for every part it
    will ever see. `refused` is a property of *this* part. A reader deciding
    what to assert needs to tell "you need the OCCT tier for that" apart from
    "fix your model".
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)
    assert doc["unavailable"] == [
        "self_intersection_free",
        "topology_counts",
        "bores",
        "blend_radii",
    ]
    assert "topology_counts" not in doc["refused"]


@needs_openscad
def test_measure_produces_no_verdict_on_a_broken_part(tmp_path: Path, capsys):
    """Exit 0 on an open box is correct here and would be a bug in `check`.

    `measure` asks no question, so it cannot answer one wrongly. The verdict
    machinery deliberately does not run.
    """
    doc = _measure(_contract(tmp_path, "open_box.scad", ""), capsys)
    assert "verdict" not in doc and "checks" not in doc


# --------------------------------------------------------------------------
# measure — identity (#47): as identifiable as a report
# --------------------------------------------------------------------------


@needs_openscad
def test_measure_carries_the_same_identity_as_the_report(tmp_path: Path, capsys):
    """One builder serves both verbs, and this pin is what keeps them from
    drifting apart again (#73 was exactly that drift, in the engine block).
    A consumer turning measure output into checks must be able to say which
    file, which revision, and which parameters produced the numbers."""
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())

    doc = _measure(target, capsys)
    assert doc["schema_version"] == report["schema_version"]
    assert doc["part"] == report["part"]
    assert doc["params"] == report["params"]
    # Presence, not just sameness: the equality pin alone cannot see a field
    # both sides lost together (PR #102 review, mutant survivor).
    assert doc["part"]["contract_digest"].startswith("sha256:")
    assert doc["part"]["source_digest"].startswith("sha256:")
    assert list(doc)[:7] == [
        "schema_version",
        "tool",
        "part",
        "engine",
        "params",
        "geometry",
        "measurements",
    ]


@needs_openscad
def test_measure_records_the_parameters_that_produced_the_numbers(tmp_path: Path, capsys):
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('block_with_hole.scad', hole=4))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    assert doc["params"] == {"hole": 4}


@needs_openscad
def test_measure_failure_is_an_artifact_not_a_shrug(tmp_path: Path, capsys):
    """A caller parsing stdout used to get an empty string and a bare exit
    code, with the reason on stderr only — machine-invisible exactly where a
    machine is the audience (#47)."""
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad', bore_diamter=8))\n"
    )
    assert main(["measure", f"{module}:make"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["schema_version"] == 1
    assert doc["part"]["id"] == "subject"
    assert doc["part"]["contract"].endswith("spec.py")
    assert doc["engine"]["kind"] == "openscad"
    # The payload records what was ASKED; `error` says what happened. A
    # typo'd parameter stays visible rather than vanishing with the build.
    assert doc["params"] == {"bore_diamter": 8}
    assert doc["geometry"] == {}
    assert "not found" in doc["error"]
    assert "hint" in doc
    assert "not found" in captured.err, "the console courtesy line survives"


def test_measure_python_closure_appears_after_the_build(tmp_path: Path, capsys):
    """A Python model's inputs are only knowable once it has run; measure's
    identity must carry the same imports-derived closure the report does."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helper47.py").write_text("SIZE = 2\n")
    (tmp_path / "model.py").write_text(
        "import helper47\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper47.SIZE, 1, 1)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('model.py'))\n"
    )
    doc = _measure(f"{module}:make", capsys)
    closure = doc["part"]["source_closure"]
    assert closure["scope"] == "model_directory"
    assert closure["partial"] is True
    assert closure["files"] >= 2, "the helper the model imported is a build input"


# --------------------------------------------------------------------------
# check — the exit code is half the contract
# --------------------------------------------------------------------------


@needs_openscad
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("    p.watertight()\n", Verdict.PASS),
        ("    p.envelope(max=(1, 1, 1))\n", Verdict.FAIL),
        ("    p.topology(faces=6)\n", Verdict.INCOMPLETE),
        ("", Verdict.EMPTY),
    ],
)
def test_check_exits_with_the_verdicts_code(tmp_path: Path, body: str, expected: Verdict):
    """Every verdict, through `main`, on a real render.

    The exit code is the only thing a CI job reads, so a report that is right
    while the process exits 0 anyway would defeat all of it.
    """
    target = _contract(tmp_path, "block_with_hole.scad", body)
    assert main(["check", target, "--quiet"]) == exit_code(expected)


@needs_openscad
def test_check_writes_the_report_where_it_says_it_did(tmp_path: Path, capsys):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    assert main(["check", target]) == 0
    printed = capsys.readouterr().err.strip().splitlines()[-1].strip()
    doc = json.loads(Path(printed).read_text())
    assert doc["verdict"] == "pass"


def test_an_unresolvable_target_is_a_usage_error_not_a_crash(tmp_path: Path):
    assert main(["check", str(tmp_path / "nope.py")]) == 64
    assert main(["measure", str(tmp_path / "nope.py")]) == 64


@pytest.mark.parametrize("verb", ["check", "measure"])
def test_a_contract_that_raises_does_not_exit_as_a_failing_part(tmp_path: Path, verb: str):
    """Found by mistyping a keyword argument while writing a real contract.

    The traceback escaped `main` and the interpreter exited 1, which is this
    tool's code for *the part failed its contract*. A malformed question would
    have been recorded in CI as a wrong answer about the design, and the two
    are indistinguishable from the outside. Exit 4: nothing was evaluated, so
    nothing may be said about the part.
    """
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def make() -> Part:\n"
        "    return Part('x', openscad('x.scad')).envelope(max=(1, 1, 1), tol=0.05)\n"
    )
    assert main([verb, f"{module}:make"]) == exit_code(Verdict.ERROR)


def test_no_arguments_prints_help(capsys):
    assert main([]) == 64
    assert "usage:" in capsys.readouterr().out


@needs_openscad
def test_a_contract_that_raises_does_not_leave_the_previous_verdict(tmp_path: Path):
    """The regression this ordering exists to prevent.

    `write_placeholder` used to run *after* the contract resolved, so a contract
    that raised returned exit 4 without touching the output directory — leaving
    the previous run's `verdict: "pass"` at the deterministic path. The exit code
    said error and the artifact said the part was fine, and the artifact is what
    a later reader trusts.
    """
    scad = tmp_path / "box.scad"
    scad.write_text("x = 10;\ncube([x, x, x]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n"
        "def part() -> Part:\n"
        "    p = Part('stale', openscad('box.scad', x=10.0))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 0
    report = out / "report.json"
    assert json.loads(report.read_text())["verdict"] == "pass", "premise: a green run on disk"

    spec.write_text(
        "from partspec import Part\ndef part() -> Part:\n    raise RuntimeError('boom')\n"
    )
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert json.loads(report.read_text())["verdict"] == "error", (
        "the previous run's pass survived a contract that raised"
    )


def test_a_contract_calling_sys_exit_is_not_a_green_run(tmp_path: Path):
    """`sys.exit(0)` raises SystemExit, which sailed past `except Exception` and
    exited the process 0 — green, silent, zero checks evaluated. The exit code
    was the contract's to choose: `sys.exit(2)` read as incomplete."""
    spec = tmp_path / "spec.py"
    spec.write_text("import sys\nfrom partspec import Part\ndef part() -> Part:\n    sys.exit(0)\n")
    out = tmp_path / "out"
    assert main(["check", f"{spec}:part", "--out", str(out), "--quiet"]) == 4
    assert json.loads((out / "report.json").read_text())["verdict"] == "error"


def test_argparse_still_owns_its_own_exits():
    """The BaseException guard is scoped to contract resolution, so argparse's
    SystemExit for `--version` and usage errors is untouched."""
    with pytest.raises(SystemExit):
        main(["--version"])


def test_render_on_the_occt_tier_from_the_same_verb(tmp_path: Path, capsys):
    """#18: same verb, same view names, and the payload carries what this
    tier uniquely knows — the backend that ran, the build-derived closure,
    and the tessellation that is what was actually shown (D15)."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helper18.py").write_text("SIZE = 20\n")
    (tmp_path / "model.py").write_text(
        "import helper18\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper18.SIZE, 10, 5)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('model.py'))\n"
    )
    assert main(["render", f"{module}:make", "--out", str(tmp_path / "out")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["renders"]) == {"iso", "front", "top", "right"}
    for path in payload["renders"].values():
        assert Path(path).stat().st_size > 0
    assert payload["engine"]["kind"] == "build123d"
    assert payload["engine"]["backend"] == "occt", "the tier that ran is named"
    assert payload["render_tessellation"]["tolerance_mm"] == 0.1
    assert payload["render_tessellation"]["triangles"] > 0
    # built=True identity: the helper the model imported is a build input,
    # knowable only because this verb actually built the part.
    assert payload["part"]["source_closure"]["files"] >= 2


def test_a_failed_build_never_reaches_the_rasterizer(tmp_path: Path, capsys, monkeypatch):
    """PR #127 review, F1: the raster import (which pulls numpy) sat before
    the build, so with the occt extra missing the verb died as a raw numpy
    traceback — empty stdout — instead of the build's honest environment
    artifact. The import order is the fix; this hook is the pin: a failing
    build must produce the #103 artifact without partspec.raster ever
    loading."""
    pytest.importorskip("build123d", reason="occt extra not installed")

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "partspec.raster":
                raise ImportError("partspec.raster must not load before the build succeeds")
            return None

    import partspec

    # Both evictions, or the pin is vacuous (the reviewer demonstrated it):
    # another test file's import binds `raster` as an attribute on the
    # package object, and `from . import raster` is satisfied by hasattr
    # without the import machinery — the hook would never fire in-suite.
    monkeypatch.delitem(sys.modules, "partspec.raster", raising=False)
    monkeypatch.delattr(partspec, "raster", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Block(), *sys.meta_path])
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('missing.py'))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["part"]["id"] == "subject"
    assert doc["renders"] == {}
    assert doc["error"]


def test_render_on_a_broken_python_model_is_an_artifact(tmp_path: Path, capsys):
    """This target used to be refused as usage (64) when the tier had no
    render; now the tier renders, a model with no factory is a build failure
    — an identifiable artifact at exit 4, like every resolved-target failure."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text("")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["part"]["id"] == "subject"
    assert doc["engine"]["backend"] == "occt"
    assert doc["renders"] == {}
    assert doc["error"]


@needs_openscad
def test_render_writes_the_views_or_reports_the_display(tmp_path: Path, capsys):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    code = main(["render", target])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert set(payload["renders"]) == {"iso", "front", "top", "right"}
        for path in payload["renders"].values():
            assert Path(path).stat().st_size > 0
    else:
        assert code == 4
        assert "display" in captured.err


@needs_openscad
def test_check_render_records_the_views_in_the_report_or_fails_the_run(tmp_path: Path):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--quiet", "--render", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    if code == 0:
        # Relative POSIX paths keyed by view, resolving against the report's
        # own directory (SPEC-report.md section 8.4).
        assert set(report["renders"]) == {"iso", "front", "top", "right"}
        for rel in report["renders"].values():
            assert not Path(rel).is_absolute()
            assert (out / rel).stat().st_size > 0
    else:
        # No display: the run fails loudly and the key is absent — the report
        # speaks for the part, the exit code for the run.
        assert code == 4
        assert "renders" not in report
        assert report["verdict"] == "pass"


@needs_openscad
def test_a_report_without_render_carries_no_renders_key(tmp_path: Path):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    assert "renders" not in json.loads((out / "report.json").read_text())


def test_check_render_on_the_occt_tier_records_the_views(tmp_path: Path):
    """The same-verb half of #18: `check --render` on a Python part records
    the views and the tessellation in the report, exactly as the OpenSCAD
    tier does — no display in the loop, so this branch has no refusal arm."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.volume(min=0.0)\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{module}:make", "--render", "--quiet", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert set(report["renders"]) == {"iso", "front", "top", "right"}
    for rel in report["renders"].values():
        assert not Path(rel).is_absolute()
        assert (out / rel).stat().st_size > 0
    assert report["render_tessellation"]["triangles"] > 0


def test_a_section_shows_the_bore_the_outside_views_cannot(tmp_path: Path, capsys):
    """#19: F16's bore is invisible from outside; the section makes it a
    void in the cut face. The payload records the resolved plane and offset
    — never implicit — and the cut-facet count."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box, Cylinder, Location\n\n\ndef make_part():\n"
        "    return Box(20, 10, 6) - Location((5, 0, 0)) * Cylinder(2, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xy"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["renders"]) == {"iso", "front", "top", "right", "section_xy"}
    assert Path(payload["renders"]["section_xy"]).stat().st_size > 0
    assert payload["section"]["plane"] == "xy"
    assert payload["section"]["offset_mm"] == 0.0, "default: the bbox centre, resolved"
    assert payload["section"]["cut_triangles"] > 0


def test_a_section_offset_is_recorded_as_given(tmp_path: Path, capsys):
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xz:1.5"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["section"] == {
        "plane": "xz",
        "offset_mm": 1.5,
        "cut_triangles": payload["section"]["cut_triangles"],
    }
    assert "section_xz" in payload["renders"]


def test_a_section_that_misses_the_part_is_refused_with_the_range(tmp_path: Path, capsys):
    """A plane outside the part would render the uncut part — an image that
    looks fine, which is this project's documented failure. Refused, with
    the span the caller needs to aim again."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "o"), "--section", "xy:99"])
    assert code == exit_code(Verdict.ERROR)
    doc = json.loads(capsys.readouterr().out)
    assert doc["renders"] == {}
    assert "misses the part" in doc["error"]
    assert "z spans" in doc["error"]


def test_a_malformed_section_is_usage_before_any_work(tmp_path: Path, capsys):
    module = tmp_path / "spec.py"
    module.write_text("def make():\n    raise AssertionError('must not resolve')\n")
    for bad in ("ab", "xy:abc", "xy:inf", "zz:1"):
        assert main(["render", f"{module}:make", "--section", bad]) == 64, bad
        assert "--section takes" in capsys.readouterr().err


def _cut_pixels(path: Path) -> int:
    """Pixels wearing the exact shaded cut colour — the deterministic value
    the rasterizer produces for a cap facing its camera head-on."""
    import math
    import struct
    import zlib

    np = pytest.importorskip("numpy")
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    idat = b""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    img = np.frombuffer(raw, np.uint8).reshape(height, width * 3 + 1)[:, 1:]
    img = img.reshape(height, width, 3)
    lz = 0.89 / math.sqrt(0.35**2 + 0.30**2 + 0.89**2)
    shade = 0.35 + 0.65 * lz
    cut = tuple(int(c * shade) for c in (204, 92, 63))
    return int((img == cut).all(axis=2).sum())


@pytest.mark.parametrize(
    ("plane", "kept", "discarded"),
    [
        ("xy", "Location((0, 0, -3)) * Box(20, 10, 6)", "Location((0, 0, 3)) * Box(6, 6, 6)"),
        ("xz", "Location((0, 3, 0)) * Box(20, 6, 10)", "Location((0, -3, 0)) * Box(6, 6, 6)"),
        ("yz", "Location((-3, 0, 0)) * Box(6, 20, 10)", "Location((3, 0, 0)) * Box(6, 6, 6)"),
    ],
)
def test_the_section_keeps_the_half_the_camera_faces(
    tmp_path: Path, capsys, plane: str, kept: str, discarded: str
):
    """PR #130 review, F2: every earlier section test cut a part symmetric
    about the plane, so flipping the discard side changed the images and
    failed nothing. Here the KEPT side carries a wide slab whose cap fills
    the frame with the cut colour; the discard side a narrow post whose own
    faces would occlude every cut pixel. A flipped half renders ZERO
    cut-coloured pixels — per plane, since each plane's sign is separate."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box, Location\n\n\ndef make_part():\n"
        f"    return {kept} + {discarded}\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    code = main(
        ["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", f"{plane}:0"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    section = Path(payload["renders"][f"section_{plane}"])
    assert _cut_pixels(section) > 10_000, (
        f"the {plane} section shows no cut face where the kept slab's cap "
        "should fill the frame — the discard side is flipped"
    )


@needs_openscad
def test_the_scad_tier_keeps_the_same_half(tmp_path: Path, capsys):
    """The discard side is decided independently in openscad.py — a flip
    there would break cross-tier agreement silently. Same construction as
    the OCCT xz case (the plane whose sign differs from the other two)."""
    pytest.importorskip("numpy", reason="no extra installed")
    (tmp_path / "part.scad").write_text(
        "union() { translate([0, 3, 0]) cube([20, 6, 10], center = true);"
        " translate([0, -3, 0]) cube([6, 6, 6], center = true); }\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('part.scad'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xz:0"])
    payload = json.loads(capsys.readouterr().out)
    if code == 0:
        assert _cut_pixels(Path(payload["renders"]["section_xz"])) > 10_000
    else:
        assert code == 4
        assert "display" in payload["error"]


def test_render_leaves_its_payload_on_disk_for_a_later_vdiff(tmp_path: Path, capsys):
    """#21: stdout serves the invoker, but a visual diff needs the engine
    version and framing bbox of a PAST run. render.json mirrors the payload
    with renders relativized to its own directory (the report's portability
    rule), and the bbox rides with every render — the only scale witness a
    framed image leaves."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = tmp_path / "out"
    assert main(["render", f"{module}:make", "--out", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    disk = json.loads((out / "render.json").read_text())
    assert payload["render_bbox"] == {"min": [-10.0, -5.0, -3.0], "max": [10.0, 5.0, 3.0]}
    # Same document, save for the paths: relative on disk, absolute on stdout.
    assert disk["renders"] == {v: f"renders/{v}.png" for v in ("iso", "front", "top", "right")}
    assert {k: v for k, v in disk.items() if k != "renders"} == {
        k: v for k, v in payload.items() if k != "renders"
    }

    # The stale-artifact rule: a failing run clears the previous payload.
    (tmp_path / "m.py").write_text("broken\n")
    assert main(["render", f"{module}:make", "--out", str(out)]) == 4
    capsys.readouterr()
    assert not (out / "render.json").exists()


@needs_openscad
def test_check_render_records_the_bbox_in_the_report(tmp_path: Path):
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    code = main(["check", target, "--quiet", "--render", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    if code == 0:
        span = [
            b - a
            for a, b in zip(report["render_bbox"]["min"], report["render_bbox"]["max"], strict=True)
        ]
        assert span == pytest.approx([30.0, 20.0, 10.0]), "the block's real extents"
    else:
        assert "render_bbox" not in report, "no images, no framing record"


def test_a_failing_section_leaves_no_stale_image(tmp_path: Path, capsys):
    """PR #130 review, F1: a refused section returned before the rasterizer's
    unlink, leaving the previous run's section_xy.png to be read as this
    run's — the exact stale-artifact class render() documents."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    return Part('subject', build123d('m.py'))\n"
    )
    out = tmp_path / "out"
    assert main(["render", f"{module}:make", "--out", str(out), "--section", "xy"]) == 0
    capsys.readouterr()
    section = out / "renders" / "section_xy.png"
    assert section.is_file()
    assert main(["render", f"{module}:make", "--out", str(out), "--section", "xy:99"]) == 4
    capsys.readouterr()
    assert not section.exists(), "the refused run must not leave the old image"
    assert (out / "renders" / "iso.png").is_file(), "the canonical views still render"


@needs_openscad
def test_a_section_works_on_the_openscad_tier_too(tmp_path: Path, capsys):
    """#19's both-tiers acceptance: the engine cuts its own exported STL
    (kernel-capped), the shared rasterizer draws it. Needs a display only
    for the canonical views that ride along."""
    pytest.importorskip("numpy", reason="no extra installed")
    (tmp_path / "part.scad").write_text(
        "difference() { cube([20, 10, 6], center = true);"
        " translate([5, 0, 0]) cylinder(h = 8, r = 2, center = true, $fn = 32); }\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('part.scad'))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out"), "--section", "xy"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    if code == 0:
        assert "section_xy" in payload["renders"]
        assert Path(payload["renders"]["section_xy"]).stat().st_size > 0
        assert payload["section"]["offset_mm"] == 0.0
        assert payload["section"]["cut_triangles"] > 0
    else:
        # No display: the canonical views fail first, and the artifact says so.
        assert code == 4
        assert "display" in payload["error"]


def test_check_render_builds_the_model_exactly_once(tmp_path: Path):
    """#129: check --render rebuilt the model its run had just built —
    doubling side effects, doubling --timeout exposure, and letting a
    nondeterministic model's renders silently disagree with the measured
    geometry. The run now hands its artifact to the render step."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part():\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(20, 10, 6)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{module}:make", "--render", "--quiet", "--out", str(out)]) == 0
    assert (tmp_path / "builds.txt").read_text() == "1", "one run, one build"
    report = json.loads((out / "report.json").read_text())
    assert set(report["renders"]) == {"iso", "front", "top", "right"}


def test_check_render_never_rebuilds_a_failing_build_for_pictures(tmp_path: Path):
    """PR #133 review, F1: a model-origin build failure left artifact_out
    empty while report.error stayed None, so the render branch rebuilt the
    model — twice the side effects, and exit 4 where plain check says 1.
    Renders depict the run's own successful build, or nothing."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part():\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(2, 2, 2) - Box(8, 8, 8)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    code = main(["check", f"{module}:make", "--render", "--quiet", "--out", str(out)])
    assert (tmp_path / "builds.txt").read_text() == "1", (
        "a failed build is not retried for pictures"
    )
    report = json.loads((out / "report.json").read_text())
    assert "renders" not in report
    # The exit is the report's own, not a render-failure 4 layered on top.
    (tmp_path / "builds.txt").unlink()
    assert main(["check", f"{module}:make", "--quiet", "--out", str(tmp_path / "o2")]) == code


def test_check_render_does_not_build_past_a_parameter_blocker(tmp_path: Path):
    """PR #133 review, F2: a failing `requires` check skips the build — and
    --render used to build anyway, shipping images of a build the report
    says was never evaluated. The artifact must not contradict itself."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "m.py").write_text(
        "from pathlib import Path\n\nfrom build123d import Box\n\n"
        "COUNTER = Path(__file__).parent / 'builds.txt'\n\n\n"
        "def make_part(w=5):\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    return Box(w, 2, 2)\n"
    )
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py', w=5))\n"
        "    p.requires('w > 10')\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{module}:make", "--render", "--quiet", "--out", str(out)]) == 1
    assert not (tmp_path / "builds.txt").exists(), (
        "rejected inputs are never built, even for pictures"
    )
    report = json.loads((out / "report.json").read_text())
    assert "renders" not in report


def test_the_two_python_engines_render_comparable_images(tmp_path: Path):
    """#18's differential arm: the same nominal box through build123d and
    CadQuery must produce near-identical images — same tessellator, same
    framing, same rasterizer, so a disagreement is a real geometry change."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    pytest.importorskip("cadquery", reason="cadquery extra not installed")
    (tmp_path / "bd.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 5)\n"
    )
    (tmp_path / "cq.py").write_text(
        "import cadquery\n\n\ndef make_part():\n    return cadquery.Workplane().box(20, 10, 5)\n"
    )
    for name, engine in (("bd", "build123d"), ("cq", "cadquery")):
        module = tmp_path / f"spec_{name}.py"
        module.write_text(
            f"from partspec import Part, {engine}\n\n\ndef make():\n"
            f"    return Part('subject', {engine}('{name}.py'))\n"
        )
        code = main(["render", f"{module}:make", "--out", str(tmp_path / name)])
        assert code == 0
    for view in ("iso", "front", "top", "right"):
        a = (tmp_path / "bd" / "renders" / f"{view}.png").read_bytes()
        b = (tmp_path / "cq" / "renders" / f"{view}.png").read_bytes()
        assert a == b, f"the {view} view differs between engines"


@needs_openscad
def test_measure_engine_block_matches_the_report_shape(tmp_path: Path, capsys):
    # measure and check had drifted (#73): wrong key order, no method. One
    # constructor now serves both, so a measure artifact answers the same
    # provenance questions a report does.
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    payload = _measure(target, capsys)
    assert list(payload["engine"]) == [
        "kind",
        "version",
        "backend",
        "render_backend",
        "adopted_via",
        "method",
        "param_mode",
    ]
    assert payload["engine"]["method"] is None
    assert payload["engine"]["param_mode"] == "define"


@needs_openscad
def test_render_engine_block_states_the_method(tmp_path: Path, capsys):
    (tmp_path / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('lib.scad', method='block', s=8.0))\n"
    )
    code = main(["render", f"{module}:make", "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    if code == 0:
        payload = json.loads(captured.out)
        assert payload["engine"]["method"] == "block"
        assert payload["engine"]["param_mode"] == "call"
    else:
        assert code == 4  # no display; the refusal path is asserted elsewhere


@needs_openscad
def test_render_carries_the_same_identity_as_the_report(tmp_path: Path, capsys):
    """render was the last verb whose payload named its part with a bare id
    string (#103): no digests, no closure — its images could not be tied to
    the revision that produced them. Same pin as measure's (#47)."""
    target = _contract(tmp_path, "block_with_hole.scad", "    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    capsys.readouterr()

    code = main(["render", target, "--out", str(tmp_path / "r")])
    payload = json.loads(capsys.readouterr().out)
    # With or without a display: the failure artifact carries the same
    # identity prefix as the success payload, so both branches pin here.
    assert code in (0, exit_code(Verdict.ERROR))
    assert payload["schema_version"] == report["schema_version"]
    assert payload["part"] == report["part"]
    assert payload["params"] == report["params"]
    # Presence, not just sameness: the equality pin alone cannot see a field
    # both sides lost together (PR #102 review, mutant survivor).
    assert payload["part"]["contract_digest"].startswith("sha256:")
    assert payload["part"]["source_digest"].startswith("sha256:")
    assert list(payload)[:6] == [
        "schema_version",
        "tool",
        "part",
        "engine",
        "params",
        "renders",
    ]


@needs_openscad
def test_render_failure_is_an_artifact_not_a_shrug(tmp_path: Path, capsys):
    """The render failure path printed to stderr and returned a bare 4 —
    machine-invisible exactly where a machine is the audience (#103, the
    hole #47 closed for measure)."""
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('missing.scad', bore_diamter=8))\n"
    )
    assert main(["render", f"{module}:make"]) == exit_code(Verdict.ERROR)
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["schema_version"] == 1
    assert doc["part"]["id"] == "subject"
    assert doc["part"]["contract"].endswith("spec.py")
    assert doc["engine"]["kind"] == "openscad"
    # The payload records what was ASKED; `error` says what happened. A
    # typo'd parameter stays visible rather than vanishing with the build.
    assert doc["params"] == {"bore_diamter": 8}
    assert doc["renders"] == {}
    assert "not found" in doc["error"]
    assert "hint" in doc
    assert "not found" in captured.err, "the console courtesy line survives"
