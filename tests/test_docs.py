"""The README makes checkable claims, so they are checked.

A verification tool whose own front page overstates what it does is not a small
irony — it is the same failure it exists to prevent, and it happened: the status
line asserted the backends were unimplemented for three phases after they
shipped. A written rule did not catch that. These do.

Nothing here needs a CAD engine; it is all parsing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from support import measured, needs_openscad

from partspec.status import EXIT_USAGE, Verdict, exit_code

ROOT = Path(__file__).resolve().parent.parent
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


@pytest.mark.parametrize(
    ("verdict", "described"),
    [
        (Verdict.PASS, "pass"),
        (Verdict.FAIL, "fail"),
        (Verdict.INCOMPLETE, "incomplete"),
        (Verdict.EMPTY, "empty"),
        (Verdict.ERROR, "error"),
    ],
)
def test_the_readme_exit_codes_match_the_implementation(verdict: Verdict, described: str):
    """The exit codes are the machine-readable half of the product contract
    (`SPEC-report.md` §6.2), so the README's table of them must not drift."""
    line = next(ln for ln in README.read_text().splitlines() if ln.startswith("codes: `0` pass"))
    assert f"`{exit_code(verdict)}` {described}" in line


def test_the_readme_documents_the_usage_exit_code():
    assert f"`{EXIT_USAGE}` bad usage" in README.read_text()


def test_the_readme_does_not_claim_the_backends_are_unimplemented():
    """Pins the specific regression. Both README.md and AGENTS.md asserted the
    contract API and geometry backends did not exist, through P1-P5 shipping
    them."""
    for doc in (README, ROOT / "AGENTS.md"):
        text = doc.read_text().lower()
        assert "backends are\nnot" not in text, doc.name
        assert "nothing useful to run yet" not in text, doc.name


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


def test_readme_agent_claim_matches_the_convergence_record():
    """The README's agent paragraph quotes the eval result; pinned to the
    evidence so the claim cannot outlive the record (#62)."""
    import json

    data = json.loads((ROOT / "evals" / "convergence-20260807" / "results.json").read_text())
    records = data["trials"]
    assert len({t["case"] for t in records}) == 5
    assert all(t["outcome"] == "converged" and t["turns_to_converge"] == 1 for t in records)
    # "without once weakening its contract" is a claim about `gamed`, so it is
    # pinned to the counter, not inferred from convergence.
    assert data["summary"]["gamed"] == 0
    assert "five defect classes in" in README.read_text()


# --------------------------------------------------------------------------
# docs/FAILURE-MODES.md — the catalogue's [repo] claims are executable
# --------------------------------------------------------------------------

CATALOGUE = (ROOT / "docs" / "FAILURE-MODES.md").read_text()


def test_the_catalogue_names_real_in_repo_guards():
    """Entries marked [repo] point at guards this repository actually ships;
    a catalogue citing a guard that was refactored away teaches an agent to
    rely on protection that no longer exists."""
    src = ROOT / "src" / "partspec"
    assert "unbound-parameter guard" in CATALOGUE
    assert "would be silently dropped" in (src / "engines" / "openscad.py").read_text()
    assert "partspec.refs.iso15" in CATALOGUE
    assert "22.5" in (ROOT / "tests" / "test_provenance.py").read_text(), (
        "the in-repo F16 reproduction (the Ø22.5 seat) is claimed by the catalogue"
    )
    assert "ocp-guard" in CATALOGUE
    assert "ocp-guard" in (ROOT / "justfile").read_text()
    assert "non-manifold" in (src / "backends" / "mesh.py").read_text()


def test_the_catalogue_marks_every_entry_reproducible_or_corpus():
    """Acceptance (#24): findings are reproducible from the repo or clearly
    marked as needing the external corpus. Every numbered entry carries one."""
    entries = re.findall(r"^## \d+\. .+$", CATALOGUE, re.M)
    assert len(entries) == 8
    for entry in entries:
        assert "[repo]" in entry or "[corpus]" in entry, entry


@needs_openscad
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


def test_the_catalogue_cites_what_this_repo_actually_pins():
    """PR #111 re-review: load-bearing citations the earlier tests missed."""
    assert "22.5" in CATALOGUE, "entry 4's number is the finding"
    assert "test_provenance.py" in CATALOGUE
    assert "render_backend" in CATALOGUE
    assert "render_backend" in (ROOT / "src" / "partspec" / "runner.py").read_text()
    assert "#109" in CATALOGUE
    assert "dogfood-results.md" in CATALOGUE
    assert (ROOT / "notes" / "dogfood-results.md").is_file(), (
        "the raw record the catalogue cites must be frozen in-repo"
    )
    assert "test_docs.py" in CATALOGUE, "entry 3 names this file as its repro home"


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
    assert "only against a reference the model does not contain" in SKILL
    assert (
        "only against a reference the model does not contain"
        in (ROOT / "docs" / "PLAN.md").read_text()
    ), "the promoted lesson must still match its source"


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


@needs_openscad
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


def test_the_scad_skill_cites_the_catalogue_and_its_neighbours():
    """Acceptance (#22): cross-references the failure catalogue — this is also
    the skills' half of #24's deferred cross-reference box, OpenSCAD side."""
    for needle in (
        "docs/FAILURE-MODES.md",
        "entry 1",
        "entry 2",
        "entry 4",
        "entry 5",
        "skills/contract-authoring/SKILL.md",
        "PARTSPEC_OPENSCAD",
        "source_closure",
    ):
        assert needle in SCAD_SKILL, f"the skill must reference {needle}"


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


def test_the_bd_skill_cites_its_evidence_and_neighbours():
    for needle in (
        "docs/FAILURE-MODES.md",
        "entry 7",
        "entry 8",
        "engines/pycad.py",
        "skills/contract-authoring/SKILL.md",
        "skills/openscad-authoring/SKILL.md",
        "examples/bearing-block/",
        "tests/test_differential.py",
        "test_the_same_hole_contract_holds_on_cadquery",
        "ocp-guard",
        "combine=False",
        "ShapePredicate",
    ):
        assert needle in BD_SKILL, f"the skill must reference {needle}"
