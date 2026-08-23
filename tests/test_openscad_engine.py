"""`engines/openscad.py`: the source model, the closure, and the build.

Split out of `test_mesh_backend.py`, which was nearly half coverage of this
module under a filename that named a different one (#153). The move is not
only tidiness: that file binds `trimesh` at import, so these tests — none of
which measures a mesh — could not run in an install without the mesh extra.
Here they do.

The markers are `needs_openscad`, and they track the BINARY, not the mesh
tier: nothing here reaches a measurement. The three tests that touch
`MeshBackend` all assert a `BuildError`, which is why they pass with no extras
installed at all.

What stays next door is what the name says: measurement of a mesh. What lives
here is everything about turning a `.scad` into an artifact — the literal, the
include closure, the invocation, and how a failure is reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import needs_openscad

from partspec.backend import BuildError
from partspec.backends.mesh import MeshBackend
from partspec.engines import openscad
from partspec.engines.openscad import OpenSCADSource, scad_literal

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def backend() -> MeshBackend:
    """Unguarded on purpose, and only safe while every consumer stops short of
    a measurement.

    This module has no `trimesh` gate — that is the point of the split. A test
    added here that drives this fixture all the way to a number will therefore
    FAIL rather than skip on `pip install partspec`, which is exactly the
    regression `support.needs_scad_tier` was written for. Mark such a test
    `needs_scad_tier`, or measure it next door in `test_mesh_backend.py`.
    """
    return MeshBackend()


# --------------------------------------------------------------------------
# scad_literal — pure, no engine
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, "10"),
        (0.2, "0.2"),
        ("pin", '"pin"'),
        (None, "undef"),
        ([1, 2, 3], "[1, 2, 3]"),
        ((1.5, "a"), '[1.5, "a"]'),
    ],
)
def test_scad_literal(value, expected):
    assert scad_literal(value) == expected


def test_bools_do_not_degrade_into_ints():
    """`bool` subclasses `int` in Python, so the obvious isinstance ordering
    silently renders True as 1. OpenSCAD then compares a number where a boolean
    was meant."""
    assert scad_literal(True) == "true"
    assert scad_literal(False) == "false"


def test_strings_are_escaped():
    assert scad_literal('a"b') == '"a\\"b"'
    assert scad_literal("a\nb") == '"a\\nb"'


def test_the_openscad_binary_can_be_pinned(monkeypatch):
    """The engine version changes the artifact, so it must be pinnable.

    Measured on a gear library: 2021.01 honours the removed `assign()` construct
    and 2026.08.01 ignores it, so the same source yields a part 35% smaller in
    every planar dimension — both exiting 0 with clean watertight meshes.

    An environment variable rather than a contract field, because which binary
    is installed is a property of the machine, not of the design.
    """
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, "/some/pinned/openscad")
    assert openscad.find_executable() == "/some/pinned/openscad"


def test_without_the_pin_the_engine_comes_from_path(monkeypatch, tmp_path: Path):
    monkeypatch.delenv(openscad.ENV_EXECUTABLE, raising=False)
    fake = tmp_path / "openscad"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert openscad.find_executable() == str(fake)


def test_no_engine_is_resolved_from_outside_the_pin_and_path(monkeypatch):
    """There is no third source, and there must not be.

    `find_executable` once preferred `~/Applications/openscad/OpenSCAD-nightly
    .AppImage` ahead of `PATH`. On the machine that had one, `which openscad`
    said 2021.01 and every render used 2026.08.01 — and F13 is the finding that
    those two build *different parts* from the same source. An engine chosen by
    a path nobody declared is the failure this function exists to prevent, so
    an empty `PATH` and no pin must resolve to nothing at all.
    """
    monkeypatch.delenv(openscad.ENV_EXECUTABLE, raising=False)
    monkeypatch.setenv("PATH", "")
    assert openscad.find_executable() is None


def test_a_broken_pin_fails_by_name_rather_than_by_traceback(monkeypatch, tmp_path: Path):
    """A typo in the pin used to raise `FileNotFoundError` out of `run()`.

    Which is the one failure mode this tool cannot have: an uncaught exception
    escapes the report machinery, so there is no artifact, no verdict and no
    exit code — just a stack trace. Every engine failure has to arrive as a
    `BuildError`, including the ones caused by the operator.
    """
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, "/nonexistent/openscad")
    result = openscad.render(OpenSCADSource(path=FIXTURES / "block_with_hole.scad"), tmp_path)
    assert isinstance(result, BuildError)
    assert "/nonexistent/openscad" in result.message
    assert openscad.ENV_EXECUTABLE in (result.hint or ""), "say where the bad path came from"


def test_unrenderable_value_is_rejected_loudly():
    with pytest.raises(TypeError):
        scad_literal({"a": 1})


# --------------------------------------------------------------------------
# the include closure — provenance, no engine needed
# --------------------------------------------------------------------------


def _scad(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_a_lone_file_is_its_own_closure(tmp_path: Path):
    entry = _scad(tmp_path, "a.scad", "cube([1,2,3]);\n")
    closure = openscad.include_closure(entry)
    assert closure.files == (entry.resolve(),)
    assert not closure.partial


def test_the_closure_is_transitive(tmp_path: Path):
    _scad(tmp_path, "c.scad", "// leaf\n")
    _scad(tmp_path, "b.scad", "use <c.scad>\n")
    entry = _scad(tmp_path, "a.scad", "include <b.scad>\n")
    assert len(openscad.include_closure(entry).files) == 3


def test_includes_resolve_against_the_including_file(tmp_path: Path):
    """OpenSCAD's actual rule, and the one that matters on real libraries: the
    path is relative to the file containing the statement, not to the entry.

    gridfinity's `src/core/cutouts.scad` says `include <standard.scad>` and means
    its own sibling. Resolving against the entry would miss it and report it
    unresolved.
    """
    _scad(tmp_path, "src/core/standard.scad", "// sibling\n")
    _scad(tmp_path, "src/core/cutouts.scad", "include <standard.scad>\n")
    entry = _scad(tmp_path, "top.scad", "use <src/core/cutouts.scad>\n")

    closure = openscad.include_closure(entry)
    assert len(closure.files) == 3
    assert not closure.unresolved


def test_a_cycle_terminates(tmp_path: Path):
    """Mutual includes are legal OpenSCAD."""
    _scad(tmp_path, "b.scad", "include <a.scad>\n")
    entry = _scad(tmp_path, "a.scad", "include <b.scad>\n")
    assert len(openscad.include_closure(entry).files) == 2


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("line comment", "// include <ghost.scad>\n"),
        ("block comment", "/* include <ghost.scad> */\n"),
        ("string literal", 'x = "include <ghost.scad>";\n'),
    ],
)
def test_a_non_include_is_not_followed(tmp_path: Path, label, body):
    """A false positive here is not harmless: the phantom would not resolve, so
    the closure would report itself partial on a file that is complete."""
    entry = _scad(tmp_path, "a.scad", body)
    closure = openscad.include_closure(entry)
    assert closure.files == (entry.resolve(),), label
    assert not closure.partial, label


def test_a_string_containing_a_slash_slash_does_not_start_a_comment(tmp_path: Path):
    """Strings have to be tracked, not merely skipped."""
    _scad(tmp_path, "b.scad", "// leaf\n")
    entry = _scad(tmp_path, "a.scad", 'url = "http://example.com";\ninclude <b.scad>\n')
    assert len(openscad.include_closure(entry).files) == 2


def test_an_unresolvable_include_is_reported_not_swallowed(tmp_path: Path):
    entry = _scad(tmp_path, "a.scad", "include <nowhere/missing.scad>\n")
    closure = openscad.include_closure(entry)
    assert closure.unresolved == ("nowhere/missing.scad",)
    assert closure.partial, "a closure missing a member must say so"


def test_external_data_makes_the_closure_partial(tmp_path: Path):
    """`import()` and `surface()` name real build inputs whose paths may be
    computed at render time, so no static reader can resolve them. Recorded
    rather than ignored — the closure must not claim to be complete when
    something it cannot see may have changed."""
    entry = _scad(tmp_path, "a.scad", 'import("part.stl");\n')
    closure = openscad.include_closure(entry)
    assert closure.reads_external_data
    assert closure.partial
    assert not closure.unresolved, "this is a different gap from a missing include"


@pytest.mark.parametrize(
    "body",
    [
        'import("part.stl");',
        'import_stl("part.stl");',
        'import_dxf("plan.dxf");',
        'import_off("part.off");',
        'surface(file = "height.dat");',
        'dxf_linear_extrude(file = "plan.dxf", height = 3);',
        'dxf_rotate_extrude(file = "plan.dxf");',
        'x = dxf_dim(file = "plan.dxf", name = "width");',
        'p = dxf_cross(file = "plan.dxf");',
        'linear_extrude(height = 3, file = "plan.dxf");',
        'rotate_extrude(file = "plan.dxf");',
        'linear_extrude(\n  height = 3,\n  file = "plan.dxf");',
    ],
)
def test_every_way_of_reading_a_file_makes_the_closure_partial(tmp_path: Path, body: str):
    """`import()` was the whole of this until an adversarial review of #187.

    `import_stl(` did not match — the pattern wanted the paren straight after
    `import` — and 2021.01, the version floor, still executes it. The closure
    called itself complete for a build that reads a file, and the
    `measure --out` guard that asks this question overwrote the file being
    read: three runs, `[30,10,10]`, `[50,10,10]`, `[70,10,10]`, all exit 0.
    Every spelling the engine honours has to answer the same way.
    """
    closure = openscad.include_closure(_scad(tmp_path, "a.scad", body + "\n"))
    assert closure.reads_external_data, body
    assert closure.partial, body


@pytest.mark.parametrize(
    "body",
    [
        "importantValue = 3;",
        "imports(3);",
        "linear_extrude(height = 3, twist = 0) polygon([[0,0],[1,0],[1,1]]);",
        "rotate_extrude($fn = 64) circle(2);",
        "module my_import(x) { cube(x); }\nmy_import(2);",
    ],
)
def test_a_name_that_merely_looks_like_a_reader_does_not_make_it_partial(tmp_path: Path, body: str):
    """The other direction, and it is not symmetric with a false negative: a
    closure that claims to be partial when it is whole makes `diff` return
    indeterminate for a comparison it could have decided. An extrude with no
    `file=` reads nothing, and `importantValue` is a variable."""
    closure = openscad.include_closure(_scad(tmp_path, "a.scad", body + "\n"))
    assert not closure.reads_external_data, body
    assert not closure.partial, body


# --------------------------------------------------------------------------
# build errors
# --------------------------------------------------------------------------


@needs_openscad
def test_missing_source_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    result = backend.build(OpenSCADSource(path=tmp_path / "nope.scad"), tmp_path)
    assert isinstance(result, BuildError)
    assert "not found" in result.message


@needs_openscad
def test_syntax_error_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    bad = tmp_path / "bad.scad"
    bad.write_text("cube([1,2,3)\n")
    result = backend.build(OpenSCADSource(path=bad), tmp_path)
    assert isinstance(result, BuildError)


@needs_openscad
def test_empty_geometry_is_a_build_error(backend: MeshBackend, tmp_path: Path):
    """OpenSCAD exits 0 on a file that produces nothing, so the artifact is
    checked rather than the exit code trusted."""
    empty = tmp_path / "empty.scad"
    empty.write_text("// nothing here\n")
    result = backend.build(OpenSCADSource(path=empty), tmp_path)
    assert isinstance(result, BuildError)


@needs_openscad
def test_a_failed_render_leaves_the_previous_artifact_untouched(tmp_path: Path):
    """The opposite of what this test asserted until #208, deliberately.

    It required that a failed render leave nothing behind, because `render`
    unlinked its target up front. What the unlink also reached was the caller's
    file, deleted for nothing — and an `.stl` beside a model may be the model's
    own `import()`. The engine now exports into a scratch directory and the
    result is moved into place only once it exists, so a compile error, a blown
    timeout or a Ctrl-C leaves whatever was there: the same guarantee
    `measure --out <file>` already gave the filename form.

    The claim the unlink actually protected — that a stale file cannot answer
    the post-render guards — is `test_a_stale_artifact_cannot_answer_the_
    post_render_guards`, which the scratch directory keeps true without it.
    """
    good = _scad(tmp_path, "part", "cube([10, 10, 10]);")
    first = openscad.render(OpenSCADSource(path=good), tmp_path / "out")
    assert isinstance(first, Path) and first.stat().st_size > 0
    before = first.read_bytes()

    broken = tmp_path / "part.scad"
    broken.write_text("this is not openscad;\n")
    second = openscad.render(OpenSCADSource(path=broken), tmp_path / "out")

    assert isinstance(second, BuildError), "premise: the second render fails"
    assert first.read_bytes() == before, "a failed render consumed the file it did not write"
    assert not [p for p in (tmp_path / "out").iterdir() if p.name.startswith(".partspec-build-")]


def test_a_stale_artifact_cannot_answer_the_post_render_guards(tmp_path: Path, monkeypatch):
    """The reason the up-front unlink existed, kept true without it.

    OpenSCAD exits 0 on some degenerate input while writing nothing, so
    `render` asks whether the artifact exists and is non-empty rather than
    trusting the exit code — questions a *previous* run's mesh at the same
    deterministic path answers just as well. Removing that mesh first was one
    way to make the questions mean what they read as; exporting into a
    directory created empty by this call is the other, and it is the one that
    does not delete the caller's data on the way (#208).

    Pinned to a stub engine rather than the real one, because the case is a
    property of `render`'s bookkeeping and not of any binary: the installed
    2021.01 exits **1** on an empty top-level object, so the branch this test
    is about is unreachable through it.
    """
    stub = tmp_path / "openscad-stub"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))

    out = tmp_path / "out"
    out.mkdir()
    (out / "part.stl").write_bytes(b"the previous run's mesh")
    source = _scad(tmp_path, "part.scad", "cube([10, 10, 10]);\n")

    result = openscad.render(OpenSCADSource(path=source), out)

    assert isinstance(result, BuildError), "an engine that wrote nothing produced nothing"
    assert "no geometry" in result.message
    assert (out / "part.stl").read_bytes() == b"the previous run's mesh"


@needs_openscad
def test_a_first_render_into_the_source_directory_is_not_refused(tmp_path: Path):
    """Rendering an external-data model beside its own source, twice.

    This pinned clause (3) of the #208 guard — `<stem>.stl` must already EXIST
    — by requiring the FIRST run to succeed and the second to be refused, on
    the ground that by then partspec's own artifact was sitting there and
    nothing on disk said whether it or an input owned the name.

    **#263 gave that ground away, and the second run now succeeds too.** The
    engine's dependency list says `imports_data.scad` read `input.stl` and
    nothing else, so `imports_data.stl` is provably not an input and refusing
    it would be refusing a question that has an answer. What the guard refuses
    is the model that really does read the derived name — the case
    `test_a_render_over_a_file_the_model_reads_is_refused` holds — and clause
    (3) survives where it is still load-bearing: an engine that writes no
    depfile cannot answer, and there the old conservative rule applies
    unchanged (the test below it).
    """
    (tmp_path / "input.stl").write_bytes(b"donor")
    source = _scad(
        tmp_path, "imports_data.scad", FIXTURES.joinpath("imports_data.scad").read_text()
    )

    for run in ("first", "second"):
        result = openscad.render(OpenSCADSource(path=source), tmp_path)
        assert isinstance(result, Path), f"{run}: {result}"
        assert result == tmp_path / "imports_data.stl"
        assert result.stat().st_size > 0
    assert (tmp_path / "input.stl").read_bytes() == b"donor"


@needs_openscad
def test_a_render_over_a_file_the_model_reads_is_refused(tmp_path: Path):
    """The exact half of #263, and the reason the loosening above is safe.

    `self_named_import.scad` imports `self_named_import.stl`, which is exactly
    the name `render` derives for its own artifact. The depfile names it by
    full resolved path, so the move into place is refused — and refused
    BEFORE the rename, so the donor is byte-identical afterwards. Rendered
    into a SUBDIRECTORY of the model's own here rather than into it, because
    that is the case #223's guard could not reach at all: its first clause
    asked whether the destination was the source's own directory, and this one
    is not.
    """
    sub = tmp_path / "sub"
    sub.mkdir()
    stl = sub / "m.stl"
    stl.write_bytes(_one_triangle_stl())
    before = stl.read_bytes()
    source = _scad(tmp_path, "m.scad", 'union() { cube([5, 5, 5]); import("sub/m.stl"); }\n')

    result = openscad.render(OpenSCADSource(path=source), sub)
    assert isinstance(result, BuildError), result
    assert "one of its own inputs" in result.message
    assert str(stl.resolve()) in result.message
    assert result.origin == "environment"
    assert stl.read_bytes() == before, "refused before the rename, so nothing moved"


@needs_openscad
def test_an_include_only_the_engine_can_find_is_still_asked_about(tmp_path: Path, monkeypatch):
    """Why the post-render guard is gated on `partial`, not on
    `reads_external_data`.

    A closure saying `reads_external_data: False` is not a promise that the
    render read no data. An `include` partspec cannot find on ITS search path
    may resolve on the engine's, and the file behind it may hold the `import()`
    partspec then never saw — so the regex answers about a file it could not
    open, which is no answer at all. Only the depfile knows.

    The divergence is real here rather than simulated: `OPENSCADPATH` is set,
    so the engine resolves `lib.scad`, and `library_path` is emptied, so
    partspec does not. partspec therefore sees an unresolved include, no
    external data, and a destination outside the model's own directory — every
    condition under which the older gate stayed silent — while the render reads
    the destination and the depfile says so.
    """
    libs = tmp_path / "libs"
    libs.mkdir()
    model = tmp_path / "model"
    sub = model / "sub"
    sub.mkdir(parents=True)
    donor = sub / "m.stl"
    donor.write_bytes(_one_triangle_stl())
    # Absolute, so no engine's rule for resolving a relative path inside an
    # INCLUDED file decides whether this test is testing anything. Which file
    # such a path resolves against is exactly the sort of thing the two
    # engines in the matrix are entitled to disagree about.
    (libs / "lib.scad").write_text(f'import("{donor}");\n')
    source = _scad(model, "m.scad", "include <lib.scad>\ncube([5, 5, 5]);\n")

    monkeypatch.setenv("OPENSCADPATH", str(libs))
    monkeypatch.setattr(openscad, "library_path", lambda: [])
    closure = openscad.include_closure(source)
    assert closure.unresolved == ("lib.scad",), closure
    assert not closure.reads_external_data, "the premise: the regex saw no import()"

    result = openscad.render(OpenSCADSource(path=source), sub)
    assert isinstance(result, BuildError), result
    assert "one of its own inputs" in result.message
    assert donor.read_bytes() == _one_triangle_stl()


@needs_openscad
def test_a_depfile_that_contradicts_the_source_is_not_an_answer(tmp_path: Path):
    """F13 arriving in a guard, and why a complete depfile is not enough.

    `import_stl()` is deprecated: 2021.01 executes it and the 2026.08.01
    snapshot ignores it, so ONE source gives a depfile naming the data file on
    one engine and omitting it on the other. Taking the second at face value
    hands back "safe to write" for a file the same contract reads on the
    machine beside it — and the first cut of #263 did exactly that, which the
    two-engine matrix caught and this machine could not have.

    Written with a branch the render never takes rather than with the
    deprecated spelling, so it is the same disagreement on **both** engines
    instead of a test that asserts one machine's answer as universal.

    The refusal is the caller's own pre-#263 answer, not a new one: a
    contradiction is treated exactly as no answer at all.
    """
    donor = tmp_path / "input.stl"
    donor.write_bytes(_one_triangle_stl())
    source = _scad(
        tmp_path,
        "m.scad",
        'if (false) { import("input.stl"); }\ncube([5, 5, 5]);\n',
    )
    closure = openscad.include_closure(source)
    assert closure.reads_external_data, "the premise: the regex sees the import"

    # Nothing to overwrite yet, so the conservative answer is to allow.
    first = openscad.render(OpenSCADSource(path=source), tmp_path)
    assert isinstance(first, Path), first

    # Now the derived name is taken, the render still reads no data, and the
    # two accounts disagree.
    second = openscad.render(OpenSCADSource(path=source), tmp_path)
    assert isinstance(second, BuildError), second
    assert "contradicts the source" in second.message
    assert donor.read_bytes() == _one_triangle_stl()


def test_an_engine_that_reports_nothing_keeps_the_conservative_refusal(tmp_path: Path, monkeypatch):
    """`refuse_unanswered`: no depfile, so #223's rule stands unchanged.

    An engine with no `-d` writes nothing for partspec to read, and `absent`
    is not "the render read nothing" (`RenderDeps`). Making the guard exact
    must not turn an unanswerable question into a pass — so where the engine
    cannot answer, the answer is the one #223 shipped: refuse when the
    destination is the model's own directory and the derived name is already
    taken, allow everything else.

    A stub engine rather than a version pin, because both engines in the CI
    matrix accept `-d` and the behaviour under test is what happens when one
    does not.
    """
    watched = tmp_path / "input.stl"
    watched.write_bytes(b"donor")
    stub = _recording_stub(tmp_path, watched)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text('union() { cube([5, 5, 5]); import("input.stl"); }\n')

    elsewhere = openscad.render(OpenSCADSource(source), tmp_path / "out")
    assert isinstance(elsewhere, Path), elsewhere

    first = openscad.render(OpenSCADSource(source), tmp_path)
    assert isinstance(first, Path), first
    second = openscad.render(OpenSCADSource(source), tmp_path)
    assert isinstance(second, BuildError), "the derived name is taken and nothing can say by what"
    assert "did not report the files it read" in second.message
    assert watched.read_bytes() == b"donor"


@needs_openscad
def test_a_model_with_a_complete_closure_renders_twice_into_its_own_directory(tmp_path: Path):
    """Clause (2) of the #208 guard: the closure must be PARTIAL.

    A model that reads no external data and resolves every include has no
    inputs partspec cannot account for, so the derived name can only be
    partspec's own artifact from the previous run. Refusing there would break
    every repeat render into a source directory — the case that costs nothing
    and is refused by nobody — and dropping the clause leaves the suite green,
    which is why this is written down.
    """
    source = _scad(tmp_path, "plain.scad", "cube([2, 3, 4]);\n")
    for run in ("first", "second"):
        result = openscad.render(OpenSCADSource(path=source), tmp_path)
        assert isinstance(result, Path), f"{run}: {result}"
        assert result == tmp_path / "plain.stl"
        assert result.stat().st_size > 0


@needs_openscad
@pytest.mark.parametrize(
    "body",
    [
        'union() { cube([5,5,5]); import("input.stl"); }',
        'names = ["input.stl"]; i = 0; union() { cube([5,5,5]); import(names[i]); }',
    ],
    ids=["literal", "computed"],
)
def test_the_engine_names_the_data_files_a_render_read(tmp_path: Path, body: str):
    """`openscad -d` answers the question `reads_external_data` cannot.

    Both output guards refused conservatively because a data path may be
    computed at render time, so no static reader can resolve it — and #226 is
    the remedy that claim implies: ask the ENGINE what it read, which is what
    `_wrote_over_an_input` does with the answer since #263. This executes
    that claim rather than asserting it in prose, on whichever binary is
    installed, which is why it is a test and not a comment. CI runs two engine
    versions (apt 2021.01 and a 2026.08.01 snapshot) and F13 is the finding
    that they differ, so a claim about engine behaviour that only ever ran on
    one of them is a claim about one machine.

    The **computed** case is the load-bearing half. A literal `import("x.stl")`
    is findable with a regex, which is roughly what `_EXTERNAL_DATA_RE` does;
    `import(names[i])` is exactly the case the bool exists to admit defeat on,
    and the deps file names it by absolute path anyway — because the engine
    reports what it opened, not what it could parse.

    Deliberately drives the binary rather than `render()`, and stays that way
    now that #226 has landed and `render()` passes `-d` itself. This is the
    ENGINE-behaviour premise the feature rests on, so it must keep failing for
    the right reason: routed through `render()` it would also fail when
    partspec's own parsing or plumbing broke, and the two are different
    findings on two different engine versions.
    """
    import subprocess

    executable = openscad.find_executable()
    assert executable is not None, "needs_openscad promised one"

    donor = _scad(tmp_path, "input.scad", "cube([3, 7, 11]);\n")
    built = openscad.render(OpenSCADSource(path=donor), tmp_path)
    assert isinstance(built, Path) and built.name == "input.stl", built

    source = _scad(tmp_path, "part.scad", f"{body}\n")
    deps = tmp_path / "part.d"
    proc = subprocess.run(
        [
            executable,
            "--export-format",
            "binstl",
            "-o",
            str(tmp_path / "part.stl"),
            "-d",
            str(deps),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert deps.is_file(), "the engine wrote no dependency file"
    assert str(built.resolve()) in deps.read_text(), (
        f"the deps file does not name the import target:\n{deps.read_text()}"
    )


def test_top_level_variables_ignores_locals_and_noise(tmp_path: Path):
    """Only depth-zero assignments are reachable by `-D`; a name inside a module
    body is a local. Comments and string interiors must not be read as
    declarations either — a false positive there re-opens the hole rather than
    merely widening it."""
    _scad(tmp_path, "lib.scad", "helper_gap = 0.2;\n")
    entry = _scad(
        tmp_path,
        "part.scad",
        "include <lib.scad>\n"
        "bore_d = 8;\n"
        "// commented = 1;\n"
        'label = "wall = 2";\n'
        "module thing(arg) { local_only = arg * 2; cube(local_only); }\n",
    )
    assert openscad.top_level_variables(entry) == {"bore_d", "label", "helper_gap"}


def test_a_parameter_binding_nothing_is_refused(tmp_path: Path):
    """`openscad("part.scad", bore_diamter=8)` -- one transposition. OpenSCAD
    accepts a `-D` that names no top-level variable and silently drops it, so the
    file's own default rendered while the report listed bore_diamter=8 under
    `params`: the artifact positively asserted a value the geometry never saw."""
    entry = _scad(tmp_path, "part.scad", "bore_d = 8;\ncube([bore_d, 10, 10]);\n")
    assert openscad.unbound_parameters(entry, {"bore_diamter": 8.0}) == ["bore_diamter"]
    assert openscad.unbound_parameters(entry, {"bore_d": 8.0}) == []


def test_special_variables_need_no_declaration(tmp_path: Path):
    """`$fn` is built in, so a file need not assign one for `-D` to take effect."""
    entry = _scad(tmp_path, "part.scad", "cube([1, 1, 1]);\n")
    assert openscad.unbound_parameters(entry, {"$fn": 180}) == []


@needs_openscad
def test_a_misspelled_parameter_fails_the_build(tmp_path: Path):
    entry = _scad(tmp_path, "part.scad", "bore_d = 8;\ncube([bore_d, 10, 10]);\n")
    result = openscad.render(
        OpenSCADSource(path=entry, params={"bore_diamter": 4.0}), tmp_path / "out"
    )
    assert isinstance(result, BuildError)
    assert "bore_diamter" in result.message
    assert "bore_d" in (result.hint or ""), "name what could have been meant"


# --------------------------------------------------------------------------
# render_views (#17) — evidence, not judgement
# --------------------------------------------------------------------------


def test_camera_framing_is_derived_from_the_bbox_and_stable():
    """The whole camera string, distance included.

    The old version asserted a prefix that stopped short of the distance
    term, then compared `_camera(bbox, view)` to itself — a pure function
    called twice with the same arguments, which no implementation can fail.
    Executed proof it hid something: changing `2.2 * diagonal` to
    `3.5 * diagonal` in `openscad._camera` left all 773 tests green, while
    `test_raster.py` deliberately pins 2.2 for the rasterizer path. Framing
    stability across the two tiers is what `vdiff` stands on, so both need
    the constant bound, not one.
    """
    import math

    bbox = ((0.0, 0.0, 0.0), (10.0, 20.0, 30.0))
    diagonal = math.dist(*bbox)
    expected_distance = max(2.2 * diagonal, 1.0)

    camera = openscad._camera(bbox, openscad.VIEWS["iso"])
    centre_and_rotation, _, distance = camera.rpartition(",")
    assert centre_and_rotation == "5.0,10.0,15.0,55.0,0.0,25.0", "centre is the bbox midpoint"
    assert float(distance) == pytest.approx(expected_distance), (
        "the framing distance is 2.2x the diagonal — the same factor test_raster pins "
        "for the rasterizer, because the two tiers must frame identically (#21)"
    )


@needs_openscad
def test_render_views_writes_the_four_views_or_refuses_naming_the_display(tmp_path: Path):
    """Both sides of the capability boundary are asserted: 2021.01 cannot
    rasterise without a display and must say so as an environment fault with
    the remedy in the hint — never a segfault read back as `exited -11`."""
    result = openscad.render_views(OpenSCADSource(FIXTURES / "block_with_hole.scad"), tmp_path)
    if isinstance(result, BuildError):
        assert result.origin == "environment"
        text = f"{result.message} {result.hint or ''}"
        assert "display" in text and "xvfb" in text
    else:
        assert set(result) == set(openscad.VIEWS)
        for path in result.values():
            data = path.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"


@needs_openscad
def test_a_consumed_part_refuses_to_render_views(tmp_path: Path):
    # The STL stage runs first precisely so this is a refusal naming the
    # defect, not four blank frames that look like a rendered part.
    gone = tmp_path / "gone.scad"
    gone.write_text("difference() { cube(10); translate([-1,-1,-1]) cube(12); }\n")
    # The failure shape is version-dependent — 2026.08 exits 1 on an empty STL
    # export, 2021.01 exits 0 writing nothing (caught by the no-geometry
    # guard) — so the claim here is the invariant: a refusal, never images.
    result = openscad.render_views(OpenSCADSource(gone), tmp_path / "out")
    assert isinstance(result, BuildError)


def _one_triangle_stl() -> bytes:
    """The smallest binary STL `_stl_bbox` can frame a camera from."""
    import struct

    facet = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
    return b"\0" * 80 + struct.pack("<I", 1) + facet


def _recording_stub(
    tmp_path: Path, watched: Path, *, fail_from: int | None = None, reads_watched: bool = False
) -> Path:
    """An engine that writes to `-o` and reports what `watched` held when it ran.

    A stub rather than the binary because the claim is about what the engine
    was ALLOWED TO SEE, and the real openscad cannot be asked. `fail_from`
    makes the Nth invocation (1-based) exit non-zero without writing.

    `reads_watched` makes it honour `-d` and declare `watched` as an input,
    which is what a real engine does for a `surface(file = ...)` target. A
    stub is the only way to exercise the view guard at all: PNG rendering
    needs a display, every CI runner is headless, and the guard's whole input
    is the depfile the STL pass produced.
    """
    stl = tmp_path / "fixture.stl"
    stl.write_bytes(_one_triangle_stl())
    log = tmp_path / "witness.log"
    counter = tmp_path / "invocations"
    stub = tmp_path / "openscad-stub"
    stub.write_text(
        "#!/bin/sh\n"
        'out=""; dep=""; prev=""\n'
        'for a in "$@"; do\n'
        '  [ "$prev" = "-o" ] && out="$a"\n'
        '  [ "$prev" = "-d" ] && dep="$a"\n'
        '  prev="$a"\n'
        "done\n"
        f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "{counter}"\n'
        f'if [ -f "{watched}" ]; then cat "{watched}" >> "{log}"; '
        f'else echo GONE >> "{log}"; fi\n'
        f'echo "" >> "{log}"\n'
        + (f'[ -n "$dep" ] && echo "$out: {watched}" > "$dep"\n' if reads_watched else "")
        + (
            f'[ "$n" -ge {fail_from} ] && {{ echo "stub refuses" >&2; exit 1; }}\n'
            if fail_from
            else ""
        )
        + 'case "$out" in\n'
        f'  *.stl) cp "{stl}" "$out" ;;\n'
        '  *) printf "\\211PNG\\r\\n\\032\\n rendered" > "$out" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    return stub


def test_render_views_refuses_to_move_a_view_over_a_heightmap_the_model_reads(
    tmp_path: Path, monkeypatch
):
    """#267: #208's defect one directory down, closed with #226's own signal.

    A model reading `renders/iso.png` as a heightmap, rendered with `--out .`,
    had partspec write its own iso view over that heightmap — and from the next
    run the part IS the previous run's picture. Measured on 2021.01 before this
    guard: `IMAGE_SIZE` is 800x800 and `surface()` spans one unit per pixel gap,
    so `render_bbox` reads 799 in x and y, at exit 0 with nothing on stderr, on
    every run after.

    The `surface()` target is opened when the source is parsed, so the STL
    pass's own depfile already names it — no second `-d` pass over four PNG
    invocations, and no new question asked of the engine.

    **Asked of every view before any view moves**, which is the constraint the
    batched move exists for (#234): a per-view refuse-then-continue would let
    three land and the fourth refuse, leaving a directory of images from two
    different builds. Asserted here by requiring the directory to be untouched.
    """
    renders = tmp_path / "renders"
    renders.mkdir()
    watched = renders / "iso.png"
    watched.write_text("DONOR")
    stub = _recording_stub(tmp_path, watched, reads_watched=True)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))

    source = tmp_path / "m.scad"
    source.write_text('surface(file = "renders/iso.png", center = true);\n')
    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert isinstance(result, BuildError), result
    assert "view artifact" in result.message
    assert "one of its own inputs" in result.message
    assert watched.read_text() == "DONOR", "nothing moved, so the heightmap is untouched"
    assert sorted(p.name for p in renders.iterdir()) == ["iso.png"], (
        "and no other view landed either — every view is asked before any moves"
    )


def test_render_views_leaves_the_data_file_the_model_reads_intact_while_it_runs(
    tmp_path: Path, monkeypatch
):
    """#224, and the reason it is #208's defect one directory down.

    `surface(file = "...")` reads a PNG as a heightmap on both engine versions,
    so `render --out .` against a model reading `renders/iso.png` unlinked that
    heightmap before invoking the engine, then rendered and reported the part
    built without it — measured on 2021.01: first run, clean directory, exit 0,
    nothing on stderr, and all four views a different part from the one the STL
    stage had just measured correctly.

    Two claims, and the second is the one a per-view move would fail. Every
    invocation must see the donor, not merely the first: the model is re-parsed
    once per view, so moving each view into place as it finishes would let the
    front view read the iso view partspec had just written, and the four images
    would depict four different parts.
    """
    watched = tmp_path / "renders" / "iso.png"
    watched.parent.mkdir()
    watched.write_text("DONOR")
    stub = _recording_stub(tmp_path, watched)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))

    source = tmp_path / "m.scad"
    source.write_text('surface(file = "renders/iso.png", center = true);\n')
    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert not isinstance(result, BuildError), result
    # Bytes, not text: the failing history writes the stub's own PNG over the
    # donor, and decoding that would fail the test on a UnicodeDecodeError
    # instead of on the sentence below.
    seen = (tmp_path / "witness.log").read_bytes().split(b"\n")[:-1]
    assert seen == [b"DONOR"] * 5, (
        f"the engine saw {seen} — every invocation (the STL and all four views) must "
        f"find the model's own data file exactly as the caller left it"
    )


def test_a_failed_view_leaves_the_previous_renders_untouched(tmp_path: Path, monkeypatch):
    """A half-overwritten view set is a set that depicts two parts.

    `render_views` returns a `BuildError` for the whole call when any view
    fails, so a caller that finds three fresh images and one stale one beside
    them has been handed a mix nothing in the report distinguishes. The moves
    therefore happen together, after the last view exists.
    """
    watched = tmp_path / "unused"
    watched.write_text("x")
    previous = {v: (tmp_path / "renders" / f"{v}.png") for v in openscad.VIEWS}
    (tmp_path / "renders").mkdir()
    for view, path in previous.items():
        path.write_bytes(f"previous {view}".encode())

    # 1 = the STL, 2 = the iso view, 3 = the front view and the refusal.
    stub = _recording_stub(tmp_path, watched, fail_from=3)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text("cube([10, 10, 10]);\n")

    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert isinstance(result, BuildError), "premise: the third invocation fails"
    for view, path in previous.items():
        # Bytes, for the reason the donor test three functions up gives: the
        # failing history writes real PNG bytes here, and decoding them would
        # fail this test on a UnicodeDecodeError instead of on its own sentence.
        assert path.read_bytes() == f"previous {view}".encode(), (
            f"{view} was overwritten by a failed run"
        )
    assert not [p for p in (tmp_path / "renders").iterdir() if p.name.startswith(".partspec-")]


def test_a_failed_section_cut_leaves_the_previous_section_untouched(tmp_path: Path, monkeypatch):
    """The same guarantee for `render_section_stl`, which unlinked up front.

    It also no longer writes its `<stem>.section.scad` into the caller's
    directory: the cut script names the mesh it imports by resolved absolute
    path, so it relocates into the scratch directory with nothing to re-resolve.

    The `.section.scad` claim is pinned by a file the CALLER wrote at that
    name, not by the absence of one afterwards. The old code wrote its script
    there and removed it in a `finally`, so "does not exist when this returns"
    was true of the old code too and distinguished nothing (adversarial review
    of #230). What the old code did and this does not is destroy the caller's
    file — measured on the parent commit — so that is what is asserted.
    """
    stl = tmp_path / "part.stl"
    stl.write_bytes(_one_triangle_stl())
    section = tmp_path / "part.section.stl"
    section.write_text("the previous cut")
    victim = tmp_path / "part.section.scad"
    victim.write_text("// the caller's own cut script\n")

    stub = _recording_stub(tmp_path, tmp_path / "unused", fail_from=1)
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))

    result = openscad.render_section_stl(
        stl, "xy", 5.0, ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0)), tmp_path
    )

    assert isinstance(result, BuildError), "premise: the cut fails"
    assert section.read_text() == "the previous cut"
    assert victim.read_text() == "// the caller's own cut script\n", (
        "the cut script must not be written over a file of that name in the caller's directory"
    )
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".partspec-")]


# --------------------------------------------------------------------------
# _first_error_line noise filtering (#37)
# --------------------------------------------------------------------------


def test_hint_skips_cache_noise_to_the_real_diagnosis():
    # Recorded 2021.01 shape: cache statistics print FIRST, so first-wins
    # handed an agent "Geometries in cache: 1" as the reason a build failed.
    stderr = (
        "Geometries in cache: 1\n"
        "Geometry cache size in bytes: 728\n"
        "Current top level object is empty.\n"
    )
    assert openscad._first_error_line(stderr) == "Current top level object is empty."


def test_hint_skips_the_summary_block_of_a_2d_object():
    # Recorded verbatim from 2021.01 stderr for `square([10,10]);` — including
    # the block header and Contours line the first filter draft missed.
    stderr = (
        "Geometries in cache: 1\n"
        "Geometry cache size in bytes: 144\n"
        "CGAL Polyhedrons in cache: 0\n"
        "CGAL cache size in bytes: 0\n"
        "Total rendering time: 0:00:00.000\n"
        "   Top level object is a 2D object:\n"
        "   Contours:        1\n"
        "Current top level object is not a 3D object.\n"
    )
    assert openscad._first_error_line(stderr) == "Current top level object is not a 3D object."


def test_hint_stays_first_wins_on_the_backend_usage_dump():
    # Recorded 2021.01 --backend=CGAL shape: the reason first, then a long
    # usage dump. Last-wins would return a fragment of the dump — the exact
    # regression #37's acceptance pins against.
    stderr = (
        "unrecognised option '--backend=CGAL'\n"
        "Allowed options:\n"
        "  -o [ --o ] arg    output specified file\n"
        "  -D [ --D ] arg    var=val\n"
    )
    assert openscad._first_error_line(stderr) == "unrecognised option '--backend=CGAL'"


def test_hint_is_none_when_only_noise_remains():
    stderr = (
        "Geometries in cache: 1\nGeometry cache size in bytes: 728\n"
        "Vertices: 8\nHalfedges: 24\nEdges: 12\nHalffacets: 12\n"
        "Facets: 6\nVolumes: 2\nSimple: yes\nTotal rendering time: 0:00:00.01\n"
    )
    assert openscad._first_error_line(stderr) is None


@needs_openscad
def test_a_failed_build_carries_its_full_stderr(tmp_path: Path):
    flat = tmp_path / "flat.scad"
    flat.write_text("square([10, 10]);\n")
    result = openscad.render(OpenSCADSource(flat), tmp_path / "out")
    assert isinstance(result, BuildError)
    # The unabridged diagnosis rides along; the hint is never a cache statistic.
    assert result.stderr
    # The exact diagnosis, not merely "not the first noise line" — the review
    # caught the weaker assertion passing while the hint was still a block
    # header from the summary.
    assert result.hint is not None and "not a 3D object" in result.hint


# --------------------------------------------------------------------------
# method= scratch placement (#39)
# --------------------------------------------------------------------------


@needs_openscad
def test_method_render_never_touches_the_source_dir_even_read_only(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "lib.scad").write_text("module block(s = 5) { cube(s); }\n")
    src_dir.chmod(0o500)
    try:
        result = openscad.render(
            OpenSCADSource(src_dir / "lib.scad", params={"s": 8}, method="block"),
            tmp_path / "out",
        )
        leftovers = [p.name for p in src_dir.iterdir() if p.name != "lib.scad"]
    finally:
        src_dir.chmod(0o755)
    assert not isinstance(result, BuildError), result
    assert leftovers == [], "the inspector wrote into the tree it was inspecting"


@needs_openscad
def test_method_render_resolves_the_sources_relative_includes(tmp_path: Path):
    # The scratch lives in the out dir but `include <>`s the source by absolute
    # path, and OpenSCAD resolves nested includes relative to the file that
    # contains the statement — so the source's own relative include holds.
    src_dir = tmp_path / "src"
    (src_dir / "sub").mkdir(parents=True)
    (src_dir / "sub" / "size.scad").write_text("s_default = 6;\n")
    (src_dir / "lib.scad").write_text(
        "include <sub/size.scad>\nmodule block(s = s_default) { cube(s); }\n"
    )
    result = openscad.render(OpenSCADSource(src_dir / "lib.scad", method="block"), tmp_path / "out")
    assert not isinstance(result, BuildError), result


@needs_openscad
def test_an_unwritable_out_dir_refuses_naming_the_directory(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o500)
    try:
        result = openscad.render(
            OpenSCADSource(FIXTURES / "block_with_hole.scad", method="nope"), out
        )
    finally:
        out.chmod(0o755)
    assert isinstance(result, BuildError)
    assert result.origin == "environment"
    assert str(out) in result.message


@needs_openscad
def test_method_render_still_resolves_relative_data_files(tmp_path: Path):
    # The regression the adversarial review caught live: surface()/import()
    # data resolves against the MAIN entry's directory, so these sources keep
    # their scratch entry beside the source instead of in the out dir.
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "data.dat").write_text("1 1\n1 1\n")
    (src_dir / "lib.scad").write_text('module part() { surface(file = "data.dat"); }\n')
    result = openscad.render(OpenSCADSource(src_dir / "lib.scad", method="part"), tmp_path / "out")
    assert not isinstance(result, BuildError), result
    leftovers = [p.name for p in src_dir.iterdir() if p.name.startswith(".partspec-")]
    assert leftovers == [], "the scratch beside the source must still be cleaned up"


@needs_openscad
def test_a_stale_artifact_in_an_unwritable_out_dir_refuses_by_name(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "block_with_hole.stl").write_text("stale")
    out.chmod(0o500)
    try:
        result = openscad.render(OpenSCADSource(FIXTURES / "block_with_hole.scad"), out)
    finally:
        out.chmod(0o755)
    assert isinstance(result, BuildError)
    assert result.origin == "environment"
    assert str(out) in result.message


def test_a_blocked_view_destination_is_refused_before_any_view_moves(tmp_path: Path, monkeypatch):
    """The batch move's own guarantee, which the batch alone did not give.

    Rendering all four before moving any stops the views reading each other.
    It does not make the four moves atomic, and nothing does — so a
    destination `os.replace` cannot replace left views 1-2 fresh and 3-4 stale
    under a message saying nothing was written, which is exactly the mix of two
    runs this batching exists to prevent (adversarial review of #230).

    A directory at a destination is the case that is knowable before the first
    move, so it is refused there, and the hint states the guarantee the caller
    needs: nothing was touched.
    """
    renders = tmp_path / "renders"
    renders.mkdir()
    previous = {v: renders / f"{v}.png" for v in openscad.VIEWS}
    for view, path in previous.items():
        path.write_bytes(f"previous {view}".encode())
    # `top` sorts after `iso` and `front` in VIEWS order, so an unguarded run
    # replaces two views before finding it — the partial state, not an early
    # bail that would pass this test for the wrong reason.
    previous["top"].unlink()
    previous["top"].mkdir()
    (previous["top"] / "keep").write_text("x")

    stub = _recording_stub(tmp_path, tmp_path / "unused")
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text("cube([10, 10, 10]);\n")

    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert isinstance(result, BuildError), "premise: the blocked destination refuses"
    assert result.origin == "environment"
    assert "is a directory" in result.message and "top.png" in result.message
    assert "nothing in the output directory has been touched" in (result.hint or "")
    for view, path in previous.items():
        if view == "top":
            continue
        assert path.read_bytes() == f"previous {view}".encode(), (
            f"{view} was replaced before the refusal — the mix this refusal exists to prevent"
        )
    assert (previous["top"] / "keep").is_file(), "and the blocking directory is left alone"


def test_an_unwritable_renders_directory_is_a_named_refusal(tmp_path: Path, monkeypatch):
    """A characterisation test for behaviour #230 shipped and did not pin.

    Honest about which parent it distinguishes, because the first version of
    this docstring was not. It claimed the refusal was new here and attributed
    the old traceback to `png.parent.mkdir` or the per-view write; **it passes
    unchanged against its own parent**, which already had the `except OSError`
    clause, and neither named call site is the source (adversarial review of
    #234 — the same defect that review's own subject was written to close).

    What it really distinguishes is pre-#230, where the traceback came out of
    the per-view `png.unlink` that #230 deleted — and only when `renders/`
    already holds images, which is why this test pre-populates it. On this
    branch the refusal comes from `TemporaryDirectory(dir=renders_dir)`,
    earlier still.

    The property is worth a test either way: an unhandled exception escapes the
    report machinery entirely — no artifact, no verdict, no exit code, just a
    stack trace — which is the one failure mode this tool cannot have.
    """
    out = tmp_path / "out"
    renders = out / "renders"
    renders.mkdir(parents=True)
    # Pre-populated, so the pre-#230 `png.unlink` this characterises is
    # actually reached there. Empty, that history returns an ordinary
    # `BuildError` and the test would distinguish nothing at all.
    for view in openscad.VIEWS:
        (renders / f"{view}.png").write_bytes(b"previous")
    renders.chmod(0o500)
    stub = _recording_stub(tmp_path, tmp_path / "unused")
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text("cube([10, 10, 10]);\n")
    try:
        result = openscad.render_views(OpenSCADSource(source), out)
    finally:
        renders.chmod(0o700)

    assert isinstance(result, BuildError), "an unwritable directory is a refusal, not a traceback"
    assert result.origin == "environment", "the environment stopped this, not the part"
    assert str(renders) in result.message, "and it names the directory"
    for view in openscad.VIEWS:
        assert (renders / f"{view}.png").read_bytes() == b"previous", (
            "and the previous set is intact, since nothing could be written"
        )


def test_a_symlinked_view_destination_is_replaced_rather_than_refused(tmp_path: Path, monkeypatch):
    """`rename(2)` does not follow its destination, so a symlink is replaced
    like any other name — including one pointing at a directory.

    The pre-flight above asked `png.is_dir()`, which DOES follow symlinks, so
    it refused a render that had always worked and called the symlink a
    directory (adversarial review of #234). The target is left alone, which is
    the same guarantee `render()`'s docstring gives for the STL.
    """
    renders = tmp_path / "renders"
    renders.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep").write_text("x")
    (renders / "top.png").symlink_to(target)

    stub = _recording_stub(tmp_path, tmp_path / "unused")
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text("cube([10, 10, 10]);\n")

    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert not isinstance(result, BuildError), result
    assert not (renders / "top.png").is_symlink(), "the rename replaced the link itself"
    assert (target / "keep").is_file(), "and never wrote through it to the directory it named"


def test_a_move_that_fails_before_any_view_moves_says_nothing_was_touched(
    tmp_path: Path, monkeypatch
):
    """The `moved == 0` wording, which had none.

    "the 0 view artifact(s) already moved into ... are from this run and the
    rest are not" described a corrupted directory that was in fact untouched —
    the thesis inverted, in the branch added to stop exactly that. The CHANGELOG
    claimed this layer was pinned; it was asserted (adversarial review of #234).
    """
    renders = tmp_path / "renders"
    renders.mkdir()
    for view in openscad.VIEWS:
        (renders / f"{view}.png").write_bytes(b"previous")

    stub = _recording_stub(tmp_path, tmp_path / "unused")
    monkeypatch.setenv(openscad.ENV_EXECUTABLE, str(stub))
    source = tmp_path / "m.scad"
    source.write_text("cube([10, 10, 10]);\n")

    # Only the view moves fail, so `moved` never advances past 0. Scoped to
    # `.png` because `render()` moves the STL through the same call first, and
    # breaking that would test a different refusal entirely.
    real_replace = openscad.Path.replace

    def refuse(self, target):
        if Path(target).suffix == ".png":
            raise PermissionError(13, "Permission denied")
        return real_replace(self, target)

    monkeypatch.setattr(openscad.Path, "replace", refuse)
    result = openscad.render_views(OpenSCADSource(source), tmp_path)

    assert isinstance(result, BuildError)
    assert "no view artifact could be moved" in result.message, result.message
    assert "0 view artifact(s)" not in result.message, "a count of zero is not a count"
    assert "nothing in the output directory has been touched" in (result.hint or "")
    for view in openscad.VIEWS:
        assert (renders / f"{view}.png").read_bytes() == b"previous"


# ---------------------------------------------------------------------------
# what the engine says it read (#226)
# ---------------------------------------------------------------------------


def test_the_depfile_parser_drops_the_target_and_unescapes(tmp_path: Path):
    """Make syntax, parsed as make syntax.

    The target is not a dependency; a trailing backslash is a line continuation
    and not part of a path; and `\\ ` is one escaped space inside a single
    filename rather than a separator. Reading any of those wrong puts a path
    that does not exist into a list whose whole purpose is naming files to hash.
    """
    (tmp_path / "a b.stl").write_text("x")
    text = "out.stl: \\\n\t/abs/one.scad \\\n\t" + f"{tmp_path}/a\\ b.stl" + " \\\n\trel.scad\n"

    files = openscad._parse_depfile(text, tmp_path)

    assert Path("/abs/one.scad") in files
    assert (tmp_path / "a b.stl") in files, "an escaped space must not split a filename"
    assert (tmp_path / "rel.scad") in files, "relative entries resolve against the render cwd"
    assert not any("out.stl" in str(f) for f in files), "the target is not a dependency"


@needs_openscad
def test_a_render_reports_the_data_files_no_static_reader_can_find(tmp_path: Path):
    """The whole point of #226, end to end through `render()`.

    A **computed** `import(names[0])` and a `surface(file = ...)` are precisely
    what `Closure.reads_external_data` exists to admit defeat on. The engine
    resolves both and says so, for one extra argument.
    """
    donor = _scad(tmp_path, "input.scad", "cube([3, 7, 11]);\n")
    stl = openscad.render(OpenSCADSource(path=donor), tmp_path)
    assert isinstance(stl, Path), stl
    heights = tmp_path / "heights.dat"
    heights.write_text("5 5 5\n5 5 5\n")

    source = _scad(
        tmp_path,
        "part.scad",
        'names = ["input.stl"];\nimport(names[0]);\nsurface(file = "heights.dat");\n',
    )
    deps: list[openscad.RenderDeps] = []
    built = openscad.render(OpenSCADSource(path=source), tmp_path, deps_out=deps)
    assert isinstance(built, Path), built

    assert len(deps) == 1
    assert deps[0].state == "complete"
    assert stl.resolve() in deps[0].files, "the computed import target"
    assert heights.resolve() in deps[0].files, "the surface() target"
    assert deps[0].missing == ()


def test_a_depfile_that_was_never_written_reads_as_absent(tmp_path: Path):
    """`absent` is a third state and not a spelling of "read nothing".

    Unit-level and engine-independent on purpose. The first cut of this test
    asserted that a SYNTAX ERROR produces `absent`, which is true on 2021.01
    and false on the 2026.08.01 snapshot — that engine writes a depfile even
    for an unparseable model, so the state is `partial`. F13 again, and caught
    by the matrix rather than by review. What is version-independent is the
    thing the state actually means: no file, no claim.
    """
    deps = openscad._read_depfile(tmp_path / "never-written", ok=True)
    assert deps.state == "absent"
    assert deps.files == ()


@needs_openscad
def test_a_broken_model_never_reports_a_complete_input_set(tmp_path: Path):
    """Whichever of the two non-complete states this engine gives.

    Both engine versions must agree on the part that matters: a render that
    failed has NOT told us its whole input set, so reading it as `complete`
    would let the strongest source of truth degrade into a false negative
    exactly when the model is most broken — silence reading as success, in the
    one field built to prevent it.
    """
    source = _scad(tmp_path, "broken.scad", "cube([1,1,1)\n")
    deps: list[openscad.RenderDeps] = []
    result = openscad.render(OpenSCADSource(path=source), tmp_path, deps_out=deps)

    assert isinstance(result, BuildError), result
    assert deps[0].state in ("absent", "partial"), deps[0].state
    assert deps[0].state != "complete"

    # The contrast is the evidence: without it this passes against a tree with
    # the whole feature reverted, since an engine never asked for a depfile
    # answers `absent` here too.
    ok = _scad(tmp_path, "fine.scad", "cube([1,1,1]);\n")
    good: list[openscad.RenderDeps] = []
    assert isinstance(openscad.render(OpenSCADSource(path=ok), tmp_path, deps_out=good), Path)
    assert good[0].state == "complete", "a failed render must be distinguishable from a real one"
    assert ok.resolve() in good[0].files


@needs_openscad
def test_a_missing_import_target_is_named_rather_than_left_silent(tmp_path: Path):
    """A dependency the engine lists need not exist on disk.

    Measured: a missing `import()` target is listed by its resolved absolute
    path. That is not a parse failure to defend against — it names a build
    input the model wanted and did not get, which is strictly more than the
    silence partspec had before. Anything hashing this list must survive it.
    """
    source = _scad(tmp_path, "part.scad", 'import("nope.stl");\n')
    deps: list[openscad.RenderDeps] = []
    result = openscad.render(OpenSCADSource(path=source), tmp_path, deps_out=deps)

    assert isinstance(result, BuildError), result
    assert len(deps) == 1
    assert deps[0].state == "partial", "the engine stopped; this is a floor, not the set"
    assert (tmp_path / "nope.stl").resolve() in deps[0].missing


def test_another_options_rejection_is_not_read_as_a_rejected_depfile():
    """A rejected `--backend` must not be read as a rejected `-d`.

    OpenSCAD answers an unknown option with a `Usage:` dump listing every
    option it DOES take, and on 2021.01 one of those lines is
    `-d [ --d ] arg  deps_file -generate a dependency file for make`. The first
    cut of the fallback searched the whole of stderr, so EVERY rejected option
    matched — and `backend=` on 2021.01 is the ordinary experience of a
    contract written against a newer engine, not an exotic one — silently
    turning depfiles off for the rest of the process.

    Pinned at the predicate rather than by driving the binary, because the two
    engine versions do not agree on what an unknown backend even is: 2021.01
    rejects it as an option, and the 2026.08.01 snapshot accepts the option and
    fails the model with `ERROR: Unknown rendering backend`. The defect is in
    the matching, so that is what this holds still.

    `_is_unknown_option`'s own docstring already says why — "One line, not a
    window" — and this is the same rule one field over.
    """
    stderr = (
        "unrecognised option '--backend=CGAL'\n"
        "Usage: openscad [options] file.scad\n"
        "  -o [ --o ] arg               output file\n"
        "  -d [ --d ] arg               deps_file -generate a dependency file for make\n"
    )

    assert openscad._is_unknown_option(stderr), "premise: the engine rejected an option"
    assert openscad._DEPS_RE.search(stderr) is not None, (
        "premise: the usage dump names -d, which is why searching all of stderr was wrong"
    )
    assert openscad._DEPS_RE.search(openscad._signal_lines(stderr)[0]) is None, (
        "the rejection names --backend, not -d; the dump below it is not evidence"
    )


# --------------------------------------------------------------------------
# the marker strings, against both engines the CI matrix pins (#286)
# --------------------------------------------------------------------------


def test_the_unresolved_markers_match_both_engine_spellings():
    """The engines word these differently, and matching one is F13 in miniature.

    Each line below was produced by running the same source under the binary
    named, not transcribed from documentation. `Can't open include file` was the
    only include spelling listed until PR #306, so on 2026.08.01 that marker had
    been dead since the snapshot leg was added — a guard that silently stops
    guarding on one half of the matrix is exactly the failure the matrix exists
    to make loud.

    Asserted against the matcher directly rather than through a render, so it
    runs on a machine with no engine at all and cannot be skipped into silence.
    """
    observed = [
        # 2021.01
        "WARNING: Can't open include file 'nowhere/absent.scad'.",
        "WARNING: Ignoring unknown module 'bore_hole' in file um.scad, line 3",
        "WARNING: Ignoring unknown function 'nofunc' in file q.scad, line 1",
        "WARNING: Ignoring unknown variable 'nope' in file q.scad, line 2",
        # 2026.08.01 — note "find" for "open", and double quotes on the variable
        "WARNING: Can't find include file 'nowhere/absent.scad'. in file q.scad, line 1",
        "WARNING: Ignoring unknown module 'nope_module' in file q.scad, line 2",
        "WARNING: Ignoring unknown function 'nofunc' in file q.scad, line 1",
        'WARNING: Ignoring unknown variable "nope" in file q.scad, line 2',
    ]
    for line in observed:
        assert openscad._unresolved_lines(line, openscad._UNRESOLVED_NAME_MARKERS), line

    # Positive-only, a marker list of ("WARNING",) would satisfy every line
    # above. These are ordinary engine chatter and a real diagnostic that is
    # NOT a name failing to resolve; matching any of them would refuse correct
    # parts, which is how `undefined operation` came off this list.
    for benign in (
        "WARNING: undefined operation (string + number) in file q.scad, line 2",
        "WARNING: Can't open library 'nowhere/absent.scad'.",
        'ECHO: "include file: none"',
        "Geometries in cache: 2",
        "WARNING: Unable to convert cube(size=[undef, 5, 5], ...) parameter to a number",
    ):
        assert not openscad._unresolved_lines(benign, openscad._UNRESOLVED_NAME_MARKERS), benign


@needs_openscad
def test_the_empty_result_marker_matches_what_the_engine_prints(tmp_path: Path):
    """`_EMPTY_RESULT` decides `produced_nothing`, and so decides `p.empty()`.

    Asserted against stderr an engine actually produced, not against a literal:
    a literal spelled from the constant is a tautology that can only fail by
    editing the constant, and would not have caught the include marker's
    `Can't open` / `Can't find` divergence either. This renders a genuinely
    null result -- two disjoint cubes intersected -- and checks the constant
    against what came back, so it fails on whichever engine changes the
    wording. Both pinned binaries print the bare sentence today.
    """
    src = tmp_path / "e.scad"
    src.write_text(
        "intersection() {\n  cube([10,10,10]);\n  translate([50,0,0]) cube([10,10,10]);\n}\n"
    )
    result = openscad.render(OpenSCADSource(path=src), tmp_path / "out")

    assert isinstance(result, BuildError)
    assert result.produced_nothing, "the empty result was not recognised as one"
    assert openscad._EMPTY_RESULT in (result.stderr or "")


def test_a_missing_use_library_is_not_itself_an_unresolved_name():
    """`use <absent.scad>` alone removes no geometry, so it is not this guard's.

    Both engines say `Can't open library` for it — a third spelling, deliberately
    unmatched. `use` imports modules and functions but evaluates nothing, so a
    library that did not load only matters once something it defined is
    *called*, and that call prints `Ignoring unknown module`, which is matched.
    Guarding on the library line as well would refuse a source that imports a
    library it never uses — correct code, refused.
    """
    for line in (
        "WARNING: Can't open library 'nowhere/absent.scad'.",
        "WARNING: Can't open library 'nowhere/absent.scad'. in file u.scad, line 1",
    ):
        assert not openscad._unresolved_lines(line, openscad._UNRESOLVED_NAME_MARKERS)


@needs_openscad
def test_a_parameter_refusal_says_when_its_variable_list_is_incomplete(tmp_path: Path):
    """The list is only as complete as the closure, and the sentence must say so.

    `unbound_parameters` answers from `top_level_variables`, which reads the
    files partspec resolved. The refusal claimed the name matched nothing "in
    <file> **or its includes**" -- a claim about includes it never opened, and
    one the engine contradicts, since the `-D` does reach the geometry (#287).

    The refusal itself stands. Skipping it was tried and traded a loud false
    error for a silent false pass (review of PR #310). What changes is that the
    sentence names what could not be read and says the list is short, and that
    the fault is `environment`: an include that will not open says nothing
    about the part, and the remedy is to make it resolvable.
    """
    entry = _scad(
        tmp_path,
        "part.scad",
        "include <missing_lib.scad>\nplate_z = 3;\ncube([lib_x, 10, plate_z]);\n",
    )
    result = openscad.render(
        OpenSCADSource(path=entry, params={"lib_x": 20.0, "plate_z": 3.0}), tmp_path / "out"
    )

    assert isinstance(result, BuildError), result
    assert result.origin == "environment", "an unopenable include is not the part's fault"
    assert "missing_lib.scad" in result.message
    assert "INCOMPLETE" in result.message
    assert "or its includes" not in result.message, "the claim it could not make"
    assert "plate_z" in (result.hint or ""), "what it did read"


@needs_openscad
def test_an_unresolved_use_does_not_excuse_a_parameter_that_binds_nothing(tmp_path: Path):
    """A `use`d file contributes no top-level variable, so an unresolved `use`
    shortens nothing and cannot excuse anything.

    This is the hole an earlier draft of #287 opened. `Closure.unresolved`
    holds `include` and `use` alike, so gating the refusal on it let a genuinely
    transposed `-D` through -- and `Can't open library` is deliberately absent
    from `_UNRESOLVED_NAME_MARKERS`, so #286's post-render guard stayed silent
    too. Measured on both engines before the fix: `verdict: pass`, exit 0, with
    `params` asserting `bore_diamter=20.0` against geometry 8 wide.
    """
    entry = _scad(
        tmp_path,
        "part.scad",
        "use <helpers/absent.scad>\nbore_diameter = 8;\ncube([bore_diameter, 10, 10]);\n",
    )
    result = openscad.render(
        OpenSCADSource(path=entry, params={"bore_diamter": 20.0}), tmp_path / "out"
    )
    assert isinstance(result, BuildError), "a dropped -D must never render as a pass"
    assert "bore_diamter" in result.message
    # And with the ORDINARY sentence, which is substantively true here: a `use`d
    # file contributes no top-level variable, so the list is not short and
    # nothing about it is incomplete. Claiming otherwise sent a reader to create
    # the missing file, after which the transposed `-D` reached `verdict: pass`.
    assert "INCOMPLETE" not in result.message
    assert result.origin == "model"


def test_only_an_unbroken_include_chain_shortens_the_variable_list(tmp_path: Path):
    """`use` stops the chain, and it stops it transitively.

    Measured on the engine rather than reasoned from the manual: with
    `entry -> use -> include` of a file declaring `X`, OpenSCAD prints
    `Ignoring unknown variable 'X'` at the entry, where including that file
    directly renders `X`. So a file behind a `use` can never widen the entry's
    top-level variable list, and an unresolved `include` found inside one
    cannot have narrowed it.

    Without this, `unresolved_includes` was "every unresolved include seen
    anywhere in the walk", which claims a shortened list for a file that could
    not have contributed to it -- the same false sentence #287 exists to
    remove, one level deeper (review of PR #310).
    """
    (tmp_path / "behind_use.scad").write_text("include <gone_a.scad>\nmodule m() { cube(1); }\n")
    (tmp_path / "mid.scad").write_text("include <gone_b.scad>\n")

    # Reached only through a `use`: its unresolved include is invisible to the
    # entry's variable list, so it must not be named as shortening it.
    through_use = _scad(tmp_path, "e1.scad", "use <behind_use.scad>\ncube([1, 1, 1]);\n")
    c1 = openscad.include_closure(through_use)
    assert c1.unresolved == ("gone_a.scad",), "still unresolved for every other question"
    assert c1.unresolved_includes == ()

    # An unbroken include chain does reach the entry, at any depth.
    through_include = _scad(tmp_path, "e2.scad", "include <mid.scad>\ncube([1, 1, 1]);\n")
    c2 = openscad.include_closure(through_include)
    assert c2.unresolved_includes == ("gone_b.scad",)

    # A file both `use`d and `include`d is spliced: the include wins.
    both = _scad(tmp_path, "e3.scad", "use <mid.scad>\ninclude <mid.scad>\ncube([1, 1, 1]);\n")
    assert openscad.include_closure(both).unresolved_includes == ("gone_b.scad",)


@pytest.mark.parametrize(
    "files",
    [
        {"a.scad": "include <a.scad>\ncube(1);\n"},
        {"a.scad": "include <b.scad>\ncube(1);\n", "b.scad": "include <a.scad>\n"},
        {
            "a.scad": "use <b.scad>\ninclude <c.scad>\ncube(1);\n",
            "b.scad": "include <c.scad>\n",
            "c.scad": "use <a.scad>\ninclude <gone.scad>\n",
        },
        {
            "a.scad": "include <b.scad>\nuse <c.scad>\n",
            "b.scad": "include <d.scad>\n",
            "c.scad": "include <d.scad>\n",
            "d.scad": "include <gone.scad>\n",
        },
        # The re-queue INSIDE a cycle: `b` is reached both ways and `c` closes
        # the loop back to `a`. Without this case the other four never visit a
        # file twice, so none of them exercises the branch the bound guards --
        # they would catch its removal by hanging on the ordinary path, which
        # is a weaker thing than covering it.
        {
            "a.scad": "use <b.scad>\ninclude <b.scad>\ninclude <c.scad>\ncube(1);\n",
            "b.scad": "include <gone.scad>\n",
            "c.scad": "include <a.scad>\n",
        },
    ],
    ids=["self", "mutual", "use-include-cycle", "diamond", "requeue-in-cycle"],
)
def test_the_closure_walk_terminates_on_a_cycle(tmp_path: Path, files: dict[str, str]):
    """Cycles are legal in OpenSCAD, and the walk now visits some files twice.

    Tracking include-reachability means a file reached first through a `use`
    and later through an `include` is re-queued, so `seen` alone is no longer
    what bounds the walk -- a file is queued at most twice and never again once
    spliced. These are the shapes that would expose a bound that does not hold.

    A regression here HANGS rather than fails. The CI jobs carry
    `timeout-minutes`, so it ends as a job timeout rather than running forever,
    but nothing prints the cause -- which is why the shapes are enumerated here
    instead of trusted to the ordinary tests.

    Only `requeue-in-cycle` visits a file twice; the other four cover cycles
    that terminate on `seen` alone and pass against the pre-#287 walker too.
    Both properties are wanted, and saying which case carries which is the
    point -- an earlier draft of this docstring claimed all of them exercised
    the re-queue, which was measurably false (round-4 review of PR #310).
    """
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    closure = openscad.include_closure(tmp_path / "a.scad")
    assert len(closure.files) == len(files)


@needs_openscad
@pytest.mark.parametrize("coord", [5.0, 10000.0], ids=["origin", "ten-metres"])
def test_the_boolean_floor_does_not_coarsen_with_distance(tmp_path: Path, coord: float):
    """A 1e-5 mm feature survives a boolean at the origin and at ten metres.

    The one thing #315 settled that is worth a test: **the floor does not
    coarsen with distance from the origin.** An earlier draft of §4.12 warned
    that it did, and that warning was backwards. If manifold's floor tracked
    half a float32 ULP all the way out it would be ~4.9e-4 mm at ten metres and
    this feature would vanish there; it does not.

    That is all this asserts. It does NOT establish a floor value or a law --
    #315's formula was fitted to one probe shape at positive coordinates and is
    false outside it, which is why §4.12 now states the figures as an existence
    proof rather than a bound. Scoped deliberately: an inequality that holds is
    worth more than a law that does not.

    Two renders per engine, no bisection -- bisections misled both measurements
    that produced #315.
    """
    src = tmp_path / "pin.scad"
    src.write_text(
        f"intersection() {{\n"
        f"  translate([0,{coord - 5:.17g},0]) cube([10,10,10]);\n"
        f"  translate([5,{coord:.17g},9]) cube([1e-5,1e-5,2]);\n"
        f"}}\n"
    )
    result = openscad.render(OpenSCADSource(path=src), tmp_path / "out")

    assert not isinstance(result, BuildError), (
        f"a 1e-5 mm interference vanished at coordinate {coord} — the floor coarsened "
        f"with distance, which #315 measured that it does not: {result}"
    )
