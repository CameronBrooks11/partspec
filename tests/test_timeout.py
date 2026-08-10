"""Bounded builds (#46): a run terminates, and a blown budget is not a verdict.

Every consumer of a run assumes it ends — a bounded repair loop with an
unbounded build step is a stall, not a loop. The other half is adjudication: a
build stopped by a stopwatch disproves nothing about the part, so it must land
on `verdict: "error"` with `build_origin: "environment"`, never on a failing
`builds` check.
"""

from __future__ import annotations

import contextlib
import signal
import threading
import time
from pathlib import Path

import pytest
from support import report_of

from partspec.backend import DEFAULT_TIMEOUT_S, effective_timeout
from partspec.cli import main
from partspec.engines.pycad import _BuildTimeout, _BuildTimeoutHard, _CannotBound, _time_limit


def _sleeping_target(tmp_path: Path) -> str:
    """A build123d contract whose model sleeps far past any test budget."""
    (tmp_path / "model.py").write_text("import time\n\n\ndef make_part():\n    time.sleep(30)\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('sleeper', build123d('model.py'))\n"
        "    p.volume(min=1.0)\n"
        "    return p\n"
    )
    return f"{spec}:make"


# --------------------------------------------------------------------------
# the mapping and the window
# --------------------------------------------------------------------------


def test_the_timeout_mapping_is_one_rule_for_both_tiers():
    assert effective_timeout(None) == DEFAULT_TIMEOUT_S
    # The number itself, not just the mapping. Every other assertion here is
    # relative to the constant, so it could move by any factor unnoticed — and
    # the default build budget is a product decision (the module docstring's
    # "a bounded repair loop with an unbounded build step is a stall"), not an
    # implementation detail.
    assert DEFAULT_TIMEOUT_S == 300.0, "five minutes; changing it is a decision, not a tweak"
    assert effective_timeout(0) is None, "0 is the explicit waiver"
    assert effective_timeout(2.5) == 2.5


def test_the_window_interrupts_a_python_level_hang():
    started = time.monotonic()
    with pytest.raises(_BuildTimeout), _time_limit(0.05):
        time.sleep(5)
    assert time.monotonic() - started < 2


def test_the_window_is_disarmed_and_the_handler_restored_afterwards():
    """A budget must not outlive its build: an alarm left armed would fire in
    the middle of geometry checks and be blamed on whatever ran there."""
    before = signal.getsignal(signal.SIGALRM)
    with _time_limit(0.05):
        pass
    time.sleep(0.1)  # would raise here if the timer survived the block
    assert signal.getsignal(signal.SIGALRM) is before


def test_no_budget_means_no_alarm():
    with _time_limit(None):
        pass


def test_a_swallowed_alarm_is_recorded_on_the_window():
    """The window's fire-record is what voids a result computed past the
    budget — without it, a model's mundane `except Exception` produced a green
    report with zero trace of the blown budget (PR #100 review, blocker 1)."""
    # The suppress is exactly what an ordinary model cleanup handler does.
    with _time_limit(0.05) as window, contextlib.suppress(_BuildTimeout):
        time.sleep(5)
    assert window["fired"]


def test_a_swallowing_loop_is_escalated_past_except_exception():
    """A loop that eats every Exception must not turn the bound into a hang
    (PR #100 review, blocker 2): the re-fired alarm is a BaseException.

    The loop is bounded rather than `while True` so a broken escalation makes
    this test FAIL with "DID NOT RAISE" in seconds instead of hanging the
    suite until a CI job timeout — a hang is itself a silent signal."""
    started = time.monotonic()
    # PT012/BLE001 suppressed deliberately: the multi-statement block and the
    # blind except ARE the fixture. This reproduces a model that catches
    # everything in a loop, which is what defeats a single SIGALRM and why the
    # escalation to BaseException exists (PR #100 review, blocker 1).
    with pytest.raises(_BuildTimeoutHard), _time_limit(0.05):  # noqa: PT012
        for _ in range(50):
            try:
                time.sleep(0.2)
            except Exception:  # noqa: BLE001 - the swallowing loop is the point
                continue
    assert time.monotonic() - started < 10


def test_an_unarmable_budget_restores_the_handler():
    """setitimer overflow must not leak the window's handler into the process
    (PR #100 review, finding 4): a later stray alarm would raise mid-run."""
    before = signal.getsignal(signal.SIGALRM)
    with pytest.raises(_CannotBound), _time_limit(1e300):
        pass
    assert signal.getsignal(signal.SIGALRM) is before


def test_a_nested_window_restores_the_outer_bound():
    """An inner window that completes must hand the alarm back to its
    enclosing window, not silently unbound it (PR #100 review, finding 5)."""
    started = time.monotonic()
    # PT012: the nesting IS the assertion — an inner window completing, then
    # the outer bound still firing. It cannot be one statement.
    with pytest.raises(_BuildTimeout), _time_limit(0.5):  # noqa: PT012
        with _time_limit(0.05):
            pass  # completes without firing
        time.sleep(5)  # the OUTER bound must still stop this
    elapsed = time.monotonic() - started
    # BOTH bounds, because `< 3` alone cannot tell the two outcomes apart. If the
    # inner 0.05s window leaked its alarm instead of restoring the outer one, the
    # sleep is cut at ~0.05s, `_BuildTimeout` raises anyway, and an upper-bound-only
    # assertion passes on the exact bug the test is named for. The floor is what
    # distinguishes "the outer window fired" from "an inner leak fired early".
    assert elapsed >= 0.4, f"fired at {elapsed:.3f}s — an inner alarm leaked"
    assert elapsed < 3, f"the outer bound did not stop the sleep ({elapsed:.3f}s)"


def test_a_bound_off_the_main_thread_is_refused_not_silently_dropped():
    """An unarmable budget must fail loudly: a bound that silently does not
    exist is the silence-as-success failure in run-control clothes."""
    caught: list[BaseException] = []

    def attempt() -> None:
        try:
            with _time_limit(1):
                pass
        except _CannotBound as exc:
            caught.append(exc)

    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join()
    assert caught, "the bound was requested and silently not enforced"
    assert "main thread" in str(caught[0]) and "--timeout 0" in str(caught[0])


# --------------------------------------------------------------------------
# the CLI: the value the user chose is the value that applies
# --------------------------------------------------------------------------


def test_a_sleeping_model_is_stopped_and_reported_as_error(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    out = tmp_path / "out"
    started = time.monotonic()
    code = main(
        ["check", _sleeping_target(tmp_path), "--timeout", "1", "--quiet", "--out", str(out)]
    )
    assert code == 4, "a blown budget is error, never a failing part"
    assert time.monotonic() - started < 25, "the CLI value applied, not DEFAULT_TIMEOUT_S"

    report = report_of(out)
    assert report["verdict"] == "error"
    assert report["build_origin"] == "environment"
    assert "against its 1s budget" in report["error"]
    assert report["invocation"]["timeout_s"] == 1.0
    statuses = {c["kind"]: c["status"] for c in report["checks"]}
    assert statuses["volume"] == "skipped"
    assert statuses.get("builds") != "fail", "a stopwatch disproves nothing about the part"


def test_the_environment_variable_supplies_the_budget(tmp_path: Path, monkeypatch):
    pytest.importorskip("build123d", reason="occt extra not installed")
    monkeypatch.setenv("PARTSPEC_TIMEOUT", "1")
    out = tmp_path / "out"
    assert main(["check", _sleeping_target(tmp_path), "--quiet", "--out", str(out)]) == 4
    assert report_of(out)["invocation"]["timeout_s"] == 1.0


def test_the_flag_beats_the_environment(tmp_path: Path, monkeypatch):
    pytest.importorskip("build123d", reason="occt extra not installed")
    monkeypatch.setenv("PARTSPEC_TIMEOUT", "600")
    out = tmp_path / "out"
    code = main(
        ["check", _sleeping_target(tmp_path), "--timeout", "1", "--quiet", "--out", str(out)]
    )
    assert code == 4
    assert report_of(out)["invocation"]["timeout_s"] == 1.0


def test_measure_is_bounded_by_the_same_flag(tmp_path: Path, capsys):
    pytest.importorskip("build123d", reason="occt extra not installed")
    code = main(["measure", _sleeping_target(tmp_path), "--timeout", "1"])
    assert code == 4
    assert "budget" in capsys.readouterr().err


def test_a_garbage_environment_variable_is_a_usage_error(tmp_path: Path, monkeypatch, capsys):
    """Refused by name, not silently ignored: a machine-level bound that
    quietly stopped applying is an unbounded run wearing a configured one's
    clothes."""
    monkeypatch.setenv("PARTSPEC_TIMEOUT", "soon")
    code = main(["check", _sleeping_target(tmp_path), "--quiet", "--out", str(tmp_path / "out")])
    assert code == 64
    assert "PARTSPEC_TIMEOUT" in capsys.readouterr().err


def test_a_negative_flag_is_a_usage_error(tmp_path: Path):
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "spec.py:make", "--timeout", "-3"])
    assert excinfo.value.code == 64


def test_an_astronomical_flag_is_a_usage_error_not_a_traceback(tmp_path: Path):
    """1e300 overflows the platform timer; refused at the door (PR #100
    review, finding 4), not surfaced as an OverflowError traceback."""
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "spec.py:make", "--timeout", "1e300"])
    assert excinfo.value.code == 64


def test_a_model_that_swallows_the_alarm_cannot_report_green(tmp_path: Path):
    """The review's blocker 1, as a regression test: an over-budget model
    whose mundane `except Exception` ate the alarm returned a valid shape and
    the run reported PASS with `timeout_s` recorded as if it had governed."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "model.py").write_text(
        "import time\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    try:\n"
        "        time.sleep(10)\n"
        "    except Exception:\n"
        "        pass\n"
        "    return Box(1, 1, 1)\n"
    )
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('swallower', build123d('model.py'))\n"
        "    p.volume(min=0.5)\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    started = time.monotonic()
    code = main(["check", f"{spec}:make", "--timeout", "1", "--quiet", "--out", str(out)])
    assert code == 4, "a result computed past the budget is not a result"
    assert time.monotonic() - started < 25

    report = report_of(out)
    assert report["verdict"] == "error"
    assert report["build_origin"] == "environment"
    assert "budget" in report["error"]


# --------------------------------------------------------------------------
# wiring: the resolved value reaches the engine
# --------------------------------------------------------------------------


def _wiring_target(tmp_path: Path) -> str:
    (tmp_path / "m.scad").write_text("cube([1, 1, 1]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('m.scad'))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    return f"{spec}:make"


def _captured_render_timeout(tmp_path: Path, monkeypatch, argv_tail: list[str]) -> object:
    pytest.importorskip("trimesh", reason="mesh extra not installed")
    from partspec.backend import BuildError
    from partspec.engines import openscad

    seen: dict[str, object] = {}

    def fake_render(source, out_dir, *, timeout_s=None):
        seen["timeout_s"] = timeout_s
        return BuildError("stub render", origin="environment")

    monkeypatch.setattr(openscad, "render", fake_render)
    out = tmp_path / "out"
    assert main(["check", _wiring_target(tmp_path), "--quiet", "--out", str(out), *argv_tail]) == 4
    return seen["timeout_s"]


def test_the_mesh_tier_receives_the_resolved_budget(tmp_path: Path, monkeypatch):
    assert _captured_render_timeout(tmp_path, monkeypatch, ["--timeout", "7"]) == 7.0


def test_zero_reaches_the_mesh_tier_as_unbounded(tmp_path: Path, monkeypatch):
    assert _captured_render_timeout(tmp_path, monkeypatch, ["--timeout", "0"]) is None


def test_nobody_choosing_applies_and_records_the_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PARTSPEC_TIMEOUT", raising=False)
    assert _captured_render_timeout(tmp_path, monkeypatch, []) == DEFAULT_TIMEOUT_S
    report = report_of(tmp_path / "out")
    assert report["invocation"]["timeout_s"] == DEFAULT_TIMEOUT_S
