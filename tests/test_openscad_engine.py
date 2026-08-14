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
    """Clause (3) of the #208 guard: `<stem>.stl` must already EXIST.

    Both this and the test below pin a clause whose deletion left the suite
    green (adversarial review of #223). The guard refuses a render into the
    model's own directory only when the derived name is already taken; a first
    run there takes a name nothing holds, so nothing can be destroyed and
    nothing is refused. Drop the clause and this ordinary invocation — an
    external-data model rendered beside its own source, once — becomes a hard
    environment error over a file that does not exist.

    The second render IS refused, and that is the same boundary from the other
    side: by then partspec's own artifact is sitting there, and nothing on disk
    says whether it or an input owns the name.
    """
    (tmp_path / "input.stl").write_bytes(b"donor")
    source = _scad(
        tmp_path, "imports_data.scad", FIXTURES.joinpath("imports_data.scad").read_text()
    )

    first = openscad.render(OpenSCADSource(path=source), tmp_path)
    assert isinstance(first, Path), first
    assert first == tmp_path / "imports_data.stl"
    assert first.stat().st_size > 0

    second = openscad.render(OpenSCADSource(path=source), tmp_path)
    assert isinstance(second, BuildError), "now the derived name is taken"
    assert "cannot prove imports_data.stl is not one of them" in second.message


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
