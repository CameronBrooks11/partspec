"""`source_closure.imports` — which distributions a model imported, and how.

Every trap here was measured before it was tested (`DESIGN-190.md` §R6), and
each has the same shape: the feature keeps working, quietly, over the wrong
files. A test that only asserted "a digest came out" would pass through all
four.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from partspec import build123d, imports
from partspec.runner import _python_closure


def _clear() -> None:
    imports._record_index.cache_clear()
    imports._metadata_digest.cache_clear()
    imports._content_digest.cache_clear()
    imports._resolved.cache_clear()


@pytest.fixture
def fresh() -> Iterator[None]:
    """Undo everything a synthetic install touches.

    The per-process memoisation these tests exercise is exactly what leaks
    between them, and `just test-reverse` exists to catch that.
    """
    path, modules = list(sys.path), set(sys.modules)
    _clear()
    yield
    for name in set(sys.modules) - modules:
        del sys.modules[name]
    sys.path[:] = path
    _clear()


@pytest.fixture
def whole_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inventory everything, including what was loaded before partspec was.

    `_BASELINE` is captured at import and is the right default for a `partspec
    check`, where it holds the venv's own scenery and nothing a model needs.
    Under pytest it holds the whole test runner, so a test that wants to see a
    real installed distribution has to ask for the unfiltered view.
    """
    monkeypatch.setattr(imports, "_BASELINE", frozenset())


def _install(site: Path, name: str, version: str, files: dict[str, str]) -> Path:
    """A distribution whose RECORD declares exactly the files it wrote."""
    rows = []
    for relative, text in files.items():
        target = site / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        rows.append(f"{relative},sha256={digest},{len(text)}")
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    (info / "RECORD").write_text("\n".join(rows) + "\n")
    return info


def _activate(*directories: Path) -> None:
    for directory in reversed(directories):
        sys.path.insert(0, str(directory))
    importlib.invalidate_caches()
    _clear()


# --------------------------------------------------------------------------
# the two tiers
# --------------------------------------------------------------------------


def test_a_record_owned_import_is_identified_by_its_installer(tmp_path: Path, fresh: None):
    site = tmp_path / "site"
    _install(site, "widget", "1.2.3", {"widget/__init__.py": "VALUE = 1\n"})
    _activate(site)
    importlib.import_module("widget")

    entry = imports.inventory()["widget"]
    assert entry["identity"] == "metadata"
    assert entry["version"] == "1.2.3"
    assert entry["digest"].startswith("sha256:")


def test_an_import_no_record_claims_is_hashed_from_its_bytes(tmp_path: Path, fresh: None):
    """The tier that exists because the cheap one would be vacuous here."""
    checkout = tmp_path / "checkout"
    (checkout / "loose").mkdir(parents=True)
    (checkout / "loose" / "__init__.py").write_text("VALUE = 1\n")
    (checkout / "loose" / "helper.py").write_text("OTHER = 2\n")
    _activate(checkout)
    importlib.import_module("loose")

    entry = imports.inventory()["loose"]
    assert entry["identity"] == "content"
    assert entry["version"] is None
    assert entry["files"] == 2, "the whole tree, not the one file that was imported"


def test_a_source_checkout_beats_the_version_metadata_would_have_reported(
    tmp_path: Path, fresh: None
):
    """The fleet's own configuration, and the reason tier 2 is not optional.

    All three arm-A agents ran a `sys.path` checkout of `cq-gridfinity` while
    the venv reported 0.5.7 from a different, 12-file copy. A closure that took
    the installer's word would have described code that never ran.
    """
    site = tmp_path / "site"
    _install(site, "gadget", "0.5.7", {"gadget/__init__.py": "VALUE = 'installed'\n"})
    checkout = tmp_path / "checkout"
    (checkout / "gadget").mkdir(parents=True)
    (checkout / "gadget" / "__init__.py").write_text("VALUE = 'checkout'\n")
    (checkout / "gadget" / "extra.py").write_text("MORE = 1\n")
    _activate(checkout, site)

    module = importlib.import_module("gadget")
    assert module.VALUE == "checkout", "premise: the checkout is what imported"

    entry = imports.inventory()["gadget"]
    assert entry["identity"] == "content"
    assert entry["version"] is None, "0.5.7 describes the copy that did not run"
    assert entry["files"] == 2
    assert entry["digest"] != imports._metadata_digest("gadget")


def test_an_edit_to_an_installed_file_does_not_move_a_metadata_digest(tmp_path: Path, fresh: None):
    """A limitation, pinned because SPEC-report §8.3 rule 5 now states it.

    Ownership is decided by path, so an edited file the RECORD declares is
    still declared: the entry stays `metadata` and the digest stays the
    installer's. Catching it would mean hashing every loaded file to compare
    against its declared hash, which is the cost this tier exists to avoid,
    and `DESIGN-190.md` R3 takes that trade knowingly — §7.1 already limits a
    digest to comparison-based tamper evidence. If this test ever fails
    because the digest moved, the spec is what needs the edit.
    """
    site = tmp_path / "site"
    _install(site, "tampered", "1.0", {"tampered/__init__.py": "VALUE = 1\n"})
    _activate(site)
    importlib.import_module("tampered")
    before = imports.inventory()["tampered"]

    (site / "tampered" / "__init__.py").write_text("VALUE = 666\n")
    _clear()
    after = imports.inventory()["tampered"]

    assert after == before
    assert after["identity"] == "metadata"


def test_the_bytes_that_moved_move_the_digest(tmp_path: Path, fresh: None):
    """A content digest that did not track its own tree would be worse than
    the metadata it replaced: confident, cheap and blind."""
    checkout = tmp_path / "checkout"
    (checkout / "moving").mkdir(parents=True)
    (checkout / "moving" / "__init__.py").write_text("VALUE = 1\n")
    _activate(checkout)
    importlib.import_module("moving")
    before = imports.inventory()["moving"]["digest"]

    (checkout / "moving" / "__init__.py").write_text("VALUE = 2\n")
    _clear()
    assert imports.inventory()["moving"]["digest"] != before


def test_two_checkouts_of_one_tree_agree(tmp_path: Path, fresh: None):
    """SPEC-report §8.3: the digest identifies contents, not locations, or a
    CI run could never be compared against a laptop run."""
    digests = []
    for where in ("first", "second"):
        checkout = tmp_path / where
        (checkout / "twin").mkdir(parents=True)
        (checkout / "twin" / "__init__.py").write_text("VALUE = 1\n")
        digests.append(imports._content_digest((checkout / "twin",))[0])
    assert digests[0] == digests[1]


# --------------------------------------------------------------------------
# attribution: exact RECORD rows
# --------------------------------------------------------------------------


def test_attribution_reads_whole_record_rows_not_the_first_path_segment(
    tmp_path: Path, fresh: None
):
    """Two distributions sharing a top-level directory is the ordinary case —
    `zope.*`, `google.*`, `sphinxcontrib.*`, `ruamel.*`, `jaraco.*` — and an
    index keyed on `row[0].split('/')[0]` makes each the claimant of the
    other's modules. PR #212's review caught it recording a distribution whose
    `__init__.py` raises `RuntimeError('beta was never imported')`.
    """
    site = tmp_path / "site"
    _install(site, "alpha-dist", "1.0", {"ns/alpha/__init__.py": "VALUE = 1\n"})
    _install(
        site,
        "beta-dist",
        "2.0",
        {"ns/beta/__init__.py": "raise RuntimeError('beta was never imported')\n"},
    )
    _activate(site)
    importlib.import_module("ns.alpha")

    found = imports.inventory()
    assert found["alpha-dist"]["version"] == "1.0"
    assert "beta-dist" not in found, "nothing in beta-dist was imported"


def test_a_distribution_digest_covers_the_files_beside_its_package(tmp_path: Path, fresh: None):
    """`cadquery_ocp.libs/` — 69 vendored OCCT shared objects, 105 MB — sits
    *beside* `OCP/`, not inside it, and `sys.modules` never names it. Scoping a
    digest to the imported package's directory misses all of it while claiming
    to identify the distribution; scoping to the RECORD does not.
    """
    digests = []
    for lib_bytes in ("ELF-one\n", "ELF-two\n"):
        site = tmp_path / f"site-{len(digests)}"
        _install(
            site,
            "vendored",
            "1.0",
            {"vendored/__init__.py": "VALUE = 1\n", "vendored.libs/libfoo.so": lib_bytes},
        )
        _activate(site)
        rows = [row for row, _ in imports._record_index()[1]["vendored"]]
        assert "vendored.libs/libfoo.so" in rows, "the sibling directory is part of the unit"
        digests.append(imports._metadata_digest("vendored"))
        _clear()
    assert digests[0] != digests[1], "a changed vendored library must move the digest"


def test_an_editable_finder_shim_does_not_stand_in_for_the_library(tmp_path: Path, fresh: None):
    """`pip install -e .` on a flat layout writes `__editable___<name>_finder.py`
    **into site-packages**, lists it in the RECORD, and imports it from a `.pth`
    at startup. Index that row and the shim is a RECORD-owned loaded file, so
    the distribution earns a `metadata` entry for a library the model never
    imported — and the shim's `MAPPING` embeds the checkout's absolute path, so
    two byte-identical installs at two paths disagree. That is the
    machine-sensitivity the `../` filter exists to remove, arriving through a
    row the filter does not cover.
    """
    site = tmp_path / "site"
    finder = "__editable___flat_lib_0_2_0_finder"
    _install(
        site,
        "flat-lib",
        "0.2.0",
        {
            f"{finder}.py": f"MAPPING = {{'flatlib': '{tmp_path}/src/flatlib'}}\n",
            "__editable__.flat_lib-0.2.0.pth": f"import {finder}\n",
        },
    )
    _activate(site)
    importlib.import_module(finder)

    found = imports.inventory()
    assert "flat-lib" not in found, "the shim is not the library, and never ran its code"
    assert finder not in found
    assert not imports._record_index()[1]["flat-lib"], "no row of this install is its code"


def test_a_content_digest_covers_the_package_tree_and_says_so(tmp_path: Path, fresh: None):
    """The other side of the trap above, and the reason rule 3 is about the
    *metadata* tier. With no RECORD there is nothing that can associate
    `co_pkg.libs/` with `co_pkg` — the vendored directory is named for the
    distribution, not the package, which is why `OCP` sits beside
    `cadquery_ocp.libs`. The digest covers the tree it was loaded from, rule 6
    says exactly that, and this pins the two together so neither can drift.
    """
    checkout = tmp_path / "checkout"
    (checkout / "co_pkg").mkdir(parents=True)
    (checkout / "co_pkg" / "__init__.py").write_text("VALUE = 1\n")
    (checkout / "co_pkg.libs").mkdir()
    (checkout / "co_pkg.libs" / "libfoo.so").write_text("ELF-one\n")
    _activate(checkout)
    importlib.import_module("co_pkg")

    entry = imports.inventory()["co_pkg"]
    assert entry["files"] == 1, "the package tree, and rule 6 says no more than that"

    (checkout / "co_pkg" / "data.txt").write_text("used at run time\n")
    _clear()
    assert imports.inventory()["co_pkg"]["files"] == 2, "the whole tree, not the .py files"


def test_a_console_script_row_cannot_move_the_digest(tmp_path: Path, fresh: None):
    """A generated console script embeds the venv's absolute path in its
    shebang, so its hash differs on every machine — numpy's differed across all
    five fleet venvs, and that alone. Unfiltered, the digest is per-machine
    noise and a comparator built on it reports a change every time.
    """
    digests = []
    for shebang in ("#!/one/bin/python\n", "#!/two/bin/python\n"):
        site = tmp_path / f"site-{len(digests)}"
        info = _install(site, "scripted", "1.0", {"scripted/__init__.py": "VALUE = 1\n"})
        row = f"../../../bin/scripted,sha256={hashlib.sha256(shebang.encode()).hexdigest()},18\n"
        (info / "RECORD").write_text((info / "RECORD").read_text() + row)
        _activate(site)
        digests.append(imports._metadata_digest("scripted"))
        _clear()
    assert digests[0] == digests[1]


def test_a_row_that_is_not_a_console_script_still_moves_the_digest(tmp_path: Path, fresh: None):
    """The other half of the filter: it must drop the volatile rows and only
    those, or the test above passes on a digest that ignores everything."""
    digests = []
    for body in ("VALUE = 1\n", "VALUE = 2\n"):
        site = tmp_path / f"site-{len(digests)}"
        _install(site, "moved", "1.0", {"moved/__init__.py": body})
        _activate(site)
        digests.append(imports._metadata_digest("moved"))
        _clear()
    assert digests[0] != digests[1]


# --------------------------------------------------------------------------
# the gaps
# --------------------------------------------------------------------------


def test_a_namespace_package_is_a_named_gap_and_not_a_crash(tmp_path: Path, fresh: None):
    """`__file__ is None`. `_python_closure` skipped these silently; under
    SPEC-report §8.3 they are named in `unseen` and listed in `imports`, so a
    reader of either can see that something was imported and not identified.
    """
    site = tmp_path / "site"
    (site / "ghost").mkdir(parents=True)
    _activate(site)
    module = importlib.import_module("ghost")
    assert module.__file__ is None, "premise: a namespace package has no file"

    entry = imports.inventory()["ghost"]
    assert entry == {"identity": "unidentified", "version": None, "digest": None}

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model = model_dir / "m.py"
    model.write_text("def make_part():\n    pass\n")
    closure = _python_closure(build123d(model), None)
    assert closure["unseen"] == ["native_reads", "unidentified_imports"]
    assert closure["partial"] is True


def test_the_inventory_is_not_empty_in_an_ordinary_process(whole_process: None):
    """The `platstdlib` trap (§R6), which is silent by construction: in a venv
    `sysconfig.get_paths()["platstdlib"]` is the **parent** of `site-packages`,
    so excluding the stdlib by that path excludes every installed distribution
    too. The prototype that did it reported zero imports and its tests passed.

    Asserted against this real venv rather than a synthetic one, because the
    trap is a property of where a real interpreter puts things.
    """
    found = imports.inventory()
    assert found, "an inventory that filtered everything away must fail loudly"
    assert found["pytest"]["identity"] == "metadata"
    assert found["pytest"]["version"]
    assert "json" not in found and "unittest" not in found, "the stdlib is not an input"


def test_no_directory_holding_installed_packages_reads_as_stdlib():
    """`--system-site-packages` on a distribution that installs to
    `<stdlib>/site-packages` — Arch, Fedora, RHEL — puts third-party code
    inside the stdlib directory and outside `sysconfig`'s `purelib`. Every
    system distribution would then vanish from the closure in silence."""
    for directory in imports._site_dirs():
        assert not imports._is_stdlib(directory), directory
    assert imports._site_dirs(), "there is always at least one site directory"


def test_the_stdlib_lives_where_os_does_not_where_platstdlib_says():
    stdlib = imports._stdlib_dir()
    assert imports._is_stdlib(str(Path(sys.modules["json"].__file__ or "").resolve()))
    assert not any(imports._is_stdlib(site) for site in imports._site_dirs()), (
        f"site-packages must never read as stdlib, under {stdlib}"
    )


# --------------------------------------------------------------------------
# memoisation, and what it must not lose
# --------------------------------------------------------------------------


def test_a_later_targets_imports_are_not_lost_to_the_cache(tmp_path: Path, fresh: None):
    """One `partspec check` runs several targets in one interpreter. The
    per-file work is memoised; the inventory itself must not be, or the second
    target inherits the first target's answer and silently under-reports.
    """
    site = tmp_path / "site"
    _install(site, "early", "1.0", {"early/__init__.py": "VALUE = 1\n"})
    _install(site, "late", "1.0", {"late/__init__.py": "VALUE = 1\n"})
    _activate(site)

    importlib.import_module("early")
    first = imports.inventory()
    assert "late" not in first

    importlib.import_module("late")
    second = imports.inventory()
    assert "late" in second and "early" in second


def test_a_snapshot_names_exactly_what_the_inventory_would(tmp_path: Path, fresh: None):
    """`names_of` is intersected with an `inventory`, so a name the two spell
    differently is a `preloaded` entry that either goes missing or is invented.
    They share one scan; this holds them to the same answer over both identity
    tiers and a namespace package at once."""
    site = tmp_path / "site"
    _install(site, "owned", "1.0", {"owned/__init__.py": "VALUE = 1\n"})
    checkout = tmp_path / "checkout"
    (checkout / "unowned").mkdir(parents=True)
    (checkout / "unowned" / "__init__.py").write_text("VALUE = 2\n")
    _activate(site, checkout)
    importlib.import_module("owned")
    importlib.import_module("unowned")

    assert imports.names_of(frozenset(sys.modules)) == set(imports.inventory())
    assert {"owned", "unowned"} <= imports.names_of(frozenset(sys.modules))


def test_a_snapshot_covers_only_the_modules_it_was_taken_over(tmp_path: Path, fresh: None):
    """The point of the snapshot: what was loaded BEFORE this target began.
    A name imported after it must not appear, or every import a part made
    itself would read as inherited."""
    site = tmp_path / "site"
    _install(site, "before", "1.0", {"before/__init__.py": "VALUE = 1\n"})
    _install(site, "after", "1.0", {"after/__init__.py": "VALUE = 1\n"})
    _activate(site)

    importlib.import_module("before")
    snapshot = frozenset(sys.modules)
    importlib.import_module("after")

    assert "before" in imports.names_of(snapshot)
    assert "after" not in imports.names_of(snapshot)
    assert "after" in imports.inventory(), "and the inventory still records it"


def test_the_entry_point_is_not_an_import(whole_process: None):
    """`__main__` under a console script is a venv-generated launcher whose
    shebang embeds an absolute path, and `__mp_main__` is multiprocessing's
    alias for the same file — importing build123d registers it. Hashing either
    makes the closure machine-specific."""
    assert "__main__" not in imports.inventory()
    assert "__mp_main__" not in imports.inventory()


def test_the_tool_and_the_venv_are_not_inputs_of_the_part():
    """What was loaded before partspec was is scenery, and scenery is not a
    build input. `partspec` itself is `tool.version`, which `diff` already
    compares, and it is editable-installed in the dogfood loop — recorded here
    it would report "an input moved" on every part after any edit to the tool.
    `_virtualenv` is written by `uv venv` and not by `python -m venv`, so it
    would separate two machines with identical package sets.
    """
    found = imports.inventory()
    assert "partspec" not in found
    assert "_virtualenv" not in found
    assert "partspec" in imports._BASELINE, "the exclusion is the baseline's doing"


def test_a_library_imported_after_partspec_is_not_scenery(tmp_path: Path, fresh: None):
    """The other half of the baseline: it must drop what preceded partspec and
    nothing else, or a model's own library disappears with it. Everything a
    contract loads — the model, its helpers, the CAD kernel the engine imports
    lazily at build time — happens after."""
    site = tmp_path / "site"
    _install(site, "afterwards", "1.0", {"afterwards/__init__.py": "VALUE = 1\n"})
    _activate(site)
    importlib.import_module("afterwards")

    assert imports.inventory()["afterwards"]["version"] == "1.0"


def test_the_models_own_directory_is_not_counted_twice(tmp_path: Path, fresh: None):
    """`digest`/`files` already cover it, and an entry here would make the
    same helper move two fields of one closure."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "beside.py").write_text("VALUE = 1\n")
    _activate(model_dir)
    importlib.import_module("beside")

    assert "beside" in imports.inventory()
    assert "beside" not in imports.inventory(skip_tree=model_dir)


def test_the_contract_is_not_an_import(tmp_path: Path, fresh: None):
    """A *source* closure that moved whenever a claim changed would answer a
    different question than its name (SPEC-report §8.3)."""
    contract = tmp_path / "spec.py"
    contract.write_text("CLAIM = 1\n")
    _activate(tmp_path)
    importlib.import_module("spec")

    assert "spec" in imports.inventory()
    assert "spec" not in imports.inventory(exclude=frozenset({contract.resolve()}))
