"""Resolve `<module-path>[:<factory>]` to a Part.

The error message is the discovery mechanism: asked for a module with several
part factories, the failure lists them rather than saying "ambiguous". Borrowed
from cad-khana, where the same idea means you never need a separate `list` verb
to find out what a file offers.

Spec: SPEC-contract.md section 2.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from .contract import Part, Source

__all__ = ["Target", "TargetError", "factories", "resolve"]


class TargetError(Exception):
    """The target could not be resolved. Exits 64 and writes no report."""


@dataclass(frozen=True, slots=True)
class Target:
    path: Path
    factory: str | None = None

    @staticmethod
    def parse(spec: str) -> Target:
        head, sep, tail = spec.rpartition(":")
        if sep and tail.isidentifier():
            return Target(Path(head), tail)
        return Target(Path(spec))

    @property
    def slug(self) -> str:
        """Report directory name — distinct per factory so co-located targets
        never clobber each other's report."""
        return self.path.stem if self.factory is None else f"{self.path.stem}-{self.factory}"


def _load(path: Path) -> ModuleType:
    if not path.is_file():
        raise TargetError(f"contract not found: {path}")

    module_name = f"_partspec_contract_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise TargetError(f"could not load contract: {path}")

    module = importlib.util.module_from_spec(spec)
    # Registered before exec so that dataclasses and typing inside the contract
    # can resolve the module by name during import.
    sys.modules[module_name] = module
    # The contract's own directory goes on the path so it can import helpers
    # that live beside it.
    parent = str(path.resolve().parent)
    added = parent not in sys.path
    if added:
        sys.path.insert(0, parent)
    try:
        # Compiled from source, never from the bytecode cache. CPython
        # validates a .pyc by (mtime seconds, size), so a same-length edit
        # within one second re-executes the OLD contract under the NEW
        # contract_digest — an agent's rapid edit loop hits exactly that, and
        # the claims pin (#31) would adjudicate bytecode the file no longer
        # contains. Contracts are small; the pyc saves nothing worth that.
        code = compile(path.read_bytes(), str(path), "exec")
        exec(code, module.__dict__)  # noqa: S102 - executing the contract IS the product
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # BaseException: `sys.exit(0)` at contract import scope is user code
        # choosing our exit status, and it chose green.
        raise TargetError(f"contract raised on import: {type(exc).__name__}: {exc}") from exc
    finally:
        if added:
            sys.path.remove(parent)
    return module


def factories(module: ModuleType) -> tuple[str, ...]:
    """Public callables defined in `module` and annotated `-> Part`.

    The return annotation is the declaration: a helper that happens to build a
    Part but is not annotated stays private to the contract, which is usually
    what the author meant.
    """
    found: list[str] = []
    for name, obj in vars(module).items():
        if name.startswith("_") or not callable(obj):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        try:
            hints = inspect.signature(obj).return_annotation
        except (TypeError, ValueError):
            continue
        if hints is Part or hints in ("Part", "partspec.Part"):
            found.append(name)
    return tuple(found)


def resolve(spec: str) -> tuple[Part, Target]:
    """Resolve a target string to a Part.

    Records whatever the contract's import pulled in from beside it, so a
    later `invalidate_model_modules(target.path)` can evict it. The recording
    used to live only in `cli._cmd_check`, which meant a library caller —
    or a test — that reached `resolve()` directly left its siblings cached
    under bare names like `claims` with nothing tracking them. The deslop
    audit found exactly that: an exemplar's `claims.py` outlived its test and
    answered for a later one in a different directory, breaking the five
    tests that exist to prove that cannot happen. Bookkeeping belongs with
    the import that causes it.

    In a `finally`, because the case that most needs the record is the one
    where the contract imports its sibling and THEN raises (#114 path 1):
    recording after a successful `_load` leaves the leak untracked on
    exactly the path `cli._cmd_check`'s own `finally` was written for.
    """
    from .engines.pycad import record_model_modules

    target = Target.parse(spec)
    modules_before = set(sys.modules)
    try:
        module = _load(target.path)
    finally:
        record_model_modules(target.path, modules_before)
    available = factories(module)

    if target.factory is not None:
        factory = getattr(module, target.factory, None)
        if factory is None:
            raise TargetError(
                f"{target.path}: no factory named {target.factory!r}. "
                f"Available: {', '.join(available) or 'none'}"
            )
    elif len(available) == 1:
        factory = getattr(module, available[0])
    elif not available:
        raise TargetError(
            f"{target.path} declares no part factories. A factory is a public "
            f"function annotated `-> Part`."
        )
    else:
        raise TargetError(
            f"{target.path} declares several part factories, so one must be named: "
            + ", ".join(f"{target.path}:{name}" for name in available)
        )

    # Called with its own defaults — a factory's defaults are the master design.
    part = factory()
    if not isinstance(part, Part):
        raise TargetError(
            f"{target.path}:{getattr(factory, '__name__', '?')} returned "
            f"{type(part).__name__}, not a Part"
        )
    part.source = _anchor(part.source, target.path.resolve().parent)
    return part, target


def _anchor(source: Source, contract_dir: Path) -> Source:
    """Resolve a relative source path against the contract's directory.

    `openscad("spacer.scad")` in a contract means the file sitting beside it, not
    a file relative to wherever the user happened to run the command from. The
    alternative — resolving against the process CWD — makes a contract work or
    fail depending on the shell's history, which is exactly the kind of
    action-at-a-distance a reproducibility tool should not ship with.
    """
    if source.path.is_absolute():
        return source
    return replace(source, path=(contract_dir / source.path).resolve())
