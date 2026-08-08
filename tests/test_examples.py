"""The worked exemplars stay green, and teach what they claim to (#25).

Each exemplar's acceptance is executable: parameterised, decomposed, contract
footed on external references — and every one exercised from this repo, not
from an untracked workspace (the audit revision's sharpening of #25).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_openscad

from partspec.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _report(out: Path) -> dict:
    return json.loads((out / "report.json").read_text())


def test_the_bracket_carries_the_standards_citation(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    target = f"{EXAMPLES / 'stepper-bracket' / 'spec.py'}:stepper_bracket"
    assert main(["check", target, "--quiet", "--out", str(tmp_path)]) == 0

    report = _report(tmp_path)
    assert report["attribution"]["attributed"] >= 1, "the mount claims are cited"
    bolt = next(c for c in report["checks"] if c["id"] == "nema17:bolt_circle")
    assert bolt["status"] == "pass"
    assert bolt["source"]["bcd"]["standard"] == "NEMA ICS 16"


def test_the_bearing_family_follows_the_standard(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    spec = EXAMPLES / "bearing-block" / "spec_py.py"
    targets = [f"{spec}:seat_608", f"{spec}:seat_6000", f"{spec}:seat_6200"]
    assert main(["check", *targets, "--quiet", "--out", str(tmp_path)]) == 0

    report = _report(tmp_path / "spec_py-seat_608")
    seat = next(c for c in report["checks"] if c["id"] == "iso15:608:seat")
    assert seat["status"] == "pass"
    assert seat["source"]["d"]["standard"] == "ISO 15"


@needs_openscad
def test_the_scad_leg_warns_about_its_unattributed_envelope(tmp_path: Path, capsys):
    """The exemplar shows the disclosure instead of hiding it: this leg's only
    dimensional bound is derived from the design's own numbers, and the README
    says exactly that."""
    target = f"{EXAMPLES / 'bearing-block' / 'spec_scad.py'}:seat_608"
    assert main(["check", target, "--out", str(tmp_path)]) == 0
    assert "is unattributed:" in capsys.readouterr().err
    assert _report(tmp_path)["attribution"] == {"dimensional": 1, "attributed": 0}


@needs_openscad
def test_the_enclosure_family_is_green_and_the_contradiction_is_not(tmp_path: Path):
    spec = EXAMPLES / "enclosure" / "spec.py"
    ok = [f"{spec}:small", f"{spec}:deep", f"{spec}:thickwall"]
    assert main(["check", *ok, "--quiet", "--out", str(tmp_path / "ok")]) == 0

    report = _report(tmp_path / "ok" / "spec-small")
    genus = next(c for c in report["checks"] if c["kind"] == "genus")
    assert genus["status"] == "pass" and genus["measurement"]["value"] == 0

    code = main(["check", f"{spec}:contradictory", "--quiet", "--out", str(tmp_path / "bad")])
    assert code == 1, "the impossible member fails in the parameter phase"
    bad = _report(tmp_path / "bad")
    failing = next(c for c in bad["checks"] if c["status"] == "fail")
    assert failing["phase"] == "parameter"
    assert failing["operands"], "the report names the values that contradicted"


def test_every_exemplar_model_is_parameterised_and_documented():
    """The structural half of the acceptance, held mechanically: every
    exemplar directory carries a README, and every factory model takes
    parameters rather than hardcoding its dimensions."""
    for name in ("stepper-bracket", "bearing-block", "enclosure"):
        d = EXAMPLES / name
        assert (d / "README.md").is_file(), f"{name} must explain what it teaches"
    bracket = (EXAMPLES / "stepper-bracket" / "bracket.py").read_text()
    assert "def bracket(" in bracket and "width: float" in bracket
    block = (EXAMPLES / "bearing-block" / "block.py").read_text()
    assert "def block(" in block and "bore_d: float" in block
