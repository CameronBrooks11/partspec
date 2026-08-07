"""partspec diff: the comparator the report format carried fields for since v0.

Unit tests build documents through the real Report serializer where shape
matters, and hand-edit parsed JSON the way a real second run would differ.
The CLI tests run two genuine engine builds and diff the written artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partspec.diff import DiffUsageError, diff_reports, exit_code_of, summary_of
from partspec.report import CheckResult, Report
from partspec.status import Limit, Measurement, Status


def _doc(part_id: str = "p", **overrides) -> dict:
    report = Report(
        part_id=part_id,
        contract="spec.py:make",
        tool_version="0.1.0",
        contract_digest="sha256:c1",
        source_digest="sha256:s1",
        source_closure={"digest": "sha256:k1", "files": 2},
        checks=[
            CheckResult(
                id="wall_gt_2",
                kind="param_range",
                phase="parameter",
                status=Status.PASS,
                measurement=Measurement(2.9, "mm"),
                limit=Limit(min=2.0),
            ),
            CheckResult(
                id="fits",
                kind="requires",
                phase="parameter",
                status=Status.PASS,
                expr="a + b <= c",
                operands={"a": 1.0, "b": 2.0, "c": 4.0},
            ),
            CheckResult(id="builds", kind="builds", phase="geometry", status=Status.PASS),
            CheckResult(
                id="envelope",
                kind="envelope",
                phase="geometry",
                status=Status.PASS,
                measurement=Measurement((30.0, 20.0, 10.0), "mm", axes=("x", "y", "z")),
                limit=Limit(max=(30, 20, 10)),
            ),
        ],
    )
    doc = report.to_json()
    doc.update(overrides)
    return doc


def _diff(old: dict, new: dict) -> dict:
    return diff_reports(old, new, tool_version="test")


# --------------------------------------------------------------------------
# the headline: silent weakening becomes loud
# --------------------------------------------------------------------------


def test_a_deleted_check_is_named_not_implied():
    old = _doc()
    new = _doc()
    new["checks"] = [c for c in new["checks"] if c["id"] != "wall_gt_2"]
    new["counts"]["total"] -= 1

    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    assert exit_code_of(doc["outcome"]) == 1
    assert doc["contract"]["removed"] == ["wall_gt_2"]
    assert doc["counts_total"] == {"old": 4, "new": 3}
    assert "wall_gt_2" in summary_of(doc)


def test_pass_to_pass_drift_reports_both_values():
    """The 7.2 payoff: a wall thinning 2.9 -> 2.1 against min 2.0 is two green
    reports and one trend only this comparison can see."""
    old = _doc()
    new = _doc()
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["measurement"]["value"] = 2.1

    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "drifted"
    assert entry["status"] == "pass"
    assert entry["value"] == {"old": 2.9, "new": 2.1}


def test_float_noise_below_epsilon_is_not_a_difference():
    """Transform-order noise perturbs coordinates at ~1e-13; exact equality
    would bury signal under it (SPEC-diff.md 3)."""
    old = _doc()
    new = _doc()
    envelope = next(c for c in new["checks"] if c["id"] == "envelope")
    envelope["measurement"]["value"] = [30.0 + 1e-13, 20.0, 10.0 - 1e-13]

    doc = _diff(old, new)
    assert doc["checks"] == []
    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0


def test_status_changes_split_by_direction():
    old = _doc()
    new = _doc()
    next(c for c in new["checks"] if c["id"] == "envelope")["status"] = "fail"
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["status"] = "pass"
    next(c for c in old["checks"] if c["id"] == "wall_gt_2")["status"] = "fail"
    new["verdict"] = "fail"

    doc = _diff(old, new)
    changes = {c["id"]: c["change"] for c in doc["checks"]}
    assert changes == {"envelope": "regressed", "wall_gt_2": "fixed"}


def test_a_moved_limit_is_a_contract_edit_with_both_sides_shown():
    old = _doc()
    new = _doc()
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 1.0}

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "limit_changed"
    assert entry["claim"]["old"] == {"limit": {"min": 2.0}}
    assert entry["claim"]["new"] == {"limit": {"min": 1.0}}


def test_requires_checks_drift_on_operands():
    """Half the reason operands are recorded (SPEC-contract.md 5)."""
    old = _doc()
    new = _doc()
    next(c for c in new["checks"] if c["id"] == "fits")["operands"]["b"] = 2.5

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "fits")
    assert entry["change"] == "drifted"
    assert entry["operands"]["old"]["b"] == 2.0
    assert entry["operands"]["new"]["b"] == 2.5


# --------------------------------------------------------------------------
# the honest refusals
# --------------------------------------------------------------------------


def test_identical_on_a_partial_closure_is_indeterminate_not_clean():
    """Matching digests on a partial closure mean 'nothing we looked at
    changed'. Claiming identical there is silence-as-success at the
    provenance layer (SPEC-report.md 8.3)."""
    old = _doc()
    new = _doc()
    for doc_ in (old, new):
        doc_["part"]["source_closure"]["partial"] = True

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    assert exit_code_of(doc["outcome"]) == 2
    assert "partial" in doc["indeterminate"][0]
    assert doc["source"]["closure"] == "inconclusive"


def test_a_found_difference_survives_a_partial_closure():
    """Partiality only ever blocks the identical claim: a difference that was
    seen is real whatever else was not seen."""
    old = _doc()
    new = _doc()
    for doc_ in (old, new):
        doc_["part"]["source_closure"]["partial"] = True
    new["checks"] = [c for c in new["checks"] if c["id"] != "wall_gt_2"]

    assert _diff(old, new)["outcome"] == "different"


def test_an_error_report_compares_nothing():
    old = _doc()
    new = _doc(verdict="error", error="boom")
    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    assert "did not complete" in doc["indeterminate"][0]


def test_different_parts_are_a_usage_error_not_a_finding():
    with pytest.raises(DiffUsageError, match="different parts"):
        _diff(_doc("a"), _doc("b"))


def test_an_unknown_report_schema_is_rejected_not_best_effort_parsed():
    bad = _doc()
    bad["schema_version"] = 2
    with pytest.raises(DiffUsageError, match="schema_version"):
        _diff(_doc(), bad)


def test_environment_changes_explain_without_being_differences():
    """An engine upgrade that moved nothing measurable is context, not a
    semantic difference — but it must be visible, because it is what
    distinguishes 'a dependency moved this' from 'the design changed'."""
    old = _doc()
    new = _doc()
    new["engine"] = {**new.get("engine", {}), "version": "2026.08.01"}
    old["engine"] = {**old.get("engine", {}), "version": "2021.01"}

    doc = _diff(old, new)
    assert doc["outcome"] == "identical"
    assert doc["environment"]["engine_version"] == {"old": "2021.01", "new": "2026.08.01"}


def test_a_cosmetic_contract_edit_is_recorded_but_not_a_difference():
    """The module-scoped digest over-fires deliberately (SPEC-report.md 7.1);
    the semantic comparison must not inherit the over-firing."""
    old = _doc()
    new = _doc()
    new["part"]["contract_digest"] = "sha256:c2"

    doc = _diff(old, new)
    assert doc["outcome"] == "identical"
    assert doc["contract"]["digest_changed"] is True


# --------------------------------------------------------------------------
# end to end, on real runs
# --------------------------------------------------------------------------

from support import needs_openscad  # noqa: E402

pytest.importorskip("trimesh", reason="mesh extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"


def _run_cli(*argv: str) -> tuple[int, str, str]:
    import io
    import sys as _sys

    from partspec.cli import main

    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = _sys.stdout, _sys.stderr
    _sys.stdout, _sys.stderr = out, err
    try:
        code = main(list(argv))
    finally:
        _sys.stdout, _sys.stderr = old_out, old_err
    return code, out.getvalue(), err.getvalue()


@needs_openscad
def test_cli_diff_on_two_real_runs(tmp_path: Path):
    """Same source, same contract, run twice -> identical exit 0 (the OpenSCAD
    closure is complete, so the claim is earned). Then the plate grows and the
    same contract still passes -> drift, exit 1, with both envelopes shown."""
    scad = tmp_path / "plate.scad"
    scad.write_text("cube([30, 20, 4]);\n")
    contract = tmp_path / "spec.py"
    contract.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def make() -> Part:\n"
        "    p = Part('plate', openscad('plate.scad'))\n"
        "    p.envelope(max=(40, 30, 10))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    target = f"{contract}:make"

    assert _run_cli("check", target, "--out", str(tmp_path / "a"), "--quiet")[0] == 0
    assert _run_cli("check", target, "--out", str(tmp_path / "b"), "--quiet")[0] == 0
    code, out, err = _run_cli(
        "diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "b" / "report.json")
    )
    assert code == 0, err
    assert json.loads(out)["outcome"] == "identical"
    assert "identical" in err

    scad.write_text("cube([30, 20, 8]);\n")  # taller, still inside the envelope
    assert _run_cli("check", target, "--out", str(tmp_path / "c"), "--quiet")[0] == 0
    code, out, err = _run_cli(
        "diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "c" / "report.json")
    )
    assert code == 1
    doc = json.loads(out)
    assert doc["outcome"] == "different"
    entry = next(c for c in doc["checks"] if c["id"] == "envelope")
    assert entry["change"] == "drifted"
    assert entry["value"]["old"][2] == pytest.approx(4.0)
    assert entry["value"]["new"][2] == pytest.approx(8.0)
    assert doc["source"]["digest_changed"] is True


def test_cli_diff_usage_errors(tmp_path: Path):
    missing = tmp_path / "gone.json"
    present = tmp_path / "a.json"
    present.write_text(json.dumps(_doc()))
    assert _run_cli("diff", str(missing), str(present))[0] == 64

    not_json = tmp_path / "junk.json"
    not_json.write_text("{nope")
    assert _run_cli("diff", str(not_json), str(present))[0] == 64
