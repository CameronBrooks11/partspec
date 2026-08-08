"""Multi-target check (#29): one interpreter start, N reports, honest exits.

The batch rules are SPEC-report §5 rule 4 and §6.2: no early abort, one report
per part, exit by the highest-precedence verdict — and the hazard the slice
owns, POST-V0 §8: `sys.modules` must not serve a later build a stale helper.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from support import needs_openscad

from partspec.cli import main
from partspec.status import Verdict, exit_code

FIXTURES = Path(__file__).parent / "fixtures"


def _scad_target(tmp_path: Path, name: str, body: str) -> str:
    d = tmp_path / name
    d.mkdir()
    shutil.copy(FIXTURES / "block_with_hole.scad", d / "block_with_hole.scad")
    module = d / f"{name}.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        f"    p = Part({name!r}, openscad('block_with_hole.scad'))\n"
        f"{body}"
        "    return p\n"
    )
    return f"{module}:make"


def _report(target: str) -> dict:
    module, _, _ = target.rpartition(":")
    path = Path(module)
    return json.loads((path.parent / "outputs" / f"{path.stem}-make" / "report.json").read_text())


# --------------------------------------------------------------------------
# exits and no-early-abort
# --------------------------------------------------------------------------


@needs_openscad
def test_a_batch_writes_every_report_and_exits_the_worst_verdict(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    assert main(["check", good, bad, "--quiet"]) == exit_code(Verdict.FAIL)
    assert _report(good)["verdict"] == "pass", "the passing part still got its fresh report"
    assert _report(bad)["verdict"] == "fail"


@needs_openscad
def test_an_erroring_part_does_not_stop_the_rest(tmp_path: Path, capsys):
    raising = tmp_path / "raising.py"
    raising.write_text("def make():\n    raise TypeError('broken contract')\n")
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", f"{raising}:make", good, "--quiet"]) == exit_code(Verdict.ERROR)
    assert _report(good)["verdict"] == "pass", "SPEC-report 5.4: failures must not abort the batch"


@needs_openscad
def test_an_unresolvable_target_is_usage_and_the_rest_still_run(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", str(tmp_path / "nowhere.py") + ":make", good, "--quiet"]) == 64
    assert _report(good)["verdict"] == "pass"


@needs_openscad
def test_empty_outranks_fail_in_the_batch_exit(tmp_path: Path, capsys):
    """SPEC-report 6.1 precedence, pinned: the vacuous-green case is the more
    dangerous signal and must not hide behind a mere failure."""
    empty = _scad_target(tmp_path, "empty", "")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    assert main(["check", empty, bad, "--quiet"]) == exit_code(Verdict.EMPTY)


@needs_openscad
def test_the_summary_names_the_tally_and_quiet_suppresses_it(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    main(["check", good, bad])
    out = capsys.readouterr().out
    assert "BATCH: 2 parts" in out and "1 pass" in out and "1 fail" in out

    main(["check", good, bad, "--quiet"])
    assert "BATCH" not in capsys.readouterr().out


@needs_openscad
def test_a_single_target_emits_no_batch_summary(tmp_path: Path, capsys):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    assert main(["check", good]) == 0
    assert "BATCH" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# --out in a batch
# --------------------------------------------------------------------------


@needs_openscad
def test_explicit_out_gets_a_subdirectory_per_part(tmp_path: Path):
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.envelope(max=(1, 1, 1))\n")
    out = tmp_path / "reports"
    main(["check", good, bad, "--quiet", "--out", str(out)])
    assert json.loads((out / "good-make" / "report.json").read_text())["verdict"] == "pass"
    assert json.loads((out / "bad-make" / "report.json").read_text())["verdict"] == "fail"


def test_colliding_slugs_under_one_out_dir_are_refused(tmp_path: Path, capsys):
    """Two targets named spec.py:make in different directories share a slug;
    letting the second silently overwrite the first's report under one
    deterministic path is the stale-artifact failure, chosen on purpose."""
    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / "spec.py").write_text("def make():\n    pass\n")
    code = main(
        [
            "check",
            f"{tmp_path / 'a' / 'spec.py'}:make",
            f"{tmp_path / 'b' / 'spec.py'}:make",
            "--quiet",
            "--out",
            str(tmp_path / "reports"),
        ]
    )
    assert code == 64
    assert "collide" in capsys.readouterr().err


def test_render_refuses_a_batch(tmp_path: Path, monkeypatch, capsys):
    # chdir: shape refusals now precede the placeholder fan-out, but a test
    # running from the repo root must not depend on that to keep the tree
    # clean (PR #104 re-review, finding 7 — the old order littered ./outputs).
    monkeypatch.chdir(tmp_path)
    code = main(["check", "a.py:x", "b.py:x", "--render", "--quiet"])
    assert code == 64
    assert "single-target" in capsys.readouterr().err
    assert not (tmp_path / "outputs").exists(), "a refused shape touches no disk"


# --------------------------------------------------------------------------
# the POST-V0 §8 hazard: stale modules across builds in one process
# --------------------------------------------------------------------------


def _py_target(d: Path, size: float) -> str:
    d.mkdir(exist_ok=True)
    (d / "helper29.py").write_text(f"SIZE = {size}\n")
    (d / "model.py").write_text(
        "import helper29\nfrom build123d import Box\n\n\ndef make_part():\n"
        "    return Box(helper29.SIZE, 1, 1)\n"
    )
    spec = d / "spec.py"
    spec.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('model.py'))\n"
        "    p.volume(min=0.0)\n"
        "    return p\n"
    )
    return f"{spec}:make"


def _measured_volume(out: Path) -> float:
    report = json.loads((out / "report.json").read_text())
    (check,) = [c for c in report["checks"] if c["kind"] == "volume"]
    return check["measurement"]["value"]


def test_an_edited_helper_reaches_the_second_run_in_one_process(tmp_path: Path):
    """The acceptance test of POST-V0 §8: before invalidation, the second run
    measured the FIRST run's geometry — a stale build reported as fresh, with
    a closure digest taken from the edited file that never got imported."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    target = _py_target(tmp_path / "m", 1.0)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["check", target, "--quiet", "--out", str(out1)]) == 0
    assert _measured_volume(out1) == pytest.approx(1.0)

    # A different-LENGTH value on purpose: CPython validates a cached .pyc by
    # (mtime seconds, size), so a same-length edit within one second serves
    # stale bytecode to any interpreter — a ceiling beneath this tool's reach,
    # noted on `invalidate_model_modules`.
    _py_target(tmp_path / "m", 12.5)
    assert main(["check", target, "--quiet", "--out", str(out2)]) == 0
    assert _measured_volume(out2) == pytest.approx(12.5), "the edited helper must be re-imported"


def test_a_helper_the_contract_imports_is_invalidated_too(tmp_path: Path):
    """PR #104's review blocker: a helper the CONTRACT imports top-level
    enters sys.modules during resolve, before the build's snapshot — so it
    was never recorded, never evicted, and an edit produced POST-V0 §8's
    worst case verbatim: a stale build with a closure digest of the edited
    file that never reached the interpreter. Resolution is snapshot now."""
    pytest.importorskip("build123d", reason="occt extra not installed")

    def write(size: float) -> str:
        d = tmp_path / "m"
        d.mkdir(exist_ok=True)
        (d / "contract_helper.py").write_text(f"SIZE = {size}\n")
        (d / "model.py").write_text(
            "from build123d import Box\n\n\ndef make_part(size=1.0):\n    return Box(size, 1, 1)\n"
        )
        spec = d / "spec.py"
        spec.write_text(
            "from contract_helper import SIZE\n"
            "from partspec import Part, build123d\n\n\ndef make():\n"
            "    p = Part('subject', build123d('model.py', size=SIZE))\n"
            "    p.volume(min=0.0)\n"
            "    return p\n"
        )
        return f"{spec}:make"

    target = write(1.0)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["check", target, "--quiet", "--out", str(out1)]) == 0
    assert _measured_volume(out1) == pytest.approx(1.0)

    write(12.5)  # different length: sidestep the .pyc mtime-second ceiling
    assert main(["check", target, "--quiet", "--out", str(out2)]) == 0
    assert _measured_volume(out2) == pytest.approx(12.5), (
        "the contract's own import must be re-read, not served from sys.modules"
    )


@needs_openscad
def test_garbage_timeout_env_still_placeholders_every_target(tmp_path: Path, monkeypatch, capsys):
    """The fan-out exists so an invocation that dies at the door leaves every
    target's artifact saying the run died — never a previous verdict."""
    good = _scad_target(tmp_path, "good", "    p.watertight()\n")
    bad = _scad_target(tmp_path, "bad", "    p.watertight()\n")
    assert main(["check", good, bad, "--quiet"]) == 0

    monkeypatch.setenv("PARTSPEC_TIMEOUT", "soon")
    assert main(["check", good, bad, "--quiet"]) == 64
    assert _report(good)["verdict"] == "error", "the stale pass must not survive"
    assert _report(bad)["verdict"] == "error"


def test_an_interrupt_leaves_no_stale_pass_behind_it(tmp_path: Path, capsys):
    """A batch interrupted at part two meant to re-check part three; part
    three's previous pass sitting untouched would be a stale artifact reading
    as current. Placeholders for every target go down before any runs."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    calm = _py_target(tmp_path / "calm", 1.0)
    assert main(["check", calm, "--quiet"]) == 0

    interrupting = tmp_path / "interrupting.py"
    interrupting.write_text("def make():\n    raise KeyboardInterrupt\n")
    assert main(["check", f"{interrupting}:make", calm, "--quiet"]) == 130
    report = json.loads((tmp_path / "calm" / "outputs" / "spec-make" / "report.json").read_text())
    assert report["verdict"] == "error", "the never-reached target's artifact says the run died"


def test_batch_of_two_python_models_each_measures_its_own(tmp_path: Path):
    """PR #101's review demonstrated the cross live: model B built with model
    A's cached helper. In one batch invocation each part must measure its own."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    a = _py_target(tmp_path / "a", 1.0)
    b = _py_target(tmp_path / "b", 3.0)
    assert main(["check", a, b, "--quiet"]) == 0
    vol_a = _measured_volume(tmp_path / "a" / "outputs" / "spec-make")
    vol_b = _measured_volume(tmp_path / "b" / "outputs" / "spec-make")
    assert vol_a == pytest.approx(1.0)
    assert vol_b == pytest.approx(3.0), "model B must not build with model A's cached helper"


@needs_openscad
def test_a_contracts_shared_claims_module_does_not_cross_directories(tmp_path: Path):
    """PR #112's review: the taught `from claims import shared_claims`
    pattern, copied into two directories and batched, served directory A's
    cached claims module to directory B's contract — part B green under part
    A's checks. The eviction registry now covers contract-sibling imports on
    every engine."""
    for name, body in (("a", "p.watertight()"), ("b", "p.solid_count(1)")):
        d = tmp_path / name
        d.mkdir()
        (d / "m.scad").write_text("cube([2, 2, 2]);\n")
        (d / "claims.py").write_text(f"def shared_claims(p):\n    {body}\n    return p\n")
        (d / "spec.py").write_text(
            "from claims import shared_claims\n\n"
            "from partspec import Part, openscad\n\n\ndef make():\n"
            f"    return shared_claims(Part('{name}', openscad('m.scad')))\n"
        )
    targets = [f"{tmp_path / 'a' / 'spec.py'}:make", f"{tmp_path / 'b' / 'spec.py'}:make"]
    assert main(["check", *targets, "--quiet"]) == 0

    def kinds(d: Path) -> set[str]:
        report = json.loads((d / "outputs" / "spec-make" / "report.json").read_text())
        return {c["kind"] for c in report["checks"]} - {"builds"}

    assert kinds(tmp_path / "a") == {"watertight"}
    assert kinds(tmp_path / "b") == {"solid_count"}, (
        "part B must be checked by ITS claims module, not directory A's cached one"
    )


@needs_openscad
def test_a_contract_that_raises_after_its_sibling_import_does_not_poison_the_next_run(
    tmp_path: Path,
):
    """#114 path 1: the sibling import succeeded, THEN the contract raised —
    the record now lands in _resolve_or_report's finally and the failed
    resolve evicts, so directory B still gets its own module."""
    a, b = tmp_path / "a", tmp_path / "b"
    for d, body in ((a, "p.watertight()"), (b, "p.solid_count(1)")):
        d.mkdir()
        (d / "m.scad").write_text("cube([2, 2, 2]);\n")
        (d / "claims.py").write_text(f"def shared_claims(p):\n    {body}\n    return p\n")
    (a / "spec.py").write_text(
        "from claims import shared_claims\n\nraise TypeError('broken after the import')\n"
    )
    (b / "spec.py").write_text(
        "from claims import shared_claims\n\n"
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return shared_claims(Part('b', openscad('m.scad')))\n"
    )
    # An import-time raise is an unresolvable target: usage, exit 64.
    assert main(["check", f"{a / 'spec.py'}:make", "--quiet"]) == 64
    assert main(["check", f"{b / 'spec.py'}:make", "--quiet"]) == 0
    report = json.loads((b / "outputs" / "spec-make" / "report.json").read_text())
    kinds = {c["kind"] for c in report["checks"]} - {"builds"}
    assert kinds == {"solid_count"}, "B must not inherit A's cached claims module"


def test_a_render_refusal_does_not_leave_the_sibling_cached(tmp_path: Path):
    """#114 path 2: the --render-on-OCCT usage refusal returned before the
    eviction; the try/finally now covers it."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    a, b = tmp_path / "a", tmp_path / "b"
    for d, size in ((a, "1.0"), (b, "3.0")):
        d.mkdir()
        (d / "claims.py").write_text(f"SIZE = {size}\n")
        (d / "model.py").write_text(
            "from claims import SIZE\nfrom build123d import Box\n\n\ndef make_part():\n"
            "    return Box(SIZE, 1, 1)\n"
        )
        (d / "spec.py").write_text(
            "from partspec import Part, build123d\n\n\ndef make():\n"
            "    p = Part('subject', build123d('model.py'))\n"
            "    p.volume(min=0.0)\n"
            "    return p\n"
        )
    # The refusal path on A caches A's claims module during resolve...
    assert main(["check", f"{a / 'spec.py'}:make", "--render", "--quiet"]) == 64
    # ...which must not answer for B's model in the same process.
    assert main(["check", f"{b / 'spec.py'}:make", "--quiet", "--out", str(tmp_path / "o")]) == 0
    vol = _measured_volume(tmp_path / "o")
    assert vol == pytest.approx(3.0), "B built with A's cached SIZE"
