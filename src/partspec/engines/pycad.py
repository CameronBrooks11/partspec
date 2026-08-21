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
from ..install import install_hint

__all__ = ["PyCADSource", "adopt", "build", "invalidate_model_modules", "record_model_modules"]


_LOADED_MODEL_MODULES: dict[str, set[str]] = {}
"""Resolved model directory -> module names its builds added to `sys.modules`.

A registry of what each build actually imported, not a directory sweep: an
early draft evicted "everything whose file sits under the model's directory",
and a model path that resolves near the repo root made that a grenade — it
evicted the editable-installed partspec itself and the test suite's own
modules, mid-session. Only what a build introduced can be stale because of
that build, so only that is remembered and evicted."""


def record_model_modules(model_path: Path, before: set[str]) -> None:
    """Remember which modules this build added from the model's directory."""
    root = model_path.resolve().parent
    added: set[str] = set()
    for name in set(sys.modules) - before:
        filename = getattr(sys.modules.get(name), "__file__", None)
        if not filename or "site-packages" in Path(filename).parts:
            # A build's first lazy import of an installed package (OCP
            # submodules, typically) is process-wide state, not model state;
            # evicting a C extension for re-import buys nothing and risks
            # duplicate-class identity bugs.
            continue
        if name == "partspec" or name.startswith("partspec."):
            # Never this package. An EDITABLE install's source is not under
            # site-packages, so the filter above misses it, and a contract
            # sitting at the repo root makes `partspec.*` relative to the
            # model root — the registry then evicts partspec's own modules
            # and the next import rebuilds classes that fail `isinstance`
            # against the ones already held. PR #147's review demonstrated
            # the duplicate-class break live. The registry was described as
            # preventing this; it did not, and now it does.
            continue
        try:
            if Path(filename).resolve().is_relative_to(root):
                added.add(name)
        except OSError:
            continue
    if added:
        _LOADED_MODEL_MODULES.setdefault(str(root), set()).update(added)


def invalidate_model_modules(model_path: Path) -> None:
    """Evict the modules this model's builds imported from beside it.

    `sys.modules` caches a model's helpers top-level, so a later build in the
    same process that imports an edited helper gets the *previous* version —
    a stale build reported as fresh, with a closure digest computed from the
    file on disk that never reached the interpreter (POST-V0 §8, #29). PR
    #101's review demonstrated it live: two models with same-named helpers in
    one process, and the second silently built with the first's.

    Called after every Python-engine run rather than only between batch
    targets, because the hazard is a property of the process, not of the
    batch verb — a library caller or a test suite hits it identically.
    Evicting is safe for live objects (existing references keep working; only
    the next import re-reads the file).

    Two ceilings beneath this function's reach, stated rather than hidden.
    CPython validates a cached `.pyc` by (mtime seconds, size), so an edit
    that changes neither — same byte count, within the same second — serves
    stale bytecode to ANY interpreter, fresh process included; the closure
    digest still changes (it reads the file), which is how such a run is
    caught on comparison. And a module a caller imported BEFORE any build —
    a same-named helper from an unrelated directory, or the model's own
    helper imported directly by a test — predates every snapshot, so the
    registry never sees it, wherever its file sits, and it shadows the fresh
    import for as long as the process lives.
    """
    root = str(model_path.resolve().parent)
    for name in _LOADED_MODEL_MODULES.pop(root, set()):
        sys.modules.pop(name, None)


class _BuildTimeout(Exception):
    """Raised by the SIGALRM handler the first time the budget expires.

    Ordinary `Exception`, so a model's own `except Exception` handlers behave
    no differently because a budget exists — but that also means a model's
    perfectly mundane `try/except Exception` can swallow it. Two guards make
    that survivable rather than silent: the window records that it fired (so a
    swallowed alarm still voids the build's result), and the timer re-fires,
    escalating to `_BuildTimeoutHard` (adversarial review of PR #100: the
    swallowed alarm produced a green report with zero trace, and a
    swallow-loop hung the process past its budget forever)."""


class _BuildTimeoutHard(BaseException):
    """The second and every later firing of an already-swallowed alarm.

    `BaseException`, so `except Exception` cannot swallow it — this is what
    turns "the model caught the alarm and kept going" from an unbounded hang
    into a stopped run. A model catching `BaseException` bare in a loop still
    escapes; that sits in the stated ceiling, beside C-kernel hangs."""


class _CannotBound(Exception):
    """A bound was requested where no timer can be armed."""


_ESCALATE_AFTER_S = 1.0
"""Re-fire interval once the budget has expired. The first alarm is a polite
`Exception`; anything still running this long after it has demonstrably eaten
it, and gets the `BaseException` variant."""


@contextmanager
def _time_limit(seconds: float | None):
    """Bound the enclosed block with a real-time alarm; None means no bound.

    Yields a window record whose `"fired"` flag outlives the block — the
    caller MUST consult it, because a model can catch the in-flight exception
    and return something anyway, and a result computed past the budget is not
    a result (a green report from a swallowed alarm is the silence-as-success
    failure verbatim).

    SIGALRM, not a watchdog thread: a thread cannot interrupt the main
    thread's Python frames, while an alarm raises inside them. The stated
    ceiling, in full: a hang inside a C kernel call (an OCCT boolean that
    never returns) is not preemptible in-process; a model that installs its
    own SIGALRM handler, ignores the signal, or catches `BaseException` in a
    loop defeats the alarm; and a non-daemon thread the model leaks keeps the
    *process* alive at exit even though the report is finished and honest.
    Everything short of that — loops, sleeps, recursion, `except Exception`
    cleanup — is covered by the fire-record plus escalation.

    Requesting a bound somewhere it cannot be armed (a non-main thread, a
    platform without SIGALRM, a value the platform timer cannot hold) raises
    `_CannotBound` instead of proceeding unbounded: a budget that silently
    does not exist is the silence-as-success failure in run-control clothing.
    `--timeout 0` is the explicit waiver.
    """
    window = {"fired": False}
    if seconds is None:
        yield window
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
        if window["fired"]:
            raise _BuildTimeoutHard
        window["fired"] = True
        raise _BuildTimeout

    started = time.monotonic()
    outer_delay, outer_interval = signal.getitimer(signal.ITIMER_REAL)
    previous = signal.signal(signal.SIGALRM, _expired)
    try:
        try:
            signal.setitimer(signal.ITIMER_REAL, seconds, _ESCALATE_AFTER_S)
        except (ValueError, OverflowError) as exc:
            raise _CannotBound(
                f"a {seconds:g}s build budget cannot be armed on this platform "
                f"({exc}); pass --timeout 0 to explicitly waive the bound"
            ) from None
        yield window
    finally:
        # Restore rather than merely disarm: a nested window that zeroed the
        # timer would silently unbound its enclosing one.
        if outer_delay > 0:
            remaining = max(outer_delay - (time.monotonic() - started), 1e-6)
            signal.setitimer(signal.ITIMER_REAL, remaining, outer_interval)
        else:
            signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@dataclass(frozen=True, slots=True)
class PyCADSource:
    """A Python CAD module, the callable to invoke, and its parameters."""

    path: Path
    engine: str  # "build123d" | "cadquery"
    params: dict[str, Any] = field(default_factory=dict)
    method: str | None = None


_NO_GEOMETRY = (
    "model returned a shape containing no geometry (an empty {} with no underlying handle)"
)
"""One spelling for the two ways build123d reports nothing at all.

Both carry `produced_nothing`, which is the whole of #271. `a & b` on two
disjoint solids returns an empty `Compound`, so this — not `IsNull()`, and not
the empty CadQuery stack — is what a clearance probe on the OCCT tier actually
hits, and it was the one null result the flag did not reach. `p.empty()` could
therefore not pass for ANY input on that tier, while `SPEC-contract.md` §4.12
said the check "reads the same on either tier".

Setting it changes nothing for a contract that does not declare `empty`: the
flag is read in exactly one place, inside `if empty_specs`, so a null result is
still a hard build failure everywhere else — which is what #237 asked for.
"""


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
    #     .val().Volume()  # 125.0, not 500.0
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
            return BuildError("CadQuery result has nothing on its stack", produced_nothing=True)
    elif hasattr(obj, "val") and callable(obj.val):
        try:
            obj = obj.val()
        except _BuildTimeout:
            raise
        except Exception as exc:  # noqa: BLE001 - engine-specific failure surfaces as a build error
            return BuildError(f"could not reduce CadQuery result: {exc}")

    try:
        raw = getattr(obj, "wrapped", obj)
    except AssertionError:
        # build123d's `.wrapped` property asserts on a shape holding no
        # underlying TopoDS handle — `Compound()` with no children. The
        # assert is the library's; the empty shape is the model's. Same
        # answer as every other empty result: an artifact naming it, never
        # a traceback with empty stdout (#128).
        return BuildError(_NO_GEOMETRY.format(type(obj).__name__), produced_nothing=True)
    if raw is None:
        return BuildError(_NO_GEOMETRY.format(type(obj).__name__), produced_nothing=True)
    if not isinstance(raw, TopoDS_Shape):
        return BuildError(
            f"model returned {type(obj).__name__}, which is not a build123d or CadQuery shape"
        )
    if raw.IsNull():
        return BuildError("model returned a null shape", produced_nothing=True)

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
        # Compiled from source, never from the bytecode cache — the same rule
        # as the contract loader (target.py), for the same reason: a
        # same-length edit within one mtime second re-executes stale bytecode
        # under a fresh source digest. The model's HELPERS still import
        # through the normal machinery and keep that ceiling; the entry file
        # at least is always what is on disk.
        code = compile(path.read_bytes(), str(path), "exec")
        exec(code, module.__dict__)  # noqa: S102 - executing the model IS the build
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

    if not installed:
        try:
            proxy = distribution("cadquery-ocp-proxy").version
        except PackageNotFoundError:
            proxy = None
        if proxy is not None:
            # The OCP ecosystem is here and no concrete provider is: the
            # resolution dropped one that build123d and CadQuery both declare
            # outright. `cadquery-ocp-proxy` is a metadata-only version tracker
            # that ships no OCP itself, so its presence is the breadcrumb, not
            # the cause -- ocpsvg and ocp_gordon depend on it bare.
            #
            # The known way to reach this state is a resolver override, and the
            # known override is THIS REPO'S: `uv pip` reads `[tool.uv]` from the
            # pyproject.toml above the CWD, so any `uv pip install` run from a
            # partspec checkout inherits `override-dependencies` and drops
            # novtk. That is the whole of #109, which spent ten days on record
            # as an upstream uv bug (see the `--no-config` note in the justfile).
            wanted = "cadquery-ocp" if engine == "cadquery" else "cadquery-ocp-novtk"
            return BuildError(
                f"{engine} is not importable: {exc}; no OCP provider is installed "
                f"(cadquery-ocp-proxy {proxy} is present, but it ships no OCP) — "
                f"something dropped {wanted} from the resolution",
                hint=f"{install_hint(wanted)}; if you installed from a partspec "
                f"checkout, `uv pip` applied this repo's [tool.uv] override — "
                f"re-run it with --no-config. See partspec issue #109",
                origin="environment",
            )

    if len(installed) > 1:
        return BuildError(
            f"{engine} could not be imported because two OCP providers are installed "
            f"({', '.join(installed)}); they share the same OCP/ package and one has "
            f"clobbered the other",
            hint=install_hint(
                "--force-reinstall --no-deps cadquery-ocp",
                "--no-deps --reinstall-package cadquery-ocp cadquery-ocp",
            ),
            origin="environment",
        )
    return BuildError(
        f"{engine} is not importable: {exc}",
        hint=install_hint(f"'partspec[{'cadquery' if engine == 'cadquery' else 'occt'}]'"),
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
    # Snapshot around the WHOLE build, not just the module load, so a
    # factory-time lazy import is remembered for invalidation too.
    modules_before = set(sys.modules)
    try:
        return _bounded_build(source, timeout_s, started)
    finally:
        record_model_modules(source.path, modules_before)


def _bounded_build(
    source: PyCADSource, timeout_s: float | None, started: float
) -> Any | BuildError:
    try:
        with _time_limit(timeout_s) as window:
            result = _build(source)
    except (_BuildTimeout, _BuildTimeoutHard):
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

    if window["fired"]:
        # The alarm went off and something caught it — a model's mundane
        # `except Exception`, or a C extension initialising mid-import — and
        # the build went on to return anyway. A result computed past the
        # budget is not a result, and letting it through produced a green
        # report with zero trace of the blown budget (PR #100 review,
        # blocker 1). Whatever came back, including a BuildError blaming
        # something downstream of the alarm, is superseded by the budget.
        elapsed = time.perf_counter() - started
        assert timeout_s is not None
        return BuildError(
            f"the build budget of {timeout_s:g}s expired, was caught inside the build, "
            f"and the run continued to {elapsed:.1f}s; the result is discarded because "
            f"it was computed past the budget",
            origin="environment",
            hint="a legitimately slow model can raise the budget with --timeout or "
            "PARTSPEC_TIMEOUT; --timeout 0 waives it",
        )
    return result


def _missing_module_error(
    exc: ModuleNotFoundError, model_dir: Path, doing: str
) -> BuildError | None:
    """Classify a ModuleNotFoundError: missing wheel, or fault in local code.

    A missing third-party package is a statement about the machine, not the
    part — found live (#78): a `uv sync` dropped an ad-hoc `cqkit` install and
    the dogfood batch reported the design as *disproven*. But import failure
    is genuinely ambiguous: a model reaching into its own helper package for a
    submodule that does not exist IS a model fault.

    The split is the top-level name of the missing module. If something by
    that name sits beside the model — a `helpers/` package whose `helpers.gears`
    is missing — the failure lives in local code and stays `origin="model"`
    (return None; the caller's model-fault path applies). If nothing by that
    name is beside the model, the import could only ever have been satisfied
    by an installed package, so it is `origin="environment"` with the package
    named. The residual ambiguity — a typo'd import of a helper that never
    existed anywhere — is disclosed in the hint rather than adjudicated, since
    no machine evidence distinguishes it from a missing wheel.
    """
    top = (exc.name or "").partition(".")[0]
    if not top:
        return None
    if (model_dir / f"{top}.py").is_file() or (model_dir / top).is_dir():
        return None
    return BuildError(
        f"{doing}: No module named {exc.name!r}, and nothing named {top!r} exists "
        f"beside the model — a missing package is a statement about the machine, "
        f"not the part",
        origin="environment",
        hint=f"install the missing package into this environment; if {exc.name!r} was "
        f"meant to be a helper module beside the model, none is there",
    )


def _build(source: PyCADSource) -> Any | BuildError:
    try:
        __import__(source.engine)
    except ImportError as exc:
        return _engine_import_error(source.engine, exc)

    if not source.path.is_file():
        return BuildError(f"source not found: {source.path}", origin="environment")

    model_dir = source.path.resolve().parent
    try:
        module = _load(source.path)
    except _BuildTimeout:
        raise
    except ModuleNotFoundError as exc:
        missing = _missing_module_error(exc, model_dir, "model raised on import")
        if missing is not None:
            return missing
        return BuildError(f"model raised on import: {type(exc).__name__}: {exc}")
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
    except (KeyboardInterrupt, _BuildTimeout, _BuildTimeoutHard):
        raise
    except ModuleNotFoundError as exc:
        # A lazy `import` inside the factory hitting a missing wheel is the
        # same machine statement as one at module import time.
        missing = _missing_module_error(exc, model_dir, f"{name}() raised on a missing import")
        if missing is not None:
            return missing
        # Reaching here means something by that name IS beside the model —
        # and on this path that is exactly why the import failed: the model's
        # directory is on sys.path during `_load` only, so a helper that
        # imports fine at module top level is unreachable from inside the
        # factory. Without this hint the failure reads as a disproven design
        # with no clue the harness removed the path (PR #101 review).
        return BuildError(
            f"{name}() raised: {type(exc).__name__}: {exc}",
            hint="modules beside the model are importable at import time only — the "
            "model's directory leaves sys.path before the factory runs; import the "
            "helper at module top level instead",
        )
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
