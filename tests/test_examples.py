"""The worked exemplars stay green, and teach what they claim to (#25).

Each exemplar's acceptance is executable: parameterised, decomposed, contract
footed on external references — and every one exercised from this repo, not
from an untracked workspace (the audit revision's sharpening of #25).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import needs_scad_tier, report_of

from partspec.cli import main
from partspec.refs import nema17

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_the_bracket_carries_the_standards_citation(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    target = f"{EXAMPLES / 'stepper-bracket' / 'spec.py'}:stepper_bracket"
    assert main(["check", target, "--quiet", "--out", str(tmp_path)]) == 0

    report = report_of(tmp_path)
    assert report["attribution"]["attributed"] >= 1, "the mount claims are cited"
    bolt = next(c for c in report["checks"] if c["id"] == "nema17:bolt_circle")
    assert bolt["status"] == "pass"
    assert bolt["source"]["bcd"]["standard"] == "NEMA ICS 16"


def test_the_bracket_is_the_worked_region_example(tmp_path: Path):
    """#200: `keep_out`/`keep_in` appeared in no example anywhere, so an author
    had to guess `region.cylinder`'s argument shapes — and two fleet agents on
    different engines guessed `axis=(0, 0, 1)`.

    Asserts the example teaches the thing it claims to. Both region checks
    pass, both carry their region in the report, and the cylinder's axis is
    the string the guessing was about.
    """
    pytest.importorskip("build123d", reason="occt extra not installed")
    target = f"{EXAMPLES / 'stepper-bracket' / 'spec.py'}:stepper_bracket"
    assert main(["check", target, "--quiet", "--out", str(tmp_path)]) == 0

    report = report_of(tmp_path)
    by_id = {c["id"]: c for c in report["checks"]}

    boss = by_id["pilot-boss-clearance"]
    assert boss["kind"] == "keep_out" and boss["status"] == "pass"
    # A STRING, and the right one. `(0, 0, 1)` is what the fleet guessed.
    assert boss["region"]["axis"] == "y", "the plate's thickness runs in y"
    assert boss["region"]["d"] == pytest.approx(float(nema17.PILOT_BOSS))

    joint = by_id["plate-base-joint"]
    assert joint["kind"] == "keep_in" and joint["status"] == "pass"
    # It must reach BEYOND the plate's own 5 mm thickness, or the plate alone
    # satisfies it and the joint is not what is being proven — which is how
    # the first draft passed with the base cut to a third of its width.
    assert joint["region"]["max"][1] > 5.0

    # And the example's prose is the example's code.
    readme = (EXAMPLES / "stepper-bracket" / "README.md").read_text()
    skill = (
        Path(__file__).resolve().parents[1] / "skills" / "contract-authoring" / "SKILL.md"
    ).read_text()
    for doc, name in ((readme, "the example README"), (skill, "SKILL.md")):
        assert 'axis="y"' in doc or 'axis="z"' in doc, f"{name} shows no spelled-out axis"
        assert "p.keep_out(" in doc and "p.keep_in(" in doc, f"{name} shows no region call"


def test_the_bearing_family_follows_the_standard(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    spec = EXAMPLES / "bearing-block" / "spec_py.py"
    targets = [f"{spec}:seat_608", f"{spec}:seat_6000", f"{spec}:seat_6200"]
    assert main(["check", *targets, "--quiet", "--out", str(tmp_path)]) == 0

    report = report_of(tmp_path / "spec_py-seat_608")
    seat = next(c for c in report["checks"] if c["id"] == "iso15:608:seat")
    assert seat["status"] == "pass"
    assert seat["source"]["d"]["standard"] == "ISO 15"


@needs_scad_tier
def test_the_scad_leg_warns_about_its_unattributed_envelope(tmp_path: Path, capsys):
    """The exemplar shows the disclosure instead of hiding it: this leg's only
    dimensional bound is derived from the design's own numbers, and the README
    says exactly that."""
    target = f"{EXAMPLES / 'bearing-block' / 'spec_scad.py'}:seat_608"
    assert main(["check", target, "--out", str(tmp_path)]) == 0
    assert "is unattributed:" in capsys.readouterr().err
    assert report_of(tmp_path)["attribution"] == {"dimensional": 1, "attributed": 0}


@needs_scad_tier
def test_the_enclosure_family_is_green_and_the_contradiction_is_not(tmp_path: Path):
    spec = EXAMPLES / "enclosure" / "spec.py"
    ok = [f"{spec}:small", f"{spec}:deep", f"{spec}:thickwall"]
    assert main(["check", *ok, "--quiet", "--out", str(tmp_path / "ok")]) == 0

    report = report_of(tmp_path / "ok" / "spec-small")
    genus = next(c for c in report["checks"] if c["kind"] == "genus")
    assert genus["status"] == "pass" and genus["measurement"]["value"] == 0
    cavities = next(c for c in report["checks"] if c["kind"] == "cavities")
    assert cavities["status"] == "pass" and cavities["measurement"]["value"] == 1, (
        "the sealedness claim is cavities(1) — an open tray passes everything else"
    )

    code = main(["check", f"{spec}:contradictory", "--quiet", "--out", str(tmp_path / "bad")])
    assert code == 1, "the impossible member fails in the parameter phase"
    bad = report_of(tmp_path / "bad")
    failing = next(c for c in bad["checks"] if c["status"] == "fail")
    assert failing["phase"] == "parameter"
    assert failing["operands"], "the report names the values that contradicted"


def test_every_exemplar_model_is_parameterised_and_documented():
    """The structural half of the acceptance, held mechanically: every
    exemplar directory carries a README, and every factory model takes
    parameters rather than hardcoding its dimensions."""
    # Derived, not listed: `spacer` had no README for six releases while being
    # the example the front page inlines, and a hardcoded list is what let that
    # sit. Every exemplar directory now has to explain itself.
    #
    # `spec*.py`, not `spec.py` — `bearing-block` carries `spec_py.py` and
    # `spec_scad.py`, so the first version of this derivation silently DROPPED
    # it and the check was weaker than the hardcoded list it replaced (PR #155
    # review). And `== 4`, not `>= 3`: three-of-four passing is precisely how
    # that went unnoticed.
    exemplars = sorted(d for d in EXAMPLES.iterdir() if d.is_dir() and any(d.glob("spec*.py")))
    assert len(exemplars) == 4, f"the exemplars moved; this test needs to know: {exemplars}"
    for d in exemplars:
        assert (d / "README.md").is_file(), f"{d.name} must explain what it teaches"
    bracket = (EXAMPLES / "stepper-bracket" / "bracket.py").read_text()
    assert "def bracket(" in bracket and "width: float" in bracket
    block = (EXAMPLES / "bearing-block" / "block.py").read_text()
    assert "def block(" in block and "bore_d: float" in block


def test_the_spacer_readme_describes_the_contract_it_documents():
    """The exemplar READMEs enumerate their claims in prose, and prose about
    code is how this repo has repeatedly drifted. Written after the first draft
    of this README named two claims the contract does not make — `wall_min <=
    plate_x` and a bound on `bore_d` — so the table is checked against the
    source rather than read."""
    import re

    readme = (EXAMPLES / "spacer" / "README.md").read_text()
    spec = (EXAMPLES / "spacer" / "spec.py").read_text()

    claimed = re.findall(r"^\| `([^`]+)` \|", readme, re.M)
    assert len(claimed) >= 5, "the README must still enumerate the contract's claims"
    for claim in claimed:
        assert f"p.{claim}" in spec, f"the README claims `p.{claim}`, which the contract does not"

    # Whole calls, not method names. Comparing names let a NEW claim reusing a
    # documented name through — `p.param("plate_x", min=999.0)` beside the
    # documented `p.param("plate_z", min=1.0)` passed (PR #155 review).
    import ast

    def normalise(call: str) -> str:
        return ast.unparse(ast.parse(call, mode="eval"))

    declared = {
        ast.unparse(node)[2:]
        for node in ast.walk(ast.parse(spec))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "p"
    }
    assert {normalise(c) for c in claimed} == {normalise(d) for d in declared}, (
        f"undocumented claims: {sorted(declared)}; documented: {sorted(claimed)}"
    )
