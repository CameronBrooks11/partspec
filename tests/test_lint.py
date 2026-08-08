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
    for finding in payload["findings"]:
        assert set(finding) == {"rule", "file", "line", "message"}
        assert finding["rule"] in RULES
    assert "scad-magic-number" in captured.err, "the console courtesy lines name the rule"


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
