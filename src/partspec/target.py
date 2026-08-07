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
        spec.loader.exec_module(module)
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
    """Resolve a target string to a Part."""
    target = Target.parse(spec)
    module = _load(target.path)
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
