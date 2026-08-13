"""The docs make executable claims, so they are executed.

A verification tool whose own front page overstates what it does is not a small
irony — it is the same failure it exists to prevent, and it happened: the status
line asserted the backends were unimplemented for three phases after they
shipped. A written rule did not catch that. These do.

**What belongs here is a claim that can be RUN**: the skills' worked examples
build and satisfy what they advertise, the README's example is the contract that
actually executes, the catalogue's reproducible entry reproduces. What does not
belong is a search for a phrase. `assert "five defect classes in" in README`
passes when the README says "five defect classes in 2019, all of which failed" —
it reports that a string is present, which is not the claim anyone wanted to
make. Seven such tests were deleted in #150; do not reintroduce the shape.

Nor does an enumeration belong here. The vocabulary table, the unit table,
`DIMENSIONAL_KINDS`, the backend protocol block and the exit codes are
projections of the code, and six tests used to hold those second copies in step.
They are generated now (`scripts/gen_docs.py`, enforced by `just check`), so
there is one copy and nothing to compare. If you find yourself writing a test
that reads markdown and reads code and diffs them, generate the markdown
instead.

Some of these need a CAD engine — executing a skill's build123d example means
building it — and are marked accordingly.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from support import measured, needs_scad_tier

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
README = ROOT / "README.md"
EXAMPLE = ROOT / "examples" / "spacer" / "spec.py"


def _check_calls(source: str) -> list[str]:
    """The sequence of `p.<check>(...)` calls inside `spacer()`, normalised.

    Compares the call *shape* rather than the source text, so reformatting or
    inlining a constant does not fail the test but adding, dropping or
    reordering a check does.
    """
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "spacer")
    calls = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            args = [ast.unparse(a) for a in node.args]
            kwargs = [f"{k.arg}=" for k in node.keywords]
            calls.append(f"{node.func.attr}({', '.join(args + kwargs)})")
    return calls


def _first_python_block(markdown: str) -> str:
    match = re.search(r"```python\n(.*?)```", markdown, re.S)
    assert match is not None, "the README no longer contains a python example"
    return match.group(1)


def test_the_readme_example_is_the_real_contract():
    """The front-page example must be the contract that actually runs.

    It previously showed a `bayonet_lock.scad` call that would not have worked —
    the library needs `method=`, which the example omitted. An example nobody can
    run is a claim nobody can check.
    """
    assert _check_calls(_first_python_block(README.read_text())) == _check_calls(
        EXAMPLE.read_text()
    )


def test_the_readme_console_output_matches_the_contract():
    """Every check the example declares appears in the transcript, and the tally
    agrees. `builds` is added by the tool, hence the +1."""
    readme = README.read_text()
    transcript = re.search(r"```console\n\$ partspec check.*?```", readme, re.S)
    assert transcript is not None, "the README no longer shows a check transcript"
    body = transcript.group(0)

    declared = len(_check_calls(EXAMPLE.read_text()))
    shown = len(re.findall(r"^\s+ok\s+\S+", body, re.M))
    assert shown == declared + 1, "transcript check count disagrees with the contract"
    assert f"PASS: {shown} pass" in body, "the transcript's tally disagrees with its own lines"


def _verbs_named(text: str) -> set[str]:
    """Verbs a document mentions, in either form the docs use: `partspec
    render` or a bare `` `vdiff` ``."""
    return set(re.findall(r"partspec (\w+)", text)) | set(re.findall(r"`(\w+)`", text))


def test_the_front_page_describes_the_surface_that_exists():
    """Two guards: the claim it made, and the surface it denied.

    The regression: README and AGENTS both asserted the contract API and
    geometry backends did not exist, for three phases after they shipped.

    The first guard is the negation denylist that caught it — kept, because
    substring absence pins a specific historical claim perfectly well. What
    rotted was matching RAW text: one pattern contained a hard newline at a
    wrap position, so rewrapping the paragraph silently retired it. Joining
    whitespace first fixes the actual cause, and PR #154's review proved the
    point by showing that replacing this guard with verb-derivation alone let
    the original sentence back in — a repair that was a coverage regression.

    The second guard is derivable and catches the wider failure: a front page
    describing a smaller tool than the one installed. Both documents must name
    every verb the parser serves.
    """
    import argparse

    from partspec.cli import build_parser

    subparsers = [
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert subparsers, "the CLI must still have subcommands"
    verbs = set(subparsers[0].choices)

    for doc in (README, ROOT / "AGENTS.md"):
        prose = " ".join(doc.read_text().lower().split())
        for claim in ("backends are not implemented", "nothing useful to run yet"):
            assert claim not in prose, f"{doc.name} claims {claim!r}"
        named = _verbs_named(doc.read_text()) & verbs
        assert named == verbs, f"{doc.name} does not mention: {sorted(verbs - named)}"


def test_readme_links_survive_pypi():
    """pyproject embeds README.md verbatim as the wheel's long description, so
    a repo-relative link 404s on pypi.org. Absolute blob URLs or nothing (#61).
    """
    text = README.read_text()
    # Positive invariant, not banned prefixes: `](./docs/`, a root-file link
    # (`](LICENSE)`) or a reference-style definition would evade a denylist
    # while 404ing identically. Every markdown link target must be absolute
    # or an in-page anchor.
    for target in re.findall(r"\]\(([^)]+)\)", text):
        assert re.match(r"^(https?://|#)", target), f"README link would 404 on PyPI: {target}"
    assert "<a href=" not in text
    assert not re.search(r"^\[[^\]]+\]:", text, re.MULTILINE), "reference-style link definition"


# --------------------------------------------------------------------------
# docs/FAILURE-MODES.md — the catalogue's [repo] claims are executable
#
# Only the executable one survives. Three sibling tests asserted that phrases
# appeared in the catalogue, in source comments, and in another test file
# (`assert "would be silently dropped" in engines/openscad.py`). A substring
# search cannot tell a true claim from a false one — it reports that a string
# is PRESENT — so they enforced wording, not correctness, and rewording a
# comment broke them while a wrong catalogue passed. Executing the claim is
# the only form of this that carries information.
# --------------------------------------------------------------------------


@needs_scad_tier
def test_the_hole_becomes_notch_essence_is_reproducible_here(tmp_path: Path):
    """Catalogue entry 3's [repo] claim, executed: a slot swept across the
    plate edge drops the genus while every other check holds still — the
    failure mode visual review is worst at, in eight lines of scad."""
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource

    scad = tmp_path / "plate.scad"
    scad.write_text(
        "slot_l = 20;\n"
        "difference() {\n"
        "    cube([40, 30, 4]);\n"
        "    translate([10, 12, -1]) cube([slot_l, 6, 6]);\n"
        "}\n"
    )

    def measure(slot_l: float):
        backend = MeshBackend()
        artifact = backend.build(
            OpenSCADSource(path=scad, params={"slot_l": slot_l}), tmp_path / f"o{slot_l:g}"
        )
        return backend, artifact

    backend, hole = measure(20.0)  # slot ends at x=30: an interior through-hole
    backend2, notch = measure(35.0)  # slot reaches x=45 > 40: breaches the edge

    assert measured(backend.genus(hole)).value == 1
    assert measured(backend2.genus(notch)).value == 0, (
        "the hole that reached the boundary is a notch"
    )
    for b, a in ((backend, hole), (backend2, notch)):
        assert b.watertight(a).value is True
        assert measured(b.solid_count(a)).value == 1
        assert b.bbox(a).value == (40.0, 30.0, 4.0)


# --------------------------------------------------------------------------
# skills/contract-authoring — the skill's executable claims
# --------------------------------------------------------------------------

SKILL = (ROOT / "skills" / "contract-authoring" / "SKILL.md").read_text()


def test_the_skill_names_only_real_contract_methods():
    """Every `p.method` the skill teaches must exist on Part — a skill naming
    a method that was renamed teaches a call that raises."""
    from partspec import Part

    methods = set(re.findall(r"`p\.(\w+)", SKILL)) | set(re.findall(r"^p\.(\w+)\(", SKILL, re.M))
    assert methods, "the skill must actually name methods"
    for name in methods:
        assert hasattr(Part, name), f"skill teaches p.{name}, which Part does not have"


def test_the_skills_worked_example_executes():
    """The before/after block is code an agent will paste; both halves must
    declare real checks on a real Part."""
    from partspec import Part, openscad

    blocks = re.findall(r"```python\n(.*?)```", SKILL, re.S)
    assert blocks, "the worked before/after must be a fenced python block"
    before_half, _, after_half = blocks[0].partition("# After")
    assert after_half, "the block must carry both halves, delimited by '# After'"
    for half in (before_half, after_half):
        code = "\n".join(line for line in half.splitlines() if line.startswith("p."))
        p = Part("skill-subject", openscad("m.scad", wall=2.4, bore_d=8.0, plate_y=30.0))
        exec(code, {"p": p})  # noqa: S102 - executing the doc is the point
        assert len(p.checks) == 3, "each half declares exactly three checks"
    # The AFTER half must actually be the structured form it advertises.
    assert sorted(c.kind for c in p.checks) == ["param_range", "param_range", "requires"]


def test_the_skills_pointers_resolve():
    for path in (
        "docs/PLAN.md",
        "docs/FAILURE-MODES.md",
        "docs/AGENT-CONTRACT.md",
        "examples/stepper-bracket/spec.py",
        "examples/bearing-block/claims.py",
        "examples/enclosure",
    ):
        assert path in SKILL, f"the skill must cite {path} by its full path"
        assert (ROOT / path).exists(), f"{path} is cited by the skill and must exist"


# --------------------------------------------------------------------------
# skills/openscad-authoring — the skill's examples build and mean what they say
# --------------------------------------------------------------------------

SCAD_SKILL = (ROOT / "skills" / "openscad-authoring" / "SKILL.md").read_text()


def _scad_blocks() -> dict[str, str]:
    blocks = {}
    for body in re.findall(r"```scad\n(.*?)```", SCAD_SKILL, re.S):
        first = body.splitlines()[0]
        m = re.match(r"// (rule-\d+-(?:before|after))", first)
        assert m, f"every scad block carries a rule marker, got: {first!r}"
        blocks[m.group(1)] = body
    return blocks


@needs_scad_tier
def test_the_scad_skills_examples_build_and_satisfy_their_claims(tmp_path: Path):
    """Acceptance (#22): the examples in the skill actually build and satisfy
    what they claim — executed, per rule, not asserted in prose."""
    from partspec.backend import BuildError
    from partspec.backends.mesh import MeshBackend
    from partspec.engines.openscad import OpenSCADSource

    blocks = _scad_blocks()
    assert set(blocks) >= {
        "rule-1-before",
        "rule-1-after",
        "rule-2-before",
        "rule-2-after",
        "rule-4-before",
        "rule-4-after",
        "rule-5-after",
    }
    # Rule 3's overshoot idiom is taught THROUGH the after-blocks it points
    # at; an exact-face cutter slipped every measurement (review mutation M4),
    # so the idiom itself is pinned textually.
    for name in ("rule-2-after", "rule-5-after"):
        assert "-1" in blocks[name] and "+ 2" in blocks[name], f"{name} lost the overshoot"

    def build(name: str):
        scad = tmp_path / f"{name}.scad"
        scad.write_text(blocks[name])
        backend = MeshBackend()
        return backend, backend.build(OpenSCADSource(path=scad), tmp_path / name)

    # Rule 1: both build; the after-form has drivable top-level parameters.
    for name in ("rule-1-before", "rule-1-after"):
        _, artifact = build(name)
        assert not isinstance(artifact, BuildError), name
    from partspec.engines.openscad import top_level_variables

    scad = tmp_path / "rule-1-after.scad"
    assert {"plate_w", "plate_d", "plate_t"} <= top_level_variables(scad)

    # Rule 4: pinned facets are a measurable property of the artifact — a
    # 48-gon cylinder exports exactly 50 distinct face normals; the unpinned
    # form follows $fa/$fs and must NOT equal it.
    backend4, pinned = build("rule-4-after")
    assert not isinstance(pinned, BuildError)
    assert backend4.provenance(pinned)["distinct_normals"] == 50
    backend4b, unpinned = build("rule-4-before")
    assert not isinstance(unpinned, BuildError)
    assert backend4b.provenance(unpinned)["distinct_normals"] != 50
    assert "facets" in top_level_variables(tmp_path / "rule-4-after.scad")

    # Rule 2: the fully-empty wrong order is refused by the engine itself and
    # relayed by partspec as a build failure; the right order is a genuine
    # through-hole, genus 1. (The exit-0 hazard is the PARTIAL wrong order,
    # which no fixed fixture can pin — the skill's prose carries it.)
    _, before = build("rule-2-before")
    assert isinstance(before, BuildError), "hole-minus-plate must fail as empty geometry"
    backend, after = build("rule-2-after")
    assert not isinstance(after, BuildError)
    assert measured(backend.genus(after)).value == 1
    assert backend.watertight(after).value is True

    # Rule 5: the decomposed form produces the same part as rule 2's after.
    backend5, decomposed = build("rule-5-after")
    assert not isinstance(decomposed, BuildError)
    assert measured(backend5.genus(decomposed)).value == 1
    assert measured(backend5.volume(decomposed)).value == pytest.approx(
        measured(backend.volume(after)).value, rel=1e-9
    )


# --------------------------------------------------------------------------
# skills/build123d-authoring — the skill's examples build and mean what they say
# --------------------------------------------------------------------------

BD_SKILL = (ROOT / "skills" / "build123d-authoring" / "SKILL.md").read_text()


def _bd_blocks() -> dict[str, str]:
    blocks = {}
    for body in re.findall(r"```python\n(.*?)```", BD_SKILL, re.S):
        m = re.match(r"# (bd-rule-\d+-(?:before|after))", body.splitlines()[0])
        assert m, f"every python block carries a marker: {body.splitlines()[0]!r}"
        blocks[m.group(1)] = body
    return blocks


def test_the_bd_skills_examples_build_and_satisfy_their_claims(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    import sys

    from partspec.backends.occt import OcctBackend
    from partspec.engines import pycad

    blocks = _bd_blocks()
    assert set(blocks) >= {
        "bd-rule-1-after",
        "bd-rule-2-after",
        "bd-rule-3-before",
        "bd-rule-5-after",
    }
    backend = OcctBackend("build123d")

    def factory_of(name: str):
        ns: dict = {}
        exec(blocks[name], ns)  # noqa: S102 - executing the doc is the point
        return ns["make_part"]

    # Rule 1: the factory shape builds a genuine through-bored plate, and
    # the parameters MEAN something — a hardcoded body passed this test
    # until the review's mutation showed it (PR #117, F3).
    factory = factory_of("bd-rule-1-after")
    part = pycad.adopt(factory())
    assert measured(backend.genus(part)).value == 1
    assert measured(backend.watertight(part)).value is True
    widened = pycad.adopt(factory(plate_w=50.0))
    assert measured(backend.bbox(widened)).value == (50.0, 30.0, 4.0)

    # Rule 2: the three-line adapter drives an untouched community class.
    (tmp_path / "cq_gridfinity_like.py").write_text(
        "from build123d import Box\n\n\n"
        "class GridfinityBox:\n"
        "    def __init__(self, w, d, h):\n"
        "        self.w, self.d, self.h = w, d, h\n\n"
        "    def render(self):\n"
        "        return Box(42 * self.w, 42 * self.d, 7 * self.h)\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        adapted = pycad.adopt(factory_of("bd-rule-2-after")(2, 1))
        assert measured(backend.solid_count(adapted)).value == 1
        assert measured(backend.bbox(adapted)).value == (84.0, 42.0, 21.0)
        assert "cq_gridfinity_like" in sys.modules, (
            "the adapter must DRIVE the community class, not replace it"
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("cq_gridfinity_like", None)

    # Rule 3: both selector variants build watertight — that is the trap —
    # and the chamfer measurably moved: the boss rim sheds less material
    # than the plate rim it silently abandoned.
    make = factory_of("bd-rule-3-before")
    flat, bossed = pycad.adopt(make(0.0)), pycad.adopt(make(2.0))
    for shape in (flat, bossed):
        assert measured(backend.watertight(shape)).value is True
    removed_flat = 40 * 30 * 4 - measured(backend.volume(flat)).value
    removed_bossed = (40 * 30 * 4 + 10 * 10 * 2) - measured(backend.volume(bossed)).value
    assert removed_bossed < removed_flat * 0.5, (
        "the chamfer must have silently moved to the smaller boss rim"
    )

    # Rule 5: the CadQuery factory drives the SAME kernel to the same part.
    cadquery = pytest.importorskip("cadquery", reason="cadquery extra not installed")
    assert cadquery
    cq_part = pycad.adopt(factory_of("bd-rule-5-after")())
    assert measured(backend.genus(cq_part)).value == 1
    assert measured(backend.watertight(cq_part)).value is True
    assert measured(backend.bbox(cq_part)).value == (40.0, 30.0, 4.0)


def test_every_repo_path_the_specs_cite_can_be_opened():
    """Two normative specs listed `investigations/03`, `investigations/04` and
    `DIRECTION.md` under **Backing:** — files in an unpublished survey
    workspace that no reader of this repository could open, while
    `notes/README.md` argues at length that exactly this is a loss worth
    preventing. They are vendored under `notes/survey/` now.

    Scoped to paths that look like in-repo files, so prose naming an external
    project is unaffected.
    """
    import subprocess

    # `git ls-files` needs a checkout. Without this guard the test ERRORS in an
    # unpacked sdist (`CalledProcessError`, exit 128) — and `pyproject.toml`'s
    # sdist `exclude` list argues that `tests/` ships "because a downstream
    # packager runs the suite from an sdist, and that claim only holds if the
    # suite actually passes there". It did not, from #151 until now. Same guard
    # `test_packaging.py` and `test_lint_config.py` use. Part of #150.
    if not (ROOT / ".git").exists():
        pytest.skip("asks what this checkout TRACKS; an unpacked sdist has no git")

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    pattern = re.compile(r"`((?:docs|notes|src|tests|examples|skills|evals|scripts)/[\w./-]+)`")
    missing = []
    for doc in [*sorted(DOCS.glob("*.md")), README]:
        for cited in pattern.findall(doc.read_text()):
            # Tracked, not merely present. `notes/upstream/` is a gitignored
            # vendored clone: DECISIONS cited a path inside it, the file existed
            # on the machine that vendored it, and this test passed locally and
            # failed in CI — the citation was unreachable for every reader but
            # one, which is the exact loss the test is for.
            prefix = cited.rstrip("/")
            if prefix in tracked or any(t.startswith(prefix + "/") for t in tracked):
                continue
            missing.append(f"{doc.name} -> {cited}")
    assert not missing, "cited paths no reader can open:\n  " + "\n  ".join(missing)


def shipped_markdown() -> list[Path]:
    """Every markdown file the sdist carries.

    Recursive, and derived from one list rather than three. The first version
    of this used depth-fixed globs (`skills/*/*.md`), which silently stopped
    scanning the moment anyone nested a document one level deeper — a hole in a
    test whose whole job is noticing unreachable references (PR #162 review,
    LOW-H).
    """
    trees = ("docs", "skills", "examples")
    found = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CHANGELOG.md"]
    for tree in trees:
        found.extend(sorted((ROOT / tree).rglob("*.md")))
    return [p for p in found if p.is_file()]


def prose_of(text: str) -> str:
    """`text` with fenced code blocks blanked out, line numbering preserved.

    A citation inside a ```sh fence is a command someone types, not a reference
    a reader follows, and a link definition inside one defines nothing. Both
    directions bit the first version of these guards: a shell example produced
    a false positive, and a definition moved into a fence let a heading render
    as literal text while the test passed (PR #162 review, LOW-D and LOW-E).

    Blanked rather than removed so reported line numbers still point at the
    right line.
    """
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def test_every_repo_url_the_docs_link_to_can_be_opened():
    """The same question as the test above, asked of absolute repo URLs.

    `notes/` stopped shipping in the sdist at #150, so the citations naming it
    dangled for anyone reading these files from PyPI rather than a checkout —
    the reader `notes/README.md` argues hardest about. They are reference-style
    links to `blob/main` now, which resolve from anywhere.

    Not a duplicate of it. The link form writes the path down TWICE — once as
    the backticked display text that test reads, once in a URL that nothing
    read — so the two copies could drift apart and only one was checked. Both
    halves need a reader: mutate the display text and the test above fails;
    mutate the URL and, before this, nothing did.

    Scans every shipped markdown surface, not just `docs/`. `skills/`,
    `examples/`, `AGENTS.md` and `CHANGELOG.md` all ride in the sdist for the
    same reason `docs/` does, and no test looked at any of them (PR #162
    review, MEDIUM-1).
    """
    import subprocess

    if not (ROOT / ".git").exists():
        pytest.skip("asks what this checkout TRACKS; an unpacked sdist has no git")

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    url = re.compile(r"https://github\.com/CameronBrooks11/partspec/(?:blob|tree)/main/([\w./-]+)")
    missing = []
    for doc in shipped_markdown():
        for cited in url.findall(prose_of(doc.read_text())):
            prefix = cited.rstrip("/")
            if prefix in tracked or any(t.startswith(prefix + "/") for t in tracked):
                continue
            missing.append(f"{doc.relative_to(ROOT)} -> {cited}")
    assert not missing, "linked paths no reader can open:\n  " + "\n  ".join(missing)


def test_no_shipped_doc_cites_a_non_shipping_file_as_a_bare_path():
    """The defect the two tests above do not catch, stated directly.

    Both of them ask "is this path tracked?". Nothing asked "does it ship?" —
    and `notes/` and `evals/` are tracked *and* excluded from the sdist, so a
    bare `` `notes/GAPS.md` `` passes both while being unopenable for every
    reader who came from PyPI. That is the whole of #162, and it survived one
    line away from the citations that were fixed (`AGENTS.md`, PR #162 review
    HIGH-2).

    A citation of an excluded tree must therefore be a LINK, which resolves
    from anywhere. Bare directory mentions (`` `notes/` ``) and prose naming
    the tree are unaffected: this matches paths that name a file.

    The excluded trees are read from `pyproject.toml` rather than listed here,
    so shipping `notes/` again — or excluding a new tree — moves this test
    with the packaging rather than leaving it asserting last year's layout.

    A directory exclude is one with no dot in it. That heuristic would stop
    policing a dotted directory silently, so `assert trees` at least refuses to
    pass vacuously if the whole list ever becomes dotted.
    """
    import tomllib

    excludes = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"
    ]["sdist"]["exclude"]
    # `re.escape`, because these are packaging globs, not a regex the author of
    # this test controls: `notes/**` compiled straight in raises "multiple
    # repeat" and fails the suite with an unrelated message (review LOW-G).
    trees = sorted(
        re.escape(e.strip("/").rstrip("*").rstrip("/")) for e in excludes if "." not in e
    )
    assert trees, "no excluded trees in the sdist config; this test has nothing to police"

    cite = re.compile(r"`((?:" + "|".join(trees) + r")/[\w./-]*\.\w+)`")
    # `[`path`][label]` and `[`path`](url)` are links; a lone code span is not.
    # Whitespace is allowed between the two halves of a reference link because
    # CommonMark allows it and this repo hard-wraps at ~90 columns, so a wrap
    # landing there is a matter of time — and it would have failed the suite
    # with a wrong diagnosis (review LOW-C).
    closes = re.compile(r"\s*[(\[]")
    bare = []
    for doc in shipped_markdown():
        text = prose_of(doc.read_text())
        for m in cite.finditer(text):
            after = text[m.end() : m.end() + 40]
            linked = (
                m.start() > 0
                and text[m.start() - 1] == "["
                and after.startswith("]")
                and closes.match(after[1:]) is not None
            )
            if not linked:
                line = text[: m.start()].count("\n") + 1
                bare.append(f"{doc.relative_to(ROOT)}:{line} -> {m.group(1)}")
    assert not bare, (
        "these name a file the sdist does not carry, as a bare path rather than a link, "
        "so a reader from PyPI cannot open them:\n  " + "\n  ".join(bare)
    )


def test_the_generated_doc_blocks_are_current():
    """`scripts/gen_docs.py --check`, run from the test suite.

    This is NOT the pattern the module docstring forbids. It does not read a
    doc, read the code and diff two copies — it asks whether the one copy is
    current, the same question `ruff format --check` asks. There is no second
    source of truth for it to disagree with.

    It lives here rather than only in `just check` because of where CI runs
    each. `check` is gated on `needs.changes.outputs.code == 'true'`, and that
    filter is `['**', '!**/*.md']`, so a markdown-only PR skips it and `ok`
    passes on skipped jobs. The `test` job is deliberately ungated — its comment
    says "a docs-only change can genuinely break it". Moving this enforcement
    into `check` alone would therefore have let exactly the change it polices
    through: hand-editing a generated table in `docs/SPEC-contract.md`, touching
    no other file, merges green. Found in PR #156's review; the six tests this
    machinery replaced all ran in the ungated job, so this restores the coverage
    rather than adding new.
    """
    import subprocess
    import sys

    # Asserted, not skipped. A skip here would be silent in the one place it
    # matters: `scripts/` is in the sdist today, and a later tarball-shrinking
    # PR that excluded it would leave this test reporting a reassuring SKIP
    # rather than a failure. `test_the_sdist_carries_everything_the_suite_reads`
    # names this path for the same reason, so the two hold each other up
    # (PR #156 review, finding B).
    script = ROOT / "scripts" / "gen_docs.py"
    assert script.exists(), (
        f"{script} is missing, so nothing here checks the generated doc blocks. "
        "If the sdist stopped shipping scripts/, that is the bug."
    )
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "a generated doc block is stale or misplaced; run `just fmt`.\n"
        f"{result.stdout}{result.stderr}"
    )


def test_every_spec_a_diagnostic_cites_is_locatable_from_the_tool():
    """A citation an installed user cannot follow is not a citation.

    Diagnostics cite the specs by section — `(SPEC-report.md 7.1)`,
    `SPEC-contract.md 10` — and the wheel ships the package and nothing else,
    on purpose. So for anyone who installed rather than cloned, the tool names
    documents it gives no way to reach. Found by dropping an agent on a cold
    install with an objective and no other context: it went looking for
    SPEC-contract.md after the attribution advisory named it, did not find it,
    and inferred the contract API from `inspect.getdoc` instead.

    Two halves, both derived rather than matched: every spec the source names
    must exist, and `--help` must say where the specs are. Neither is a phrase
    search — the first fails on a citation to a document that does not exist,
    the second on a tool that cites documents and never locates them.
    """
    import re

    cited = {
        m.group(0)
        for path in (ROOT / "src" / "partspec").rglob("*.py")
        for m in re.finditer(r"SPEC-[a-z]+\.md", path.read_text())
    }
    assert cited, "no spec citations at all — this guard has lost its subject"
    missing = sorted(name for name in cited if not (DOCS / name).exists())
    assert not missing, f"diagnostics cite specs that do not exist: {missing}"

    from partspec.cli import build_parser

    epilog = build_parser().epilog or ""
    assert "docs" in epilog, (
        "the CLI cites specs by section but never says where they live; an "
        "installed user has no docs/ directory to look in"
    )


def test_every_engine_factory_documents_how_it_finds_the_part():
    """`openscad` had a docstring; `build123d` and `cadquery` had none.

    Those two are the entry point for both Python engines, and the thing they
    do not say is the thing that bites: partspec calls a NAMED CALLABLE,
    defaulting to `make_part`, with the contract's params as keyword
    arguments. An agent evaluating a CadQuery library assumed CQGI's
    module-level `result` — the convention that library's own shims use — and
    was corrected only by the build failing.

    Scoped to the property, not to the two functions that were missing one: a
    fourth engine added tomorrow is covered without touching this test. That
    is the lesson of the `--no-config` guard, which searched the justfile
    because the justfile is where its bug was found, and so missed the same
    bug in the release workflow.
    """
    import inspect

    import partspec
    from partspec.contract import Source

    # `isfunction` first: `__all__` also carries exception classes, and
    # `inspect.signature` raises outright on some builtin types.
    factories = {
        name: obj
        for name in partspec.__all__
        if inspect.isfunction(obj := getattr(partspec, name))
        and inspect.signature(obj).return_annotation in (Source, "Source")
    }
    assert len(factories) >= 3, f"expected one factory per engine, found {sorted(factories)}"
    undocumented = sorted(name for name, obj in factories.items() if not inspect.getdoc(obj))
    assert not undocumented, (
        f"engine factories with no docstring: {undocumented} — `inspect.getdoc` is "
        "where an installed user learns the API, because the wheel ships no docs"
    )


@needs_scad_tier
def test_the_readme_console_block_is_what_the_console_prints():
    """The front page quotes a run. The run must still say that.

    `test_the_readme_example_is_the_real_contract` compares the *contract*
    shape and never looks at the transcript below it, so the quoted output
    drifted the moment a message changed — which is exactly what happened when
    the attribution advisory gained its escape hatch: the README went on
    showing the previous sentence, and nothing failed.

    This is not a phrase search. The phrases come from the README and the
    assertion is that the tool PRODUCES them — an executable claim about the
    front page, which is what this module is for. Path and version lines are
    skipped because they are environment, not claim.
    """
    import subprocess
    import sys

    block = re.search(
        r"```console\n\$ (partspec check examples/spacer/spec\.py:spacer)\n(.*?)```",
        README.read_text(),
        re.S,
    )
    assert block is not None, "the README no longer shows a spacer run"

    result = subprocess.run(
        [sys.executable, "-m", "partspec", *block.group(1).split()[1:]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    actual = result.stdout + result.stderr
    quoted = [
        line.strip() for line in block.group(2).splitlines() if line.strip() and "/" not in line
    ]
    assert quoted, "nothing quoted to check"
    missing = [line for line in quoted if line not in actual]
    assert not missing, (
        "the README quotes console output the tool no longer prints:\n  "
        + "\n  ".join(missing)
        + f"\n--- actual ---\n{actual}"
    )
