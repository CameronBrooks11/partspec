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

from partspec import csg
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


def test_an_assignment_is_exempt_however_it_is_wrapped(tmp_path: Path):
    """The exemption belongs to the STATEMENT, not to one line of it.

    The rule matched `^\\s*\\w+\\s*=` per line, so an assignment spread over
    several lines — the normal formatting for a lookup table — was exempt on its
    first line and flagged on every other. Measured before the fix (v0.7.0
    pre-tag audit): the same named constant gave 0 findings on one line and 3
    across four.

    The rule's own rationale is that a magic number is *unnameable*. These are
    named, so the code was the defect rather than `docs/LINT.md`.
    """
    one_line = tmp_path / "one.scad"
    one_line.write_text("plate = [60, 40, 4];\ncube(plate);\n")
    assert lint_path(one_line) == []

    wrapped = tmp_path / "wrapped.scad"
    wrapped.write_text("plate = [\n  60, 40, 4\n];\ncube(plate);\n")
    assert lint_path(wrapped) == [], "the same constant, wrapped, is the same claim"

    # A table that IS read, so the only rule in play is the one under test —
    # an unread one also draws `scad-unused`, which is correct and beside the
    # point.
    table = tmp_path / "table.scad"
    table.write_text(
        "holes = [[10,10],\n  [30,10],\n  [30,30]];\n"
        "for (h = holes) translate(h) cube([60,40,4]);\n"
    )
    magic = [f for f in lint_path(table) if f.rule == "scad-magic-number"]
    assert len(magic) == 3, "the named table is exempt; the unnamed cube literals are not"
    assert all(f.line == 4 for f in magic), "and they are the cube's line, not the table's"


def test_a_named_argument_is_not_an_assignment_statement(tmp_path: Path):
    """`name =` INSIDE brackets exempts its own line and claims nothing about
    the next one.

    The first version of the statement-scoped exemption opened on any line
    matching `^\\s*\\w+\\s*=` and then skipped everything up to the next `;`.
    A named argument in a multi-line call matches that, so it suppressed the
    whole call: `tests/fixtures/open_box.scad`, whose `points = [` is an
    argument of `polyhedron(`, lost all 28 of its findings (PR #160 review).

    This is the third time that fixture has caught a brace-blind scan —
    `_entry_top_level`'s depth counter exists because of the first two — so
    the cases below are pinned rather than left to it.
    """
    box = Path(__file__).resolve().parent / "fixtures" / "open_box.scad"
    assert len([f for f in lint_path(box) if f.rule == "scad-magic-number"]) == 28, (
        "a named argument inside polyhedron() must not silence the call"
    )

    signature = tmp_path / "sig.scad"
    signature.write_text("module plate(\n  w = 60,\n  h = 40\n) { cube([w, h, 100]); }\n")
    magic = [f for f in lint_path(signature) if f.rule == "scad-magic-number"]
    assert [f.line for f in magic] == [4], "signature defaults are named; the 100 is not"

    call = tmp_path / "call.scad"
    call.write_text(
        "linear_extrude(\n  height = 3,\n  twist = 0)\n  polygon([[0,0],[100,0],[100,60]]);\n"
    )
    assert len([f for f in lint_path(call) if f.rule == "scad-magic-number"]) == 3

    # A module-local constant is an assignment statement too. Counting braces in
    # the depth tally made the exemption top-level-only, so a table wrapped
    # inside a module drew the findings `docs/LINT.md` says it does not. Parens
    # and brackets are the right counters: an assignment can sit at any brace
    # depth but never inside `(` or `[`, which is exactly where a named argument
    # and a signature default live (PR #160 review, R1).
    local = tmp_path / "local.scad"
    local.write_text("module plate() {\n  spec = [\n    60, 40, 400\n  ];\n  cube(spec);\n}\n")
    assert [f for f in lint_path(local) if f.rule == "scad-magic-number"] == []

    unwrapped_local = tmp_path / "local_one.scad"
    unwrapped_local.write_text("module plate() {\n  spec = [60, 40, 400];\n  cube(spec);\n}\n")
    assert [f for f in lint_path(unwrapped_local) if f.rule == "scad-magic-number"] == [], (
        "the same constant unwrapped — both must answer the same"
    )

    # An assignment that never terminates must not silence the rest of the file.
    unterminated = tmp_path / "unterminated.scad"
    unterminated.write_text("x = 5\ncube([100, 200, 300]);\n")
    assert len([f for f in lint_path(unterminated) if f.rule == "scad-magic-number"]) == 3


def test_a_signature_default_answers_the_same_on_one_line_as_on_four(tmp_path: Path):
    """The declaration line is the common form, and it was the flagged one.

    `skip` is decided from a line-leading `name =` before `depth` is advanced,
    so on a `function`/`module` header `depth` is still 0 and the paren-depth
    exemption — which the rule's own comment says covers "the named argument
    and signature-default case" — never applied. Only the continuation form
    was exempt, and only the continuation form was tested, which is how the
    bug survived (#205).
    """
    one_line = tmp_path / "one.scad"
    one_line.write_text(
        "function radius(i, r_min = 100, pitch = 5) = r_min + i * pitch;\n"
        "module post(h = 40, d = 12) { cylinder(h = h, d = d); }\n"
        "post();\n"
        "echo(radius(1));\n"
    )
    assert [f for f in lint_path(one_line) if f.rule == "scad-magic-number"] == []

    wrapped = tmp_path / "wrapped.scad"
    wrapped.write_text(
        "function radius(i,\n"
        "                r_min = 100,\n"
        "                pitch = 5) = r_min + i * pitch;\n"
        "echo(radius(1));\n"
    )
    assert [f for f in lint_path(wrapped) if f.rule == "scad-magic-number"] == [], (
        "the same defaults, wrapped, are the same claim"
    )

    # The DEFAULTS are exempt, not the line: a one-line module carries its
    # body on the header line, and the body's literals are as magic as ever.
    body = tmp_path / "body.scad"
    body.write_text("module post(h = 40) { translate([0, 0, 37.5]) cube(h); }\npost();\n")
    magic = [f for f in lint_path(body) if f.rule == "scad-magic-number"]
    assert [f.message.split()[0] for f in magic] == ["37.5"], "40 is named by `h`; 37.5 is not"

    # A named argument in a CALL is not a signature default — nothing here
    # declares `h`, so the literal stays visible.
    call = tmp_path / "call.scad"
    call.write_text("cylinder(h = 40, d = 12);\n")
    assert len([f for f in lint_path(call) if f.rule == "scad-magic-number"]) == 2


def test_a_vector_default_is_as_named_as_a_scalar_one(tmp_path: Path):
    """A size, a position and a range are all spelled `[...]` in OpenSCAD.

    The first fix exempted the offset just past `name =`, which lands on the
    `[` rather than on a number, so the single-line form kept #205's exact
    asymmetry for the most common default form there is — and the repo's own
    corpus contains no `module f(v = [` at all, so the 30-to-30 count could
    not see it (PR #209 review). A corpus delta proves nothing about a shape
    the corpus does not contain.
    """
    one_line = tmp_path / "one.scad"
    one_line.write_text(
        "module plate_a(size = [60, 40, 4]) { cube(size); }\n"
        "function f(v = [100, 200]) = v;\n"
        "plate_a();\necho(f());\n"
    )
    assert [f for f in lint_path(one_line) if f.rule == "scad-magic-number"] == []

    wrapped = tmp_path / "wrapped.scad"
    wrapped.write_text("module plate_b(\n    size = [60, 40, 4]) { cube(size); }\nplate_b();\n")
    assert [f for f in lint_path(wrapped) if f.rule == "scad-magic-number"] == [], (
        "the same vector default, wrapped, is the same claim"
    )

    # Nested groups are covered, and the walk stops at the parameter list's
    # own closing paren — the body's literals are untouched by it.
    nested = tmp_path / "nested.scad"
    nested.write_text(
        "module holes(at = [[10, 300], [30, 400]]) { cube([500, 600, 700]); }\nholes();\n"
    )
    magic = [f.message.split()[0] for f in lint_path(nested) if f.rule == "scad-magic-number"]
    assert magic == ["500", "600", "700"], "the default is named by `at`; the body's cube is not"


def test_a_subscript_index_is_structure_not_a_dimension(tmp_path: Path):
    """`type[3][0]` is a field offset into a registry row: no unit, `-D`
    cannot override it, it can never reach a `param` or a report — exactly
    like the 0/1 `MAGIC_EXEMPT` already covers by accident (#206).

    The accessor-over-a-row idiom is how OpenSCAD registries name their
    fields, so the rule fired hardest on the code that best served its own
    intent — once per accessor past the third field.
    """
    rows = tmp_path / "rows.scad"
    rows.write_text(
        "function lamp_pin_spacing(type) = type[3][0];\n"
        "function lamp_pin_d(type) = type[3][1];\n"
        "function nested(type) = type[4][2][7];\n"
        "echo(lamp_pin_spacing(0), lamp_pin_d(0), nested(0));\n"
    )
    assert [f for f in lint_path(rows) if f.rule == "scad-magic-number"] == []

    # A `[` that OPENS a vector literal is not a subscript, and a fractional
    # index is a bug either way — both stay visible.
    literals = tmp_path / "literals.scad"
    literals.write_text("cube([60, 40, 4]);\ntranslate([0, 0, 37.5]) sphere(1);\necho(v[3.5]);\n")
    magic = [f.message.split()[0] for f in lint_path(literals) if f.rule == "scad-magic-number"]
    assert magic == ["60", "40", "4", "37.5", "3.5"]

    # A KEYWORD before `[` is not a subscripted identifier. `each [100, 200]`
    # is a list-comprehension splat and `else [0, 300]` a comprehension's
    # alternative; both read as an identifier run to the scan and muted the
    # literals after them — a real magic number silenced (PR #209 review).
    keywords = tmp_path / "keywords.scad"
    keywords.write_text(
        "polygon([each [100, 200], [0, 0]]);\n"
        "polygon([for (i = [0:1]) if (i > 0) [i, i] else [0, 300]]);\n"
    )
    magic = [f.message.split()[0] for f in lint_path(keywords) if f.rule == "scad-magic-number"]
    assert magic == ["100", "200", "300"], "a splat's literals are not indices"


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
    assert f"exceeds {MODULE_LINE_LIMIT} lines" in LINT_DOC
    assert f"more than {FUNCTION_LINE_LIMIT} lines" in LINT_DOC
    assert f"|value| > {MAGIC_EXEMPT:g}" in LINT_DOC
    assert "advisory and never a verdict on the part" in LINT_DOC, "bullet 3, verbatim"
    assert "#118" in LINT_DOC, "tier 2 names its issue"


def test_the_module_size_rule_fires_exactly_where_the_doc_says(tmp_path: Path):
    """A size rule's whole claim is its boundary, and the existing test probed
    LIMIT±2 — two lines either side of the only interesting value.

    A docs audit read the rule as off by one against `py-function-size`, and
    it IS — I overrode the audit, and PR #151's review proved me wrong by
    reading the code: `scad-module-size` counts from the `module` line while
    `py-function-size` counts from `fn.body[0].lineno`, excluding the `def`.
    So a 40-line module body fires and a 60-line function body does not.
    Both frames are pinned below so neither drifts and nobody re-litigates it
    from the prose.
    """
    source = tmp_path / "m.scad"

    def findings_for(body_lines: int) -> list:
        body = "\n".join(f"  cube({i + 3});" for i in range(body_lines))
        source.write_text(f"module big() {{\n{body}\n}}\n")
        return [f for f in lint_path(source) if f.rule == "scad-module-size"]

    assert findings_for(MODULE_LINE_LIMIT - 1) == [], "a body one under the limit is silent"
    fired = findings_for(MODULE_LINE_LIMIT)
    assert fired, "a body AT the limit spans limit+1 with its header, and fires"
    assert f"spans {MODULE_LINE_LIMIT + 1} lines (limit {MODULE_LINE_LIMIT})" in fired[0].message

    # The other frame, so the asymmetry is a pinned fact rather than prose.
    py = tmp_path / "m.py"

    def python_findings(body_lines: int) -> list:
        body = "\n".join("    x = 1" for _ in range(body_lines))
        py.write_text(f"def big():\n{body}\n")
        return [f for f in lint_path(py) if f.rule == "py-function-size"]

    assert python_findings(FUNCTION_LINE_LIMIT) == [], (
        "a function body AT its limit is silent — the def line is NOT counted"
    )
    assert python_findings(FUNCTION_LINE_LIMIT + 1), "one over fires"


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
    scad = tmp_path / "m.scad"
    scad.write_text("cube([3, 3, 3]);\n")
    scad.chmod(0)
    try:
        assert main(["lint", str(scad)]) == 64
        assert "cannot read" in capsys.readouterr().err
    finally:
        scad.chmod(0o644)


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


def test_the_geometry_math_binds():
    """PR #125 review F4: five of six math mutations survived the suite.
    Engine-free pins over hand-written trees for each mutation channel."""
    import math

    from partspec.csg import parse_csg, planes_of, volume_of

    # |det| under mirroring: dropping abs() must fail here.
    mirrored = parse_csg(
        "multmatrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]) {"
        " cube(size = [5, 7, 3], center = false); }"
    )[0]
    assert volume_of(mirrored) == pytest.approx(105.0)

    # Canonical orientation: a cutter rotated 180° has flipped cap normals;
    # dropping the orientation flip must fail here.
    plate = parse_csg("cube(size = [10, 10, 4], center = false);")[0]
    flipped = parse_csg(
        "multmatrix([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 4], [0, 0, 0, 1]]) {"
        " cylinder($fn = 32, h = 4, r1 = 2, r2 = 2, center = false); }"
    )[0]
    shared = planes_of(plate) & planes_of(flipped)
    assert len(shared) == 2, "flipped caps at z=0 and z=4 must still match the plate"

    # Rounding discipline: planes 1e-6 apart are DIFFERENT (a 1e-3 round
    # would merge them and fire a false coincidence).
    near = parse_csg(
        "multmatrix([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0.000001], [0, 0, 0, 1]]) {"
        " cylinder($fn = 32, h = 4, r1 = 2, r2 = 2, center = false); }"
    )[0]
    assert not (
        planes_of(plate)
        & planes_of(near) - {p for p in planes_of(near) if p[3] == 0.0}
        & planes_of(plate)
    )
    assert (0.0, 0.0, 1.0, 4.000001) in planes_of(near)
    assert (0.0, 0.0, 1.0, 4.0) not in planes_of(near)

    assert volume_of(parse_csg("sphere($fn = 32, r = 3);")[0]) == pytest.approx(
        4 / 3 * math.pi * 27
    )


@needs_openscad
def test_order_boundary_and_nested_cutters(tmp_path: Path, capsys):
    """Equal volumes must NOT fire (kills >= for >); a difference nested in
    a CUTTER subtree must be visited (kills a walk that skips them)."""
    equal = tmp_path / "equal.scad"
    equal.write_text(
        "s = 4;\ndifference() {\n    cube([s, s, s]);\n"
        "    translate([10, 0, 0]) cube([s, s, s]);\n}\n"
    )
    assert main(["lint", str(equal)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert "csg-difference-order" not in [f["rule"] for f in entry["findings"]]

    nested = tmp_path / "nested.scad"
    nested.write_text(
        "s = 20;\n"
        "difference() {\n"
        "    cube([s, s, s]);\n"
        "    difference() {\n"
        "        translate([5, 5, 5]) cube([2, 2, 2]);\n"
        "        translate([1, 1, 1]) cube([12, 12, 12]);\n"
        "    }\n"
        "}\n"
    )
    assert main(["lint", str(nested)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert "csg-difference-order" in [f["rule"] for f in entry["findings"]], (
        "the wrong-order difference lives inside a CUTTER subtree"
    )


@needs_openscad
def test_background_modifier_geometry_is_not_the_part(tmp_path: Path, capsys):
    """PR #125 review F2: a %-ed cutter is excluded from the render — linting
    it produced confident wrong findings about geometry that is not there."""
    scad = tmp_path / "bg.scad"
    scad.write_text("s = 10;\ndifference() {\n    cube([s, s, 4]);\n    %cube([20, 20, 20]);\n}\n")
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert not any(f["rule"].startswith("csg-") for f in entry["findings"]), (
        "background geometry is debug scaffolding, not the part"
    )


def test_a_singular_transform_is_an_entry_not_a_crash(tmp_path: Path, capsys):
    """PR #125 review F1: a legal file with a zero-scale transform used to
    take down the whole payload at exit 4, tier-1 findings included."""
    from partspec.engines.openscad import find_executable

    if find_executable() is None:
        pytest.skip("openscad binary not installed")
    scad = tmp_path / "flat.scad"
    scad.write_text(
        "size = 10;\ndifference() {\n"
        "    scale([1, 1, 0.0]) cube([size, size, size]);\n"
        "    cube([4, 4, 4]);\n"
        "}\n"
    )
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert any("could not be evaluated" in u["reason"] for u in entry.get("unsupported", []))


def test_string_bearing_exports_are_refused_whole(tmp_path: Path, monkeypatch):
    """PR #125 review F3: the format does not escape string interiors, so a
    hostile label silently reshaped the parse into phantom findings.

    The guard runs on the RAW export bytes, before any parse. It used to have
    a tree-walking twin (`csg.contains_strings`) which the re-review showed
    was bypassable by hiding the string in a %-dropped statement; that twin
    was deleted in the v0.7.0 sweep and this test moved onto the real guard.
    Engine-free by faking the export, so it holds in a mesh-only environment
    where the end-to-end version can only skip.
    """
    import subprocess

    from partspec import lint as lint_module

    scad = tmp_path / "m.scad"
    scad.write_text("cube(4);\n")

    def fake_export(args, **kwargs):
        Path(args[2]).write_text('group() { text(text = "hi", size = 10); }\n')
        return subprocess.CompletedProcess(args, 0, "", "")

    # `lint_scad_tier2` does `import subprocess` inside the function, so the
    # name resolves to the real module at call time — patching its attribute
    # is what reaches the call.
    monkeypatch.setattr(subprocess, "run", fake_export)
    findings, unsupported = lint_module.lint_scad_tier2(scad, "openscad")
    assert findings == []
    assert {u["rule"] for u in unsupported} == set(lint_module.TIER2_RULES)
    assert all("string content" in u["reason"] for u in unsupported)


@needs_openscad
def test_a_string_hidden_in_dropped_geometry_still_refuses(tmp_path: Path, capsys):
    """PR #125 re-review: hiding the string vehicle inside a %-dropped
    statement bypassed the tree-level detector — the check now runs on the
    RAW text before any statement is dropped, so a quote anywhere refuses."""
    scad = tmp_path / "hidden.scad"
    scad.write_text(
        "s = 10;\n"
        '%linear_extrude(1) text("decoy");\n'
        "difference() {\n"
        "    cube([s, s, 4]);\n"
        "    translate([2, 2, -1]) cube([4, 4, 6]);\n"
        "}\n"
    )
    assert main(["lint", str(scad)]) == 0
    entry = json.loads(capsys.readouterr().out)["files"][0]
    assert not any(f["rule"].startswith("csg-") for f in entry["findings"])
    unsupported = entry.get("unsupported", [])
    assert {u["rule"] for u in unsupported} == {"csg-difference-order", "csg-coincident-face"}
    assert all("refused whole" in u["reason"] or "unreadable" in u["reason"] for u in unsupported)


# --------------------------------------------------------------------------
# volume_of must refuse a surface that encloses nothing (#289)
# --------------------------------------------------------------------------

_OPEN_BOX_FACES = [
    [0, 1, 2, 3],  # the missing lid is the point: five faces where a solid needs six
    [4, 5, 1, 0],
    [5, 6, 2, 1],
    [6, 7, 3, 2],
    [7, 4, 0, 3],
]
_BOX_POINTS = [
    [0, 0, 0],
    [10, 0, 0],
    [10, 10, 0],
    [0, 10, 0],
    [0, 0, 10],
    [10, 0, 10],
    [10, 10, 10],
    [0, 10, 10],
]


def _polyhedron(points: list, faces: list) -> csg.Node:
    return csg.Node(kind="polyhedron", kwargs={"points": points, "faces": faces})


def test_volume_of_refuses_a_polyhedron_that_encloses_nothing():
    """`tests/fixtures/open_box.scad` states the requirement in its own header:

        Every measurement library will still hand you a volume for this -- 500
        rather than 1000, computed over a surface that does not enclose
        anything -- which is the case partspec must REFUSE rather than answer.

    It was answering. A signed-tetrahedron sum has no watertightness
    precondition, so five faces of a cube returned a number, `abs()` hid the
    sign, and `csg-difference-order` reported a finding computed from it.
    `planes_of` refuses the same node honestly; this is `volume_of` catching up.
    """
    with pytest.raises(csg.CsgError) as exc:
        csg.volume_of(_polyhedron(_BOX_POINTS, _OPEN_BOX_FACES))
    assert "not closed" in str(exc.value)


def test_volume_of_still_answers_for_a_closed_polyhedron():
    """The refusal must be the unsound surface, not the node kind: `LINT.md`
    says volumes are exact for polyhedra, and for a closed one they are."""
    closed = [*_OPEN_BOX_FACES, [7, 6, 5, 4]]  # the lid, wound to match
    assert csg.volume_of(_polyhedron(_BOX_POINTS, closed)) == pytest.approx(1000.0)


def test_volume_of_refuses_a_polyhedron_wound_inconsistently():
    """Closed is not enough: the divergence sum needs consistent orientation.

    Flipping one face leaves every edge paired but two of them traversed the
    same way twice, so the surface is no longer coherently oriented and the
    signed sum stops meaning a volume.
    """
    flipped = [*_OPEN_BOX_FACES, [4, 5, 6, 7]]  # the lid, reversed
    with pytest.raises(csg.CsgError):
        csg.volume_of(_polyhedron(_BOX_POINTS, flipped))
