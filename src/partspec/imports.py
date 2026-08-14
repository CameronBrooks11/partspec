"""Identify the distributions a Python model imported, and how honestly.

`source_closure` covers the model's own directory. A contract that wraps a
third-party library therefore identifies none of the code that produced the
geometry: the fleet-01 study's bin was one thin wrapper over seventeen files
of `cqgridfinity`, and the report said `files: 1` (#190).

Two identity tiers, both automatic, chosen per import by one question — **is
the file that was imported one the installer's RECORD actually describes?**

- `metadata`: yes. Take the distribution's version and a digest over its
  RECORD-declared hashes. Measured at 0.07 ms for `cadquery-ocp`'s 396 rows,
  and bounded by the ownership check, which is what keeps it from being
  vacuous.
- `content`: no. Hash the bytes that were imported. Editable installs,
  `sys.path` source checkouts and post-install edits all land here, and they
  are cheap by construction because they are source trees rather than wheels
  (measured on the fleet's checkout: 0.58 ms cold, 0.55 ms warm, 17 files).

The ownership check is not a formality. All three arm-A agents ran a
`sys.path` checkout of `cq-gridfinity` while the venv reported 0.5.7 from a
different, 12-file copy: `importlib.metadata.version()` described code that
never ran. Only the second tier can state what did.

Byte-hashing everything imported was measured and rejected: 1270 MB, 836 ms
warm / 1921 ms cold, 70% of it `vtk` and `casadi` arriving as transitive
imports of cadquery, which no author considers a build input.

Tier 3 — an author declaring a distribution worth byte-hashing regardless — is
deliberately not here yet.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
import sysconfig
from functools import cache
from pathlib import Path
from typing import Any

__all__ = ["CONTENT", "METADATA", "UNIDENTIFIED", "inventory"]

METADATA = "metadata"
"""The imported file is owned by a distribution's RECORD; take its word."""

CONTENT = "content"
"""The imported file is not RECORD-owned; hash what was actually there."""

UNIDENTIFIED = "unidentified"
"""Imported, and not identifiable at all — a namespace package (`__file__`
is None) with nothing under it that any distribution claims. Recorded as an
entry rather than dropped: a map that omits an import reads as an import that
never happened, which is the silence this tool exists to refuse."""

_BYTECODE = (".pyc", ".pyo")

_IMPORTABLE = (".py", ".so", ".pyd", ".dll")
"""Suffixes an `import` can load a module from, and so the only RECORD rows
that can ever be looked up. A file with any other suffix that somehow *is*
imported simply misses the index and gets byte-hashed, which is the safe
direction for a wrong guess."""

_POSIX = os.sep == "/"

_INVOCATION = frozenset({"__main__", "__mp_main__"})
"""The entry point, which is the run and not a build input.

Under a console script it is a venv-generated launcher whose shebang embeds
an absolute path, so hashing it makes the closure machine-specific — the same
defect the `../` RECORD filter exists to prevent, arriving by another door.
`__mp_main__` is multiprocessing's alias for that same file, and it is not
hypothetical: importing build123d pulls in joblib, which registers it."""


def inventory(
    *, skip_tree: Path | None = None, exclude: frozenset[Path] = frozenset()
) -> dict[str, dict[str, Any]]:
    """Every non-stdlib import in this process, keyed by what identifies it.

    Keys are **distribution** names for `metadata` entries and **module**
    names for `content` and `unidentified` ones, because a distribution is
    what carries a version and an unowned source tree has none. `identity`
    says which kind of name a key is.

    Ownership is decided **per file**, so a distribution is named here only
    because a file it declares was actually loaded — the check that keeps the
    cheap tier from describing code that never ran. Files no RECORD claims are
    grouped by the top-level module that imported them and byte-hashed, so an
    editable install or a `sys.path` checkout produces a content entry and no
    metadata entry at all.

    `skip_tree` (the model's own directory) and `exclude` (the contract) are
    dropped: both are already identified elsewhere in the report, and folding
    the contract in here would move the *source* closure whenever a claim
    changed.

    Read from `sys.modules`, so a target that runs second in a batch may
    inherit an earlier target's imports. That over-reports and never
    under-reports, which is the direction that cannot turn a missing build
    input into silence. It is also why nothing here caches the inventory
    itself — only the per-file work inside it, which does not vary.
    """
    owners, _rows, versions = _record_index()
    skip = str(skip_tree) if skip_tree is not None else None
    excluded = {str(path) for path in exclude}

    dists: set[str] = set()
    unowned: dict[str, set[Path]] = {}
    identified: set[str] = set()
    fileless: set[str] = set()

    for name, module in list(sys.modules.items()):
        if module is None or name in _INVOCATION:
            continue
        filename = getattr(module, "__file__", None)
        if not filename:
            if _is_unresolved_namespace(name, module, skip):
                fileless.add(name.partition(".")[0])
            continue
        path = os.path.normpath(filename)
        if path in excluded or _is_stdlib(path) or (skip and _within(path, skip)):
            continue
        owner = owners.get(path)
        if owner is None:
            # Second chance through a realpath — the expensive form, 22 µs a
            # call against ~1200 modules, so it is not spent on the ~95% that
            # match on the plain name. A site-packages reached through a
            # symlink resolves here, and a miss costs a byte hash rather than
            # a wrong claim.
            path = str(_resolved(filename))
            if path in excluded or (skip and _within(path, skip)):
                continue
            owner = owners.get(path)
        unit = name.partition(".")[0]
        if owner is not None:
            dists.add(owner)
            identified.add(unit)
        elif (loaded := Path(path)).is_file():
            unowned.setdefault(unit, set()).add(loaded)
            identified.add(unit)
        else:
            # Imported from something that is not a file on disk — a zipimport
            # member, or a source deleted after it was read. Nothing can be
            # hashed, so it is a named gap: dropping it would read as an
            # import that never happened.
            fileless.add(unit)

    found: dict[str, dict[str, Any]] = {}
    for dist in sorted(dists):
        found[dist] = {
            "identity": METADATA,
            "version": versions.get(dist),
            "digest": _metadata_digest(dist),
        }

    for unit, paths in sorted(unowned.items()):
        roots = tuple(sorted({_root_of(path) for path in paths}))
        digest, count = _content_digest(roots)
        # Content second, so it wins a name collision with a metadata entry:
        # it is a statement about bytes that were read, which outranks a
        # statement about bytes an installer once wrote.
        found[unit] = {"identity": CONTENT, "version": None, "digest": digest, "files": count}

    for name in fileless - identified:
        found.setdefault(name, {"identity": UNIDENTIFIED, "version": None, "digest": None})

    # SPEC-report §8 rule 1: a derived collection is ordered by a stated key.
    return dict(sorted(found.items()))


def _is_unresolved_namespace(name: str, module: Any, skip: str | None) -> bool:
    """True for an import with no file that no other mechanism will account for.

    A namespace package has `__file__ is None` and real submodules elsewhere;
    `_python_closure` skipped those silently until now. Built-in and frozen
    modules are the interpreter itself and are not gaps. A namespace whose
    search paths lie in the stdlib or in the model's own directory is already
    covered, so naming it as unseen would be a false alarm — and a closure
    that claims a gap it does not have is its own kind of dishonesty.
    """
    if name in sys.builtin_module_names:
        return False
    spec = getattr(module, "__spec__", None)
    if spec is None or spec.origin in ("built-in", "frozen"):
        return False
    locations = [os.path.normpath(str(entry)) for entry in getattr(module, "__path__", []) or []]
    if not locations:
        return False
    return not all(_is_stdlib(p) or (skip is not None and _within(p, skip)) for p in locations)


@cache
def _resolved(filename: str) -> Path:
    """`Path.resolve()`, memoised on the filename.

    A resolve is a realpath syscall chain — 22 µs measured, against ~1500
    modules in a cadquery process. Keying on the filename is sound for the
    same reason it is in `sys.modules` itself: a loaded module's `__file__`
    names one file for the life of the process, and a second target in the
    same run resolves the same names.
    """
    return Path(filename).resolve()


def _root_of(path: Path) -> Path:
    """The outermost package directory a file belongs to, or the file itself.

    Walking up while `__init__.py` exists stops at a namespace boundary, so
    `google/protobuf/descriptor.py` roots at `google/protobuf` — the unit that
    a distribution actually owns — rather than at the shared `google`
    directory that four distributions write into.
    """
    root = path
    while (root.parent / "__init__.py").is_file():
        root = root.parent
    return root


@cache
def _stdlib_dir() -> str:
    """The directory holding `os.py`.

    Not `sysconfig.get_paths()["platstdlib"]`, which in a venv is
    `venv/lib/pythonX.Y` — the **parent** of `site-packages`. Excluding the
    stdlib by that path excludes every installed distribution too: the
    prototype that did so reported zero imports, and its tests passed.
    """
    return os.path.realpath(Path(os.__file__).parent)


@cache
def _site_dirs() -> tuple[str, ...]:
    paths = sysconfig.get_paths()
    return tuple(
        sorted({os.path.realpath(paths[key]) for key in ("purelib", "platlib") if paths.get(key)})
    )


def _within(path: str, directory: str) -> bool:
    """`Path.is_relative_to`, by string prefix.

    Called several times for each of ~1200 loaded modules, and pathlib's own
    implementation walks `parents`: it was 0.28 s of a 0.30 s profile.
    """
    return path == directory or path.startswith(directory + os.sep)


def _is_stdlib(path: str) -> bool:
    """Stdlib is where `os.py` lives, minus the site directories under it.

    The exception is not decoration: `purelib` can sit *inside* the stdlib
    directory (`/usr/lib/python3.13/site-packages`), and without it every
    installed distribution would be filtered away as stdlib.
    """
    return _within(path, _stdlib_dir()) and not any(_within(path, site) for site in _site_dirs())


def _keep_row(path: str, digest: str) -> bool:
    """Which RECORD rows describe the installed code, and only that.

    - `../`: console scripts, whose generated shebang embeds the venv's
      absolute path. Across five independently created fleet venvs the raw
      RECORD digest for numpy 2.5.2 differed in **all five**, entirely on
      these rows. Unfiltered, the digest is per-machine noise and the field
      is worse than useless.
    - `*.dist-info/*`: the record of the *install*, not of the code.
      `direct_url.json` carries the URL or local path a wheel came from and
      `INSTALLER` names pip or uv, so two correct installs of one wheel
      disagree.
    - `.pyc`: compiled on first import, absent until then.
    - Rows with no hash: RECORD itself, and directory entries.
    """
    return bool(digest) and not (
        path.startswith("../")
        or path.endswith(_BYTECODE)
        or ".dist-info/" in path
        or ".egg-info/" in path
    )


@cache
def _record_index() -> tuple[
    dict[str, str], dict[str, tuple[tuple[str, str], ...]], dict[str, str]
]:
    """One pass over every installed RECORD: file → distribution, and its rows.

    **Every row is indexed, not `row[0].split("/")[0]`.** First-segment
    attribution makes any two distributions that share a top-level directory
    claimants of each other's modules — `zope.*`, `google.*` (protobuf and
    google-auth), `sphinxcontrib.*`, `ruamel.*`, `backports.*`, `jaraco.*` —
    and this repo's own venv holds a five-way `trame` collision that agrees
    only by accident. It was measured recording a distribution whose
    `__init__.py` raises `RuntimeError('beta was never imported')`. Exact rows
    cost about 14 ms more than first segments — the whole pass is 62.5 ms cold
    / 57.9 ms warm over the fleet's 84 distributions, 100.9 / 65.2 over this
    repo's 114 — and the difference bought is attribution rather than a
    plausible guess.

    Where two distributions claim one file — a venv with two providers of one
    package, which `just ocp-guard` exists to refuse — the first wins, the
    same resolution order `importlib.metadata.version()` and
    `environment.packages` already use, so the three cannot disagree.

    Cached per process: nothing installs a distribution between two targets of
    one run. The MCP layer runs the CLI per call and so pays it every time.
    """
    from importlib.metadata import distributions

    owners: dict[str, str] = {}
    rows: dict[str, tuple[tuple[str, str], ...]] = {}
    versions: dict[str, str] = {}
    for dist in distributions():
        metadata = dist.metadata
        name, version = metadata["Name"], metadata["Version"]
        if not name or name in rows:
            continue
        record = dist.read_text("RECORD")
        if record is None:
            continue
        base = os.path.realpath(str(dist.locate_file(""))) + os.sep
        kept: list[tuple[str, str]] = []
        for row in csv.reader(record.splitlines()):
            if len(row) < 2 or not _keep_row(row[0], row[1]):
                continue
            kept.append((row[0], row[1]))
            if row[0].endswith(_IMPORTABLE):
                # Only files an import can load need an owner — the index
                # answers "was this loaded file installed", and half the rows
                # in a wheel are data, stubs and licences. The digest below
                # still covers every one of them.
                # RECORD paths are `/`-separated by PEP 376; `__file__` is not.
                owners.setdefault(base + (row[0] if _POSIX else row[0].replace("/", os.sep)), name)
        rows[name] = tuple(sorted(kept))
        if version:
            versions[name] = version
    return owners, rows, versions


@cache
def _metadata_digest(name: str) -> str:
    """Over the filtered RECORD rows, `path,hash` per line, sorted by path.

    The installer's account of the distribution, not a re-reading of the
    bytes: it is what makes this tier ~0.3 ms. SPEC-report §7.1 is already
    explicit that a digest is comparison-based tamper *evidence*, not
    tamper-proofing, and the ownership check bounds what it can be wrong
    about to "site-packages was edited after install".
    """
    rows = _record_index()[1][name]
    body = "\n".join(f"{path},{digest}" for path, digest in rows)
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


@cache
def _content_digest(roots: tuple[Path, ...]) -> tuple[str, int]:
    """Hash the bytes under `roots`, whole package trees, not the loaded files.

    The tree, because a module reads its data files and a package that lost
    one is a different package; and because the loaded set is whatever this
    run happened to touch, which would make the digest depend on the
    parameters rather than on the code. The fleet's checkout hashes 17 files,
    more than the run imported.

    Over sorted content hashes rather than paths, as `_closure` does and for
    the same reason: two checkouts of one tree at different locations must
    compare equal.

    Bytecode is excluded — it is derived, it appears on first import, and a
    digest that moved because a `__pycache__` was written would report a
    change that did not happen.

    Memoised on the roots, which is safe for the same reason `sys.modules` is:
    the bytes were read into the interpreter before this ran, so a later
    target in the same process imported the same ones.
    """
    members: list[Path] = []
    for root in roots:
        if root.is_file():
            members.append(root)
            continue
        members.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix not in _BYTECODE and "__pycache__" not in path.parts
        )
    hashes = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in members)
    return "sha256:" + hashlib.sha256("".join(hashes).encode()).hexdigest(), len(hashes)
