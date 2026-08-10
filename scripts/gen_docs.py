#!/usr/bin/env python3
"""Generate the mechanical blocks in the docs from the code they describe.

Why this exists rather than a test
----------------------------------
Six tests used to assert that markdown tables agreed with the code: the
vocabulary table, `DIMENSIONAL_KINDS`, the unit table, the backend protocol
block, the README's exit codes. Every one of them was a diff between two
hand-maintained copies of the same fact, and the failure mode was always the
same — a check ships, someone updates the code, the table lags, and the test
reports it *after* the drift instead of preventing it. #151 found the
vocabulary table four kinds behind, `DIMENSIONAL_KINDS` listed as seven when it
was nine, and the unit table naming three of five units.

A generator removes the second copy. The code is the source; these blocks are
rendered from it; `--check` in `just check` makes a stale block a gate failure
with the exact command to fix it.

What is NOT generated
---------------------
Prose. `docs/SPEC-*.md` are normative (AGENTS.md): the spec is the source of
truth for behaviour and the code implements it, so generating a spec wholesale
would invert that — a generated spec can never say the code is wrong. What is
generated is only the mechanical enumerations *inside* the prose, the parts that
are a projection of the code by definition and carry no judgement: which methods
exist, which kind each emits, which tier answers it. The arguments around them
stay hand-written and stay normative.

Usage:
    scripts/gen_docs.py            # rewrite the blocks in place
    scripts/gen_docs.py --check    # exit 1 if any block is stale (CI)
"""

from __future__ import annotations

import argparse
import ast
import inspect
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from partspec import backend, contract  # noqa: E402
from partspec.backends import mesh, occt  # noqa: E402
from partspec.status import EXIT_USAGE, Verdict, exit_code  # noqa: E402

BEGIN = "<!-- BEGIN GENERATED: {name} -->"
END = "<!-- END GENERATED: {name} -->"

# The parameter phase, which has no `GEOMETRY_KINDS` to enumerate it: two
# methods, and `_assert_vocabulary_is_complete` fails if a third appears.
_PARAMETER_PHASE = (("requires", "requires"), ("param", "param_range"))


def _assert_vocabulary_is_complete() -> None:
    """Every public `Part` method lands in exactly one table, and every kind has
    a measurand.

    This is the property `test_the_vocabulary_table_lists_every_check_an_author
    _can_declare` used to assert against the markdown, moved to where it can
    prevent the drift rather than report it: a check added without a table row
    now fails the gate at generation, and the table it would have been missing
    from does not exist as a separate artifact to be missing from.

    An assertion rather than a silent skip because the failure this replaces was
    exactly a silent one — §4.2 sat four kinds behind its own file (#151).
    """
    declared = {name for name in dir(contract.Part) if not name.startswith("_")}
    covered = {m for m, _ in _PARAMETER_PHASE} | set(contract.GEOMETRY_KINDS)
    if undocumented := declared - covered:
        raise SystemExit(
            f"public Part methods no table would document: {sorted(undocumented)}\n"
            "Add the kind to GEOMETRY_KINDS and MEASURANDS, or to _PARAMETER_PHASE here."
        )
    if phantom := covered - declared:
        raise SystemExit(f"the vocabulary names methods Part does not have: {sorted(phantom)}")

    kinds = {kind for _, kind in _PARAMETER_PHASE} | set(contract.GEOMETRY_KINDS) | {"builds"}
    if unshaped := kinds - set(contract.MEASURANDS):
        raise SystemExit(f"kinds with no MEASURANDS entry: {sorted(unshaped)}")
    if orphan := set(contract.MEASURANDS) - kinds:
        raise SystemExit(f"MEASURANDS entries naming no kind: {sorted(orphan)}")


def _signature(method: str) -> str:
    """`p.envelope(max=, min=)` — the real signature, keywords only.

    Rendered from `inspect.signature` rather than written down: a renamed or
    added keyword changes this cell without anyone remembering to.
    """
    params = inspect.signature(getattr(contract.Part, method)).parameters
    parts = []
    for name, param in params.items():
        if name == "self":
            continue
        # `name=` marks a KEYWORD-ONLY parameter, which is the notation the table
        # already used — not "has a default". Rendering it as "has a default"
        # instead silently reclassified four rows whose keyword-only arguments
        # are required (`keep_out`'s `shell`, `bolt_circle`'s `count`/`bcd`,
        # `draft_angle`'s and `min_wall`'s `min`). Generation must adopt the
        # document's convention; changing what a cell MEANS is a spec edit, and
        # a spec edit is not something a formatter gets to make.
        parts.append(f"{name}=" if param.kind is inspect.Parameter.KEYWORD_ONLY else name)
    return f"`p.{method}({', '.join(parts)})`"


def _measurement_cell(kind: str) -> str:
    m = contract.MEASURANDS[kind]
    bits = [m.shape]
    # Exactness is a property OF a measurement, so a kind that carries none says
    # nothing about it: `builds` reads "none", not "none, exact".
    if m.unit is not None:
        # Unless the shape already names it: "bool-valued, `bool`" is noise in a
        # normative table.
        if m.unit not in m.shape:
            bits.append(f"`{m.unit}`")
        if m.interval:
            bits.append("**interval**")
        elif m.exact:
            bits.append("exact")
    cell = ", ".join(bits)
    return f"{cell} ({m.note})" if m.note else cell


def _tier_cell(kind: str) -> str:
    """Derived from the capability sets, never asserted.

    A kind whose primitive only OCCT declares is OCCT-only; the runner refuses
    it on the mesh tier. `keep_out`/`keep_in` compose two primitives, and both
    are on both tiers.
    """
    primitive = contract.GEOMETRY_KINDS.get(kind)
    if primitive is None:
        return "both"
    occt_only = primitive in occt.CAPABILITIES and primitive not in mesh.CAPABILITIES
    return "**occt only**" if occt_only else "both"


def render_parameter_table() -> str:
    _assert_vocabulary_is_complete()
    rows = ["| method | `kind` | shape |", "|---|---|---|"]
    for method, kind in _PARAMETER_PHASE:
        rows.append(f"| {_signature(method)} | `{kind}` | {_measurement_cell(kind)} |")
    return "\n".join(rows)


def render_geometry_table() -> str:
    _assert_vocabulary_is_complete()
    rows = ["| method | `kind` | measurement | tier |", "|---|---|---|---|"]
    rows.append(f"| *(implicit)* | `builds` | {_measurement_cell('builds')} | both |")
    # Every geometry kind's method is named after it; `_assert_vocabulary_is
    # _complete` is what makes that safe to rely on rather than assumed.
    for kind in contract.GEOMETRY_KINDS:
        rows.append(
            f"| {_signature(kind)} | `{kind}` | {_measurement_cell(kind)} | {_tier_cell(kind)} |"
        )
    return "\n".join(rows)


def render_dimensional_kinds() -> str:
    """Ordered by the vocabulary, not sorted: the set is a frozenset, and
    alphabetical order would scatter the parameter kind among the geometry ones.
    """
    order = ["param_range", *contract.GEOMETRY_KINDS]
    listed = [k for k in order if k in contract.DIMENSIONAL_KINDS]
    assert set(listed) == set(contract.DIMENSIONAL_KINDS), (
        f"DIMENSIONAL_KINDS has a kind the vocabulary does not: "
        f"{sorted(set(contract.DIMENSIONAL_KINDS) - set(listed))}"
    )
    # Wrapped to the width the surrounding prose is hand-wrapped to, so the
    # generated line does not stand out as machine output in a normative doc.
    return textwrap.fill(
        "`DIMENSIONAL_KINDS`: " + ", ".join(f"`{k}`" for k in listed),
        width=98,
        break_long_words=False,
        break_on_hyphens=False,
    )


def render_unit_table() -> str:
    """The units the tool can actually emit, each with the kinds that emit it.

    The old table's second column was hand-written prose; this derives it, so a
    new check emitting a new unit cannot leave the table describing the old set.
    """
    by_unit: dict[str, list[str]] = {}
    for kind, m in contract.MEASURANDS.items():
        if m.unit is not None:
            by_unit.setdefault(m.unit, []).append(kind)
    rows = ["| unit | emitted by |", "|---|---|"]
    for unit in ["mm", "mm2", "mm3", "deg", "count", "bool", "rel"]:
        if unit not in by_unit:
            continue
        kinds = ", ".join(f"`{k}`" for k in by_unit[unit])
        rows.append(f"| `{unit}` | {kinds} |")
    leftover = set(by_unit) - {"mm", "mm2", "mm3", "deg", "count", "bool", "rel"}
    assert not leftover, f"a unit with no row in the ordering: {sorted(leftover)}"
    return "\n".join(rows)


def render_protocol_block() -> str:
    """`GeometryBackend`'s declared surface, from the source.

    The protocol is `@runtime_checkable` and nothing calls `isinstance` against
    it, so it drifted five primitives behind the backends without one failure.
    Printing it removes the copy that drifts.

    The class docstring is stripped: it is twenty lines of implementation
    rationale, and §3's own prose already carries the normative reading. What
    the spec needs from this class is the surface — the attributes and the
    signatures — which is exactly the part that drifted.
    """
    src = inspect.getsource(backend.GeometryBackend)
    lines = src.splitlines()
    tree = ast.parse(textwrap.dedent(src))
    node = tree.body[0]
    assert isinstance(node, ast.ClassDef)
    doc = node.body[0]
    if (
        isinstance(doc, ast.Expr)
        and isinstance(doc.value, ast.Constant)
        and isinstance(doc.value.value, str)
    ):
        # `end_lineno` is 1-indexed and inclusive; drop the following blank line
        # too so the class body does not open on one.
        cut = doc.end_lineno or doc.lineno
        rest = lines[cut:]
        while rest and not rest[0].strip():
            rest.pop(0)
        lines = lines[: doc.lineno - 1] + rest
    return "```python\n" + "\n".join(lines).rstrip() + "\n```"


def render_exit_codes() -> str:
    """A COMPLETE sentence, standing alone between blank lines.

    An HTML comment at the start of a line opens a block-level HTML element in
    CommonMark, which interrupts an open paragraph. The first version of this
    block sat mid-sentence ("Exit" / marker / "codes: ..." / marker / "(`130`
    ...)"), which renders as three paragraphs on GitHub and on PyPI — where this
    file is the package's front page. A generated block has to be a whole block
    of prose, not a fragment of one.
    """
    described = {
        Verdict.PASS: "pass",
        Verdict.FAIL: "fail",
        Verdict.INCOMPLETE: "incomplete",
        Verdict.EMPTY: "empty",
        Verdict.ERROR: "error",
    }
    codes = ", ".join(f"`{exit_code(v)}` {name}" for v, name in described.items())
    return f"Exit codes: {codes}, `{EXIT_USAGE}` bad usage."


BLOCKS: dict[str, tuple[Path, object]] = {
    "vocabulary-parameter": (ROOT / "docs" / "SPEC-contract.md", render_parameter_table),
    "vocabulary-geometry": (ROOT / "docs" / "SPEC-contract.md", render_geometry_table),
    "dimensional-kinds": (ROOT / "docs" / "SPEC-contract.md", render_dimensional_kinds),
    "unit-table": (ROOT / "docs" / "SPEC-report.md", render_unit_table),
    "backend-protocol": (ROOT / "docs" / "SPEC-backend.md", render_protocol_block),
    "exit-codes": (ROOT / "README.md", render_exit_codes),
}


def _apply(text: str, name: str, body: str) -> str:
    """Replace whatever sits between the two markers.

    Index slicing, not a regex: the body can be empty (a freshly added marker
    pair), can contain the fenced code block the protocol renders, and must
    round-trip exactly. A regex for all three is harder to read than this.
    """
    begin, end = BEGIN.format(name=name), END.format(name=name)
    start = text.find(begin)
    if start == -1:
        raise SystemExit(
            f"marker for {name!r} not found. The document must contain:\n{begin}\n...\n{end}"
        )
    stop = text.find(end, start)
    if stop == -1:
        raise SystemExit(f"{name!r} opens a generated block and never closes it: {end} missing")
    return text[:start] + begin + "\n" + body + "\n" + text[stop:]


def _assert_blocks_are_isolated(path: Path, text: str) -> None:
    """A marker must sit on its own line with blank lines around the block.

    In CommonMark an HTML comment at the start of a line opens a block-level
    HTML element, which **interrupts an open paragraph**. A marker pair dropped
    mid-sentence therefore splits one paragraph into three when rendered — and
    the first version of the exit-codes block did exactly that in `README.md`,
    which is the package's front page on PyPI. It looked fine in the diff and
    fine to `--check`, because both compare source text.

    Checked rather than remembered, for the reason the whole script exists.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("<!-- BEGIN GENERATED") and i > 0 and lines[i - 1].strip():
            raise SystemExit(
                f"{path.name}:{i + 1}: a generated block opens mid-paragraph, which "
                f"renders as a paragraph break.\nPut a blank line before it.\n"
                f"  preceding line: {lines[i - 1]!r}"
            )
        if line.startswith("<!-- END GENERATED") and i + 1 < len(lines) and lines[i + 1].strip():
            raise SystemExit(
                f"{path.name}:{i + 1}: prose resumes immediately after a generated "
                f"block, which renders as a paragraph break.\nPut a blank line after it.\n"
                f"  following line: {lines[i + 1]!r}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any generated block is out of date",
    )
    args = parser.parse_args()

    wanted: dict[Path, str] = {}
    for name, (path, render) in BLOCKS.items():
        text = wanted.get(path, path.read_text())
        wanted[path] = _apply(text, name, render())  # type: ignore[operator]

    # Before writing or comparing: the placement check runs in both modes, so a
    # marker moved mid-paragraph by hand fails the gate rather than waiting to
    # be noticed on the rendered page.
    for path, text in wanted.items():
        _assert_blocks_are_isolated(path, text)

    stale = [path for path, text in wanted.items() if path.read_text() != text]
    if args.check:
        if stale:
            names = ", ".join(p.relative_to(ROOT).as_posix() for p in stale)
            print(f"generated blocks are out of date in: {names}", file=sys.stderr)
            print("run `just fmt` (or scripts/gen_docs.py) and commit the result", file=sys.stderr)
            return 1
        return 0

    for path in stale:
        path.write_text(wanted[path])
        print(f"updated {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
