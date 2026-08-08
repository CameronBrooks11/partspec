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
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ..backend import BuildError

__all__ = ["PyCADSource", "adopt", "build"]


class _BuildTimeout(Exception):
    """Raised by the SIGALRM handler when the build budget expires.

    Ordinary `Exception`, so every broad catch inside the build path needs an
    explicit re-raise clause ahead of it — and has one. Making it a
    `BaseException` would instead dodge the model's own `except Exception`
    handlers, which is behaviour a *model* should never observe differently
    because a budget exists."""


class _CannotBound(Exception):
    """A bound was requested where no timer can be armed."""


@contextmanager
def _time_limit(seconds: float | None):
    """Bound the enclosed block with a real-time alarm; None means no bound.

    SIGALRM, not a watchdog thread: a thread cannot interrupt the main thread's
    Python frames, while an alarm raises inside them. The known ceiling is
    shared by both approaches and stated rather than hidden: the interpreter
    delivers the exception between bytecodes, so a hang inside a C kernel call
    (an OCCT boolean that never returns) is not preemptible in-process. The
    bound covers everything the model does in Python — imports, loops, sleeps,
    recursion — which is where a broken model actually spends forever.

    Requesting a bound somewhere it cannot be armed (a non-main thread, a
    platform without SIGALRM) raises `_CannotBound` instead of proceeding
    unbounded: a budget that silently does not exist is the silence-as-success
    failure in run-control clothing. `--timeout 0` is the explicit waiver.
    """
    if seconds is None:
        yield
        return
    if not hasattr(signal, "SIGALRM"):
        raise _CannotBound(
            f"a {seconds:g}s build budget was requested but this platform has no "
            f"SIGALRM to enforce it; pass --timeout 0 to explicitly waive the bound"
        )
    if threading.current_thread() is not threading.main_thread():
        raise _CannotBound(
            f"a {seconds:g}s build budget was requested off the main thread, where "
            f"no alarm can be armed; pass --timeout 0 to explicitly waive the bound"
        )

    def _expired(signum: int, frame: Any) -> None:
        raise _BuildTimeout

    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


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

    A CadQuery `Workplane` is reduced over its whole stack — one value is taken
    as-is, several become a Compound — and anything exposing `.wrapped` is
    rewrapped by shape type. The rewrap is a handle operation, not a geometric
    rebuild, so nothing is converted or lost.
    """
    from OCP.TopoDS import TopoDS_Shape  # pyright: ignore[reportAttributeAccessIssue]

    # CadQuery Workplane -> its value(s).
    #
    # `.val()` returns the *first* item on the stack, and the comment that used
    # to sit here claimed "a multi-solid stack is already a Compound by then".
    # It is not. That holds only for the default `combine=True`; build four
    # bodies with `combine=False` and the stack is four separate Solids, of
    # which `.val()` silently kept one:
    #
    #     w = cq.Workplane('XY').rect(20, 20, forConstruction=True) \
    #           .vertices().box(5, 5, 5, combine=False)
    #     len(w.vals())  # 4
    #     .val().volume  # 125.0, not 500.0
    #
    # So `solid_count(4)` measured 1 and `volume` measured a quarter of the
    # part, both exact, on three quarters of the model quietly discarded.
    if hasattr(obj, "vals") and callable(obj.vals):
        try:
            # `vals()` is untyped on the CadQuery stubs, so it comes back as
            # `object`; the cast is about the stub, not about the runtime.
            stack = cast("list[Any]", obj.vals())
        except _BuildTimeout:
            raise
        except Exception as exc:  # noqa: BLE001 - engine-specific failure surfaces as a build error
            return BuildError(f"could not reduce CadQuery result: {exc}")
        if len(stack) > 1:
            import cadquery as cq

            obj = cq.Compound.makeCompound(stack)
        elif stack:
            obj = stack[0]
        else:
            return BuildError("CadQuery result has nothing on its stack")
    elif hasattr(obj, "val") and callable(obj.val):
        try:
            obj = obj.val()
        except _BuildTimeout:
            raise
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


_OCP_PROVIDERS = ("cadquery-ocp", "cadquery-ocp-novtk")


def _engine_import_error(engine: str, exc: ImportError) -> BuildError:
    """Turn an engine import failure into something a reader can act on.

    The failure this exists for is silent until it is fatal. `cadquery-ocp` and
    `cadquery-ocp-novtk` both install the same top-level `OCP/` package and
    neither pip nor uv detects the conflict, so whichever lands last wins. When
    novtk wins, `OCP.IVtkOCC` loses its VTK bindings and CadQuery cannot import
    at all:

        ImportError: cannot import name 'IVtkOCC_Shape' from 'OCP.IVtkOCC'

    This repo drops novtk with a `[tool.uv] override-dependencies` marker, but
    that is a workspace setting -- it is not carried in wheel metadata, so a
    plain `pip install partspec[occt,cadquery]` reproduces the clobber with no
    override in scope. The guard therefore has to live in the code, not only in
    the lockfile.
    """
    from importlib.metadata import PackageNotFoundError, distribution

    installed = []
    for name in _OCP_PROVIDERS:
        try:
            installed.append(f"{name} {distribution(name).version}")
        except PackageNotFoundError:
            continue

    if len(installed) > 1:
        return BuildError(
            f"{engine} could not be imported because two OCP providers are installed "
            f"({', '.join(installed)}); they share the same OCP/ package and one has "
            f"clobbered the other",
            hint="pip install --force-reinstall --no-deps cadquery-ocp",
            origin="environment",
        )
    return BuildError(
        f"{engine} is not importable: {exc}",
        hint=f"pip install 'partspec[{'cadquery' if engine == 'cadquery' else 'occt'}]'",
        origin="environment",
    )


def build(source: PyCADSource, *, timeout_s: float | None = None) -> Any | BuildError:
    """Import the model module, call it, and adopt the result — within budget.

    `timeout_s` is already resolved (None = unbounded, a number = the bound);
    the None-means-default rule lives in `effective_timeout`. The window covers
    the model's import, the factory call and adoption together, because a model
    can hang in any of them and the reader is owed one rule, not three.
    """
    started = time.perf_counter()
    try:
        with _time_limit(timeout_s):
            return _build(source)
    except _BuildTimeout:
        elapsed = time.perf_counter() - started
        assert timeout_s is not None  # the alarm only exists when a bound does
        return BuildError(
            f"the model build was stopped after {elapsed:.1f}s against its {timeout_s:g}s budget",
            origin="environment",
            hint="a legitimately slow model can raise the budget with --timeout or "
            "PARTSPEC_TIMEOUT; --timeout 0 waives it",
        )
    except _CannotBound as exc:
        return BuildError(str(exc), origin="environment")


def _build(source: PyCADSource) -> Any | BuildError:
    try:
        __import__(source.engine)
    except ImportError as exc:
        return _engine_import_error(source.engine, exc)

    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}", origin="environment")

    try:
        module = _load(source.path)
    except _BuildTimeout:
        raise
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
    except (KeyboardInterrupt, _BuildTimeout):
        raise
    except BaseException as exc:  # noqa: BLE001 - modelling failure is a build failure
        # BaseException for the same reason as the contract path: a model that
        # calls sys.exit() must not get to pick partspec's exit code.
        return BuildError(f"{name}() raised: {type(exc).__name__}: {exc}")

    return adopt(result)


def version(engine: str) -> str:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    try:
        return pkg_version(engine)
    except PackageNotFoundError:
        return "unknown"
