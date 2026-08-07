"""Build a part from a Python CAD module — build123d or CadQuery.

One adapter for both, because both produce OCCT shapes and the difference is a
handle rewrap at the door (D3). What varies is only the object the model
function hands back, and `adopt` normalises that.

The model is invoked as `method(**params)`. That rule is deliberately dumb: no
signature inspection, no constructing a spec dataclass from the parameter names,
no guessing. A model using a different calling convention gets a three-line
adapter in the contract, which is legible, whereas a tool that infers the
convention is not.

Spec: SPEC-backend.md section 4, SPEC-contract.md section 3.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..backend import BuildError

__all__ = ["PyCADSource", "adopt", "build"]


@dataclass(frozen=True, slots=True)
class PyCADSource:
    """A Python CAD module, the callable to invoke, and its parameters."""

    path: Path
    engine: str  # "build123d" | "cadquery"
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None


def _shape_map() -> dict[Any, Any]:
    """TopoDS shape type -> build123d wrapper.

    `build123d.Shape.cast` looks like the obvious way to do this and is not: in
    0.11.1 it returns **None** for a plain TopoDS_Solid. Dispatching on
    `ShapeType()` is explicit and works. Wrapping with the wrong class is worse
    than failing — `Compound(topods_solid)` constructs happily and reports
    volume 0.
    """
    import build123d as bd

    # OCP ships compiled bindings with incomplete stubs, so pyright cannot see
    # these symbols. They exist at runtime and are covered by tests.
    from OCP.TopAbs import TopAbs_ShapeEnum as E  # pyright: ignore[reportAttributeAccessIssue]

    return {
        E.TopAbs_COMPOUND: bd.Compound,
        E.TopAbs_COMPSOLID: bd.Compound,
        E.TopAbs_SOLID: bd.Solid,
        E.TopAbs_SHELL: bd.Shell,
        E.TopAbs_FACE: bd.Face,
        E.TopAbs_WIRE: bd.Wire,
        E.TopAbs_EDGE: bd.Edge,
        E.TopAbs_VERTEX: bd.Vertex,
    }


def adopt(obj: Any) -> Any | BuildError:
    """Normalise a build123d or CadQuery result into a build123d shape.

    A CadQuery `Workplane` is reduced with `.val()`; anything exposing
    `.wrapped` is rewrapped by shape type. The rewrap is a handle operation, not
    a geometric rebuild, so nothing is converted or lost.
    """
    from OCP.TopoDS import TopoDS_Shape  # pyright: ignore[reportAttributeAccessIssue]

    # CadQuery Workplane -> its single value. `.val()` collapses a stack, and a
    # multi-solid stack is already a Compound by then.
    if hasattr(obj, "val") and callable(obj.val):
        try:
            obj = obj.val()
        except Exception as exc:  # noqa: BLE001 - engine-specific failure surfaces as a build error
            return BuildError(f"could not reduce CadQuery result: {exc}")

    raw = getattr(obj, "wrapped", obj)
    if not isinstance(raw, TopoDS_Shape):
        return BuildError(
            f"model returned {type(obj).__name__}, which is not a build123d or CadQuery shape"
        )
    if raw.IsNull():
        return BuildError("model returned a null shape")

    wrapper = _shape_map().get(raw.ShapeType())
    if wrapper is None:
        return BuildError(f"unsupported shape type: {raw.ShapeType()}")
    shape = wrapper(raw)

    # A cut that consumes its own operand -- `Box(s) - Box(2s)`, an ordinary slip
    # -- yields a non-null but *empty* Compound, which `IsNull()` does not catch.
    # It then measured as a legitimate part: bbox (0,0,0), area 0.0, watertight
    # False, all reported exact, and a contract asserting only those three passed
    # green on a part that does not exist.
    #
    # The test is "no vertices", not "no faces". A Wire or an Edge has no faces
    # and is still real geometry that bbox and area answer for honestly; only a
    # shape with nothing in it at all has no vertices. D17 part 2 forbids the
    # broader gate.
    if not shape.vertices():
        return BuildError(
            "model returned a shape containing no geometry "
            "(an empty compound -- did a cut consume the whole part?)"
        )
    return shape


def _load(path: Path) -> Any:
    module_name = f"_partspec_model_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load model: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    # The model's own directory goes on the path so it can import helpers beside
    # it — the same courtesy the contract loader extends.
    parent = str(path.resolve().parent)
    added = parent not in sys.path
    if added:
        sys.path.insert(0, parent)
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            sys.path.remove(parent)
    return module


def build(source: PyCADSource) -> Any | BuildError:
    """Import the model module, call it, and adopt the result."""
    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}")

    try:
        module = _load(source.path)
    except Exception as exc:  # noqa: BLE001 - any import failure is a build failure
        return BuildError(f"model raised on import: {type(exc).__name__}: {exc}")

    name = source.method or "make_part"
    factory = getattr(module, name, None)
    if factory is None:
        public = sorted(
            n for n in vars(module) if not n.startswith("_") and callable(vars(module)[n])
        )
        return BuildError(
            f"{source.path} has no callable named {name!r}",
            hint=f"available: {', '.join(public) or 'none'}",
        )

    try:
        result = factory(**source.params)
    except TypeError as exc:
        return BuildError(
            f"calling {name}(**params) failed: {exc}",
            hint="partspec calls the model as method(**params); wrap a differently-shaped "
            "signature in a small adapter function in the contract",
        )
    except Exception as exc:  # noqa: BLE001 - modelling failure is a build failure
        return BuildError(f"{name}() raised: {type(exc).__name__}: {exc}")

    return adopt(result)


def version(engine: str) -> str:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    try:
        return pkg_version(engine)
    except PackageNotFoundError:
        return "unknown"
