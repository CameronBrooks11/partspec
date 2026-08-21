"""The worked exemplars stay green, and teach what they claim to (#25).

Each exemplar's acceptance is executable: parameterised, decomposed, contract
footed on external references — and every one exercised from this repo, not
from an untracked workspace (the audit revision's sharpening of #25).
"""

from __future__ import annotations

import re
import textwrap
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


def _region_block(doc: str) -> str:
    """The one fenced python block in `doc` that shows the region calls."""
    blocks = [b for b in re.findall(r"```python\n(.*?)```", doc, re.S) if "p.keep_out(" in b]
    assert len(blocks) == 1, "exactly one block shows the region calls"
    return blocks[0]


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

    # `THICKNESS` from the contract itself, so the assertions below move with
    # the design rather than restating a constant that can drift out of step.
    thickness_src = (EXAMPLES / "stepper-bracket" / "spec.py").read_text()
    declared = re.search(r"^WIDTH, HEIGHT, DEPTH, THICKNESS = .*?, ([\d.]+)$", thickness_src, re.M)
    assert declared, "the contract must still declare THICKNESS on one line"
    thickness = float(declared.group(1))

    report = report_of(tmp_path)
    by_id = {c["id"]: c for c in report["checks"]}

    boss = by_id["pilot-boss-clearance"]
    assert boss["kind"] == "keep_out" and boss["status"] == "pass"
    # A STRING, and the right one. `(0, 0, 1)` is what the fleet guessed.
    assert boss["region"]["axis"] == "y", "the plate's thickness runs in y"
    assert boss["region"]["d"] == pytest.approx(float(nema17.PILOT_BOSS))

    # The joint takes TWO regions, and each must leave the shared corner into
    # one member's OWN territory or it proves nothing about that member. Both
    # failure modes have been shipped in drafts of this example: a box inside
    # the plate's thickness (satisfied by the plate, passed with the base cut
    # away) and a box inside the base's (satisfied by the base, passed with no
    # plate at all). Asserted against `THICKNESS` from the contract rather
    # than a hardcoded 5.0, and on the NEAR corner too — constraining only the
    # far one let a region be moved wholly out of its member and still pass
    # (round 1 of #200's review).
    plate_web, base_web = by_id["joint-web-plate"], by_id["joint-web-base"]
    for web in (plate_web, base_web):
        assert web["kind"] == "keep_in" and web["status"] == "pass"
        # The API requires shell > 0; on these two it is inert (their shells
        # escape the part's outer faces, so a solid brick passes them). The
        # assertion is that the declaration carries one, not that it bites —
        # the message used to claim the latter, which is false here.
        assert web["region"]["shell"] > 0, "the API requires a shell on every region"
        # Rooted in the shared corner, which both members supply.
        assert web["region"]["min"][1] < thickness and web["region"]["min"][2] < thickness

    # The plate web climbs past where the base stops; the base web runs past
    # where the plate stops. Neither is inside the other's slab.
    assert plate_web["region"]["max"][2] > thickness, "never enters plate-only material"
    assert plate_web["region"]["max"][1] <= thickness, "strays outside the plate's slab"
    assert base_web["region"]["max"][1] > thickness, "never enters base-only material"
    assert base_web["region"]["max"][2] <= thickness, "strays outside the base's slab"

    # And the README's block RUNS as pasted. Substring checks cannot see a
    # missing import, and the first draft's block called `nema17.PILOT_BOSS`
    # while importing only `region` — `NameError` for anyone who copied it,
    # in the artifact this slice exists to provide (round 1 of #200's review).
    from partspec import Part as _Part
    from partspec import openscad as _openscad

    readme = (EXAMPLES / "stepper-bracket" / "README.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", readme, re.S)
    pasted = [b for b in blocks if "p.keep_out(" in b]
    assert len(pasted) == 1, "exactly one README block shows the region calls"
    subject = _Part("readme-subject", _openscad("m.scad"))
    exec(textwrap.dedent(pasted[0]), {"p": subject})  # noqa: S102 - the doc IS the test
    assert [c.kind for c in subject.checks] == ["keep_out", "keep_in", "keep_in"]
    assert 'axis="y"' in pasted[0], "the README must show the spelled-out axis"

    # And the doc blocks show the CONTRACT'S numbers. Executing a block proves
    # it runs, not that it is the example — the SKILL block could show a box
    # spanning the air outside the L and survive, and the README's could drift
    # from `spec.py` the moment THICKNESS changed (round 2 of #200's review).
    skill_doc = (
        Path(__file__).resolve().parents[1] / "skills" / "contract-authoring" / "SKILL.md"
    ).read_text()
    shipped = [c["region"] for c in report["checks"] if c["kind"] in ("keep_out", "keep_in")]
    for doc, name in ((pasted[0], "the README block"), (_region_block(skill_doc), "SKILL.md")):
        shown = _Part("doc-subject", _openscad("m.scad"))
        exec(textwrap.dedent(doc), {"p": shown})  # noqa: S102
        shown_regions = [{**c.region.to_json(), "shell": c.shell} for c in shown.checks if c.region]
        assert shown_regions == shipped, f"{name} shows regions the contract does not declare"


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
    assert len(exemplars) == 5, f"the exemplars moved; this test needs to know: {exemplars}"
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


@needs_scad_tier
@pytest.mark.parametrize(
    ("factory", "kind", "expected"),
    [
        ("interference", "volume", 24.0),
        ("seat", "area", 384.0),
        ("clearance", "empty", None),
    ],
)
def test_the_clearance_example_grades_all_three_probe_outcomes(
    tmp_path: Path, factory: str, kind: str, expected: float | None
):
    """#236: part-versus-part interference, declared with the unit of
    verification v0 has.

    Three outcomes and three measurands, and until v0.7.7 only the first of
    them graded — a sheet had no volume to measure (#238) and a null
    intersection failed its build before any claim was evaluated (#237). That
    is why #236 called the pattern a workaround that fails in both of its
    normal outcomes; both companions closed, and this is the executable form
    of the claim that they did.

    Parameterised so a regression names the outcome that broke rather than
    reporting one failure for three unrelated mechanisms.
    """
    target = f"{EXAMPLES / 'clearance' / 'spec.py'}:{factory}"
    assert main(["check", target, "--quiet", "--out", str(tmp_path)]) == 0

    report = report_of(tmp_path)
    check = next(c for c in report["checks"] if c["kind"] == kind)
    assert check["status"] == "pass"
    if expected is None:
        # `empty` is adjudicated from the build, so there is nothing to
        # measure — which is the whole of why it is not a `volume(max=0)`.
        assert check.get("measurement") is None
        assert [c["kind"] for c in report["checks"]] == ["builds", "empty"], (
            "declared alone: an empty part has no mesh for anything else to read"
        )
    else:
        assert check["measurement"]["value"] == pytest.approx(expected, abs=0.01)
        # Prose about code is how this repo has repeatedly drifted, and both
        # the README's table and `SPEC-contract.md` §9.1 quote these numbers as
        # if they were facts. They are, once a run has to agree with them.
        for doc in (
            EXAMPLES / "clearance" / "README.md",
            EXAMPLES.parent / "docs" / "SPEC-contract.md",
        ):
            assert str(expected) in doc.read_text(), f"{doc.name} quotes a stale {kind}"


@needs_scad_tier
def test_the_clearance_probes_intersect_placed_modules_rather_than_geometry():
    """The pattern's first rule, checked against the sources.

    A probe that translates a module itself has moved the part for the probe's
    benefit, and its interference number is then about the probe rather than
    about the assembly. Every pose belongs in `assembly.scad`; a probe is an
    `intersection()` of two bare module calls and nothing else.

    Written because the first draft of this example did exactly that — it
    translated `foot()` inside the probe to manufacture an overlap the
    assembly did not have.
    """
    import ast

    home = EXAMPLES / "clearance"
    for probe in ("interference", "seat", "clearance"):
        body = (home / f"{probe}.scad").read_text()
        assert "translate" not in body, f"{probe}.scad poses a part the assembly did not"
        assert body.count("intersection()") == 1

    # And every constant a claim is built from is stated by the contract, not
    # read back out of a measurement.
    spec = ast.parse((home / "spec.py").read_text())
    named = {
        n.id
        for a in ast.walk(spec)
        if isinstance(a, ast.Assign)
        for t in a.targets
        for n in ast.walk(t)
        if isinstance(n, ast.Name)
    }
    assert {"CRUSH_MIN", "CRUSH_MAX", "SEAT_BEARING_MIN"} <= named
