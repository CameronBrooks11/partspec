"""partspec lint, tier 1 (#26): engine-free, advisory, exact predicates.

The rules' documentation (docs/LINT.md) states each predicate precisely; these
tests hold the implementation to the document and the document to the
implementation — a lint whose rules drift from their stated predicates teaches
authors to fix the wrong things.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from support import needs_openscad

from partspec.cli import main
from partspec.lint import (
    FUNCTION_LINE_LIMIT,
    LINT_SCHEMA_VERSION,
    MAGIC_EXEMPT,
    MODULE_LINE_LIMIT,
    RULES,
    lint_path,
)

ROOT = Path(__file__).resolve().parents[1]
LINT_DOC = (ROOT / "docs" / "LINT.md").read_text()


# --------------------------------------------------------------------------
# rules, against their stated predicates
# --------------------------------------------------------------------------


def test_the_spacer_carries_the_documented_real_example():
    """docs/LINT.md names examples/spacer/spacer.scad:10 (`wall = 2;`) as the
    live unused-top-level finding — the audit's own chosen example."""
    findings = lint_path(ROOT / "examples" / "spacer" / "spacer.scad")
    assert [(f.rule, f.line) for f in findings] == [("scad-unused-top-level", 10)]
    assert "'wall'" in findings[0].message
    assert "requires" in findings[0].message, "the legitimate case is named in the finding"


def test_magic_numbers_flag_the_before_form_and_pass_the_after(tmp_path: Path):
    before = tmp_path / "before.scad"
    before.write_text("cube([60, 40, 4]);\n")
    rules = [f.rule for f in lint_path(before)]
    assert rules == ["scad-magic-number"] * 3

    after = tmp_path / "after.scad"
    after.write_text(
        "plate_w = 60;\nplate_d = 40;\nplate_t = 4;\n\ncube([plate_w, plate_d, plate_t]);\n"
    )
    assert lint_path(after) == []


def test_the_overshoot_idiom_is_never_magic(tmp_path: Path):
    """|value| <= 2 exemption: the -1/+2 idiom the repo's own skills teach
    must not be flagged by the repo's own lint."""
    scad = tmp_path / "m.scad"
    scad.write_text(
        "plate_t = 4;\nbore_d = 6;\n\n"
        "difference() {\n"
        "    cube([plate_t, plate_t, plate_t]);\n"
        "    translate([0, 0, -1]) cylinder(d = bore_d, h = plate_t + 2);\n"
        "}\n"
    )
    assert lint_path(scad) == []


def test_module_size_uses_its_documented_limit(tmp_path: Path):
    line = "    cube([a, a, a]);\n"
    big = tmp_path / "big.scad"
    big.write_text("a = 3;\nmodule blob() {\n" + line * (MODULE_LINE_LIMIT + 2) + "}\nblob();\n")
    assert [f.rule for f in lint_path(big)] == ["scad-module-size"]

    small = tmp_path / "small.scad"
    small.write_text("a = 3;\nmodule blob() {\n" + line * (MODULE_LINE_LIMIT - 2) + "}\nblob();\n")
    assert lint_path(small) == []


def test_python_magic_numbers_spare_defaults_and_module_constants(tmp_path: Path):
    model = tmp_path / "model.py"
    model.write_text(
        "SIZE = 40.0  # module constant: fine\n\n\n"
        "def make_part(w: float = 30.0):  # default: exactly where numbers belong\n"
        "    return Box(w, 25, SIZE)\n"
    )
    findings = lint_path(model)
    assert [(f.rule, f.line) for f in findings] == [("py-magic-number", 5)]
    assert "25" in findings[0].message


def test_python_function_size_uses_its_documented_limit(tmp_path: Path):
    body = "    x = 1\n" * (FUNCTION_LINE_LIMIT + 2)
    model = tmp_path / "model.py"
    model.write_text(f"def monolith():\n{body}    return x\n")
    assert [f.rule for f in lint_path(model)] == ["py-function-size"]


# --------------------------------------------------------------------------
# the verb
# --------------------------------------------------------------------------


def test_the_lint_verb_is_advisory_and_machine_readable(tmp_path: Path, capsys):
    scad = tmp_path / "m.scad"
    scad.write_text("cube([60, 40, 4]);\n")
    assert main(["lint", str(scad)]) == 0, "findings are data, not a verdict"

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == LINT_SCHEMA_VERSION
    assert payload["tool"]["name"] == "partspec-lint"
    assert payload["counts"] == {"files": 1, "findings": 3}
    (entry,) = payload["files"]
    assert entry["digest"].startswith("sha256:"), "identity per file (#120)"
    for finding in entry["findings"]:
        assert set(finding) == {"rule", "file", "line", "message"}
        assert finding["rule"] in RULES
    assert "scad-magic-number" in captured.err, "the console courtesy lines name the rule"


def test_duplicate_arguments_are_one_file_and_a_clean_file_is_visible(tmp_path: Path, capsys):
    """#120: the same file twice used to double counts, and a clean file was
    invisible except as a number."""
    dirty = tmp_path / "dirty.scad"
    dirty.write_text("cube([60, 40, 4]);\n")
    clean = tmp_path / "clean.scad"
    clean.write_text("a = 3;\ncube([a, a, a]);\n")
    assert main(["lint", str(dirty), str(dirty), str(clean)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"files": 2, "findings": 3}
    by_name = {Path(e["file"]).name: e for e in payload["files"]}
    assert by_name["clean.scad"]["findings"] == []
    assert by_name["clean.scad"]["digest"].startswith("sha256:")


def test_unlintable_inputs_are_usage_not_findings(tmp_path: Path, capsys):
    assert main(["lint", str(tmp_path / "absent.scad")]) == 64
    stl = tmp_path / "m.stl"
    stl.write_text("solid m\nendsolid m\n")
    assert main(["lint", str(stl)]) == 64
    assert "lint reads" in capsys.readouterr().err


def test_lint_runs_without_any_engine_import():
    """Acceptance (#26): runs without an engine installed — pinned by proving
    the import graph never touches one."""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from partspec.lint import lint_path\n"
        f"lint_path(Path({str(ROOT / 'examples' / 'spacer' / 'spacer.scad')!r}))\n"
        "assert 'trimesh' not in sys.modules, 'lint must not import the mesh tier'\n"
        "assert 'build123d' not in sys.modules\n"
        "print('engine-free ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "engine-free ok" in proc.stdout


# --------------------------------------------------------------------------
# the document and the registry hold together
# --------------------------------------------------------------------------


def test_every_rule_is_documented_with_its_limits():
    for rule in RULES:
        assert f"`{rule}`" in LINT_DOC, f"docs/LINT.md must document {rule}"
    assert f"more than {MODULE_LINE_LIMIT} lines" in LINT_DOC
    assert f"more than {FUNCTION_LINE_LIMIT} lines" in LINT_DOC
    assert f"|value| > {MAGIC_EXEMPT:g}" in LINT_DOC
    assert "advisory and never a verdict on the part" in LINT_DOC, "bullet 3, verbatim"
    assert "#118" in LINT_DOC, "the tier-2 deferral names its tracked issue"


# --------------------------------------------------------------------------
# PR #119 review reproductions
# --------------------------------------------------------------------------


def test_keyword_arguments_are_arguments(tmp_path: Path):
    """The review's blocker: build123d idiom is keyword-heavy, and the first
    draft was silent exactly there."""
    model = tmp_path / "model.py"
    model.write_text("def make_part(w: float = 30.0):\n    return Box(w, depth=40, radius=5)\n")
    values = sorted(f.message.split()[0] for f in lint_path(model))
    assert values == ["40", "5"]


def test_nested_calls_report_each_literal_once(tmp_path: Path):
    model = tmp_path / "model.py"
    model.write_text("def make_part():\n    return outer(inner(50))\n")
    assert len(lint_path(model)) == 1


def test_signs_are_kept_and_lambdas_are_private(tmp_path: Path):
    model = tmp_path / "model.py"
    model.write_text(
        "def make_part():\n    return spin(Rotation(-90, 0, 0), key=lambda v: v * 7.5)\n"
    )
    findings = lint_path(model)
    assert [f.message.split()[0] for f in findings] == ["-90"]


def test_line_numbers_survive_a_block_comment(tmp_path: Path):
    scad = tmp_path / "m.scad"
    scad.write_text("/*\n a\n header\n comment\n*/\ncube([60, 40, 4]);\n")
    assert {f.line for f in lint_path(scad)} == {6}, "the finding names the author's line"


def test_included_library_variables_are_not_the_entry_files_business(tmp_path: Path):
    (tmp_path / "lib.scad").write_text("helper = 1;\nmodule thing() { cube([helper, 1, 1]); }\n")
    entry = tmp_path / "entry.scad"
    entry.write_text("include <lib.scad>\n\nthing();\n")
    assert lint_path(entry) == []


def test_scientific_literals_match_whole(tmp_path: Path):
    scad = tmp_path / "m.scad"
    scad.write_text("d = 6;\ncylinder(h = 1e-3, d = d);\ncube([1e6, d, d]);\n")
    findings = lint_path(scad)
    assert [f.message.split()[0] for f in findings] == ["1e6"], (
        "1e-3 is 0.001 (exempt); its exponent digit is not a magic 3"
    )


def test_the_exempt_boundary_behaves(tmp_path: Path):
    scad = tmp_path / "m.scad"
    scad.write_text("cube([2, 2.5, 3]);\n")
    assert [f.message.split()[0] for f in lint_path(scad)] == ["2.5", "3"]


def test_an_unreadable_file_is_unlintable_not_a_crash(tmp_path: Path, capsys):
    import os

    scad = tmp_path / "m.scad"
    scad.write_text("cube([3, 3, 3]);\n")
    os.chmod(scad, 0)
    try:
        assert main(["lint", str(scad)]) == 64
        assert "cannot read" in capsys.readouterr().err
    finally:
        os.chmod(scad, 0o644)


def test_multiline_call_arguments_are_not_top_level_variables(tmp_path: Path):
    """Re-review N1: a brace-only depth count mistook `d = size,` inside a
    formatted multi-line call for a top-level assignment — live on the
    open_box fixture's `points`/`faces`."""
    scad = tmp_path / "m.scad"
    scad.write_text("size = 5;\ncylinder(\n    d = size,\n    h = size\n);\n")
    assert lint_path(scad) == []
    fixture = ROOT / "tests" / "fixtures" / "open_box.scad"
    names = {
        f.message.split("'")[1] for f in lint_path(fixture) if f.rule == "scad-unused-top-level"
    }
    assert "points" not in names and "faces" not in names


def test_a_slash_slash_inside_a_string_is_not_a_comment(tmp_path: Path):
    """Re-review N2: regex ordering let a URL in a string swallow the line —
    the engine's own docstring hazard, reintroduced and now killed."""
    scad = tmp_path / "m.scad"
    scad.write_text(
        'note = "see https://example.com/docs";\n'
        "echo(note);\n"
        "rotate([0, 0, 45]) cube([note_len(note), 3, 3]);\n"
    )
    findings = lint_path(scad)
    assert not any(f.rule == "scad-unused-top-level" for f in findings), "note IS used"
    values = {f.message.split()[0] for f in findings if f.rule == "scad-magic-number"}
    assert values == {"45", "3"}, "the literals after the string must still be seen"


# --------------------------------------------------------------------------
# tier 2 (#118): the geometry rules over the .csg tree
# --------------------------------------------------------------------------


def test_the_csg_parser_reads_the_folded_grammar():
    """Engine-free: the parser over a hand-written literal-only tree."""
    from partspec.csg import parse_csg, planes_of, volume_of

    tree = parse_csg(
        "group() {\n"
        " difference() {\n"
        "  cube(size = [40, 30, 4], center = false);\n"
        "  multmatrix([[1, 0, 0, 20], [0, 1, 0, 15], [0, 0, 1, 0], [0, 0, 0, 1]]) {\n"
        "   cylinder($fn = 48, h = 4, r1 = 3, r2 = 3, center = false);\n"
        "  }\n"
        " }\n"
        "}\n"
    )
    diff = tree[0].children[0]
    assert diff.kind == "difference"
    assert volume_of(diff.children[0]) == 40 * 30 * 4
    import math

    assert volume_of(diff.children[1]) == pytest.approx(math.pi * 9 * 4)
    shared = planes_of(diff.children[0]) & planes_of(diff.children[1])
    assert len(shared) == 2, "both cap planes coincide with the plate's faces"


@needs_openscad
def test_a_flush_cut_fires_and_the_overshoot_is_clean(tmp_path: Path, capsys):
    flush = tmp_path / "flush.scad"
    flush.write_text(
        "plate_t = 4;\nbore_d = 6;\n"
        "difference() {\n"
        "    cube([40, 30, plate_t]);\n"
        "    translate([20, 15, 0]) cylinder(d = bore_d, h = plate_t, $fn = 48);\n"
        "}\n"
    )
    assert main(["lint", str(flush)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    rules = [f["rule"] for f in entry["findings"] if f["rule"].startswith("csg-")]
    assert rules == ["csg-coincident-face", "csg-coincident-face"], (
        "a cutter with h = plate_t from z = 0 coincides on BOTH cap planes"
    )
    assert all(f["line"] == 0 for f in entry["findings"] if f["rule"].startswith("csg-")), (
        "the folded tree has no source lines; 0 is documented"
    )

    clean = tmp_path / "clean.scad"
    clean.write_text(
        "plate_t = 4;\nbore_d = 6;\n"
        "difference() {\n"
        "    cube([40, 30, plate_t]);\n"
        "    translate([20, 15, -1]) cylinder(d = bore_d, h = plate_t + 2, $fn = 48);\n"
        "}\n"
    )
    assert main(["lint", str(clean)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert not any(f["rule"].startswith("csg-") for f in entry["findings"])
    assert "unsupported" not in entry


@needs_openscad
def test_the_wrong_order_fires_on_volume(tmp_path: Path, capsys):
    scad = tmp_path / "wrong.scad"
    scad.write_text(
        "size = 4;\n"
        "difference() {\n"
        "    translate([20, 15, 1]) cylinder(d = size, h = 2, $fn = 48);\n"
        "    cube([40, 30, 8]);\n"
        "}\n"
    )
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert "csg-difference-order" in [f["rule"] for f in entry["findings"]]


@needs_openscad
def test_an_unmodelled_node_is_an_entry_never_an_absence(tmp_path: Path, capsys):
    scad = tmp_path / "hulled.scad"
    scad.write_text(
        "size = 8;\n"
        "difference() {\n"
        "    hull() { cube([size, size, size]); translate([20, 0, 0]) cube([size, size, size]); }\n"
        "    translate([4, 4, -1]) cylinder(d = 3, h = 12, $fn = 32);\n"
        "}\n"
    )
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    unsupported = {u["rule"]: u["reason"] for u in entry["unsupported"]}
    assert set(unsupported) == {"csg-difference-order", "csg-coincident-face"}
    assert "hull" in unsupported["csg-difference-order"]


def test_a_missing_engine_is_an_entry_never_an_absence(tmp_path: Path, capsys, monkeypatch):
    """Audit bullet 1's MUST, executed: tier 2 without openscad refuses per
    rule, and tier 1 still runs."""
    from partspec.engines import openscad as openscad_mod

    monkeypatch.setattr(openscad_mod, "find_executable", lambda: None)
    scad = tmp_path / "m.scad"
    scad.write_text("cube([60, 40, 4]);\n")
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert len(entry["findings"]) == 3, "tier 1 is engine-free and still ran"
    assert {u["rule"] for u in entry["unsupported"]} == {
        "csg-difference-order",
        "csg-coincident-face",
    }
    assert all("openscad is not installed" in u["reason"] for u in entry["unsupported"])
