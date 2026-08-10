"""partspec diff: the comparator the report format carried fields for since v0.

Unit tests build documents through the real Report serializer where shape
matters, and hand-edit parsed JSON the way a real second run would differ.
The CLI tests run two genuine engine builds and diff the written artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from partspec.diff import (
    CLAIM_FIELDS,
    DiffUsageError,
    diff_reports,
    exit_code_of,
    summary_of,
)
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
    assert doc["indeterminate"][0]["code"] == "partial_closure"
    assert doc["source"]["closure"] == "inconclusive"


def test_a_found_difference_survives_a_partial_closure():
    """Partiality only ever blocks the identical claim: a difference that was
    seen is real whatever else was not seen."""
    old = _doc()
    new = _doc()
    for doc_ in (old, new):
        doc_["part"]["source_closure"]["partial"] = True
    new["checks"] = [c for c in new["checks"] if c["id"] != "wall_gt_2"]
    new["counts"]["total"] -= 1

    assert _diff(old, new)["outcome"] == "different"


def test_an_error_report_compares_nothing():
    old = _doc()
    new = _doc(verdict="error", error="boom")
    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    assert doc["indeterminate"][0]["code"] == "input_error"
    assert "did not complete" in doc["indeterminate"][0]["reason"]


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
    the semantic comparison must not inherit the over-firing.

    The deslop audit proposed the opposite — routing a changed digest with no
    check deltas to `indeterminate` — and this test is why it was not taken:
    the digest moves when an unrelated docstring in the contract module
    changes, so the rule would make routine edits exit 2 until someone piped
    the verb through `|| true`. What the diff compares IS the contract's
    observable content: every id, kind, claim field, status and measurement.
    Recorded, not outcome-bearing, on purpose. SPEC-diff §3 now says so, in the paragraph headed
    'Recorded but never outcome-bearing'.
    """
    old = _doc()
    new = _doc()
    new["part"]["contract_digest"] = "sha256:c2"

    doc = _diff(old, new)
    assert doc["outcome"] == "identical"
    assert doc["contract"]["digest_changed"] is True


def test_a_loosened_requires_predicate_is_a_different_claim():
    """PR #147's review, blocker 1: `expr` is the entire claim of a
    `requires` check, and nothing compared it. `wall >= 2.0` becoming
    `wall >= 0.2` — a tenfold weakening, the flagship move this verb exists
    to catch — reported `identical`, exit 0, with `contract_digest` the only
    remaining signal and that deliberately not outcome-bearing."""
    old = _doc()
    new = _doc()
    next(c for c in new["checks"] if c["id"] == "fits")["expr"] = "a + b <= c * 0.01"

    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    entry = next(c for c in doc["checks"] if c["id"] == "fits")
    assert entry["claim"]["old"]["expr"] == "a + b <= c"
    assert entry["claim"]["new"]["expr"] == "a + b <= c * 0.01"


def test_a_swapped_check_kind_is_a_different_claim():
    """The deslop audit's silent-weakening find: `kind` was compared by
    nothing, so under one id `genus` could become `cavities` — "this part has
    no through-holes" turning into "this part has one sealed void" — and the
    verb reported `identical`, exit 0.

    `expectation._claim_slug` had covered kind as claim-bearing all along and
    said so in its docstring, so the pin caught what the comparator could
    not. The two agree now.
    """
    old = _doc()
    new = _doc()
    target = next(c for c in new["checks"] if c["id"] == "wall_gt_2")
    target["kind"] = "envelope"

    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["claim"]["old"]["kind"] == "param_range"
    assert entry["claim"]["new"]["kind"] == "envelope"


def test_the_spec_lists_every_field_that_makes_a_claim_a_claim():
    """SPEC-diff §3 enumerates the claim fields and the list drifted three
    times unnoticed — `direction` arrived with `draft_angle` and was never
    documented, `kind` was never compared at all, and `expr` (the whole
    predicate of a `requires` check) was in neither list. Held in step now.

    The bullet terminator matches the next bullet or heading rather than a
    blank line: reflowing the paragraph used to fail this test with a
    message claiming fields were undocumented when every one was present.

    And it reads the ENUMERATION, not the whole bullet. Scanning every
    backticked word counted the prose — `kind` and `expr` are named in the
    anecdote that follows — so deleting either from the actual list went
    undetected, which is the entire failure this test exists to prevent.
    """
    spec = (Path(__file__).resolve().parents[1] / "docs" / "SPEC-diff.md").read_text()
    bullet = re.search(
        r"^- \*\*`limit_changed`\*\*.*?(?=\n- \*\*|\n\*\*|\n#{2,} )", spec, re.S | re.M
    )
    assert bullet, "SPEC-diff must carry a `limit_changed` bullet"
    enumeration = re.search(r"the \*claim\* moved: (.*?) differ", bullet.group(0), re.S)
    assert enumeration, "the bullet must enumerate the claim fields before the word 'differ'"
    named = set(re.findall(r"`(\w+)`", enumeration.group(1)))
    assert set(CLAIM_FIELDS) == named, (
        f"spec enumeration and CLAIM_FIELDS disagree: "
        f"only in code {set(CLAIM_FIELDS) - named}, only in spec {named - set(CLAIM_FIELDS)}"
    )


def test_every_field_the_report_emits_is_classified_as_claim_or_not():
    """The reverse direction, and the one that would have caught `expr`.

    Checking only that the spec names every field in `CLAIM_FIELDS` can
    never notice a claim-bearing field missing from BOTH lists — which is
    exactly how a loosened `requires` predicate stayed invisible while three
    places asserted the comparator covered "every field that makes a check
    the claim it is". Every key the serializer can emit must now be either
    compared as a claim or listed in `NON_CLAIM_FIELDS` with a reason, so
    the next field added to a report has to be classified deliberately.
    """
    import dataclasses

    from partspec.diff import NON_CLAIM_FIELDS

    # Declared fields, not just the ones this fixture happens to pass. The
    # first draft hand-built a CheckResult and checked only what it saw,
    # which is the same blind spot one level up: adding a new optional field
    # to CheckResult sailed through it. The two sets are already equal, so
    # this costs nothing today and refuses tomorrow's unclassified field.
    declared = {f.name for f in dataclasses.fields(CheckResult)}
    classified_all = set(CLAIM_FIELDS) | set(NON_CLAIM_FIELDS)
    assert declared <= classified_all, (
        f"CheckResult fields classified as neither claim nor non-claim: "
        f"{sorted(declared - classified_all)}"
    )
    assert classified_all <= declared, (
        f"classified but not a CheckResult field: {sorted(classified_all - declared)}"
    )

    emitted = set()
    for status in (Status.PASS, Status.UNSUPPORTED):
        emitted |= set(
            CheckResult(
                id="x",
                kind="requires",
                phase="parameter",
                status=status,
                measurement=Measurement(1.0, "mm"),
                limit=Limit(min=0.0),
                components={"x": Status.PASS},
                expr="a > b",
                operands={"a": 1},
                region={"kind": "box"},
                hole={"d": 1.0},
                source={"min": {"standard": "ISO"}},
                direction=[0.0, 0.0, 1.0],
                step={"schema": "AP214IS"},
                detail="d",
                requires="occt",
            ).to_json()
        )

    classified = set(CLAIM_FIELDS) | set(NON_CLAIM_FIELDS)
    assert emitted <= classified, (
        f"report fields classified as neither claim nor non-claim: {sorted(emitted - classified)}"
    )
    assert not (set(CLAIM_FIELDS) & set(NON_CLAIM_FIELDS)), "a field cannot be both"


def test_two_reports_with_no_closure_at_all_are_not_identical():
    """SPEC-diff §2 rule 3 names this case explicitly — "absent from either input,
    which is the ordinary v0.1.0 upgrade path" — and the code returned early
    when BOTH were absent, so the rule fired for one side and not for two.
    `identical` then rested on `source_digest` alone, which is the overclaim
    SPEC-report §8.3 reversed itself to prevent."""
    old, new = _doc(), _doc()
    for doc in (old, new):
        doc["part"].pop("source_closure")

    result = _diff(old, new)
    assert result["outcome"] == "indeterminate"
    assert result["source"]["closure"] == "inconclusive"
    assert exit_code_of(result["outcome"]) == 2


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


# --------------------------------------------------------------------------
# review hardening (PR #88)
# --------------------------------------------------------------------------


def test_a_missing_closure_on_one_side_blocks_the_identical_claim():
    """The ordinary v0.1.0 upgrade path: Python-engine reports written by the
    released tag carry no source_closure at all. Calling that 'changed' let
    the identical claim through unearned (review B1) — it is inconclusive."""
    old = _doc()
    del old["part"]["source_closure"]
    new = _doc()
    new["part"]["source_closure"]["partial"] = True

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    assert doc["source"]["closure"] == "inconclusive"
    assert doc["indeterminate"][0]["code"] == "partial_closure"


def test_a_partial_closure_on_only_the_new_side_still_blocks_identical():
    """Pins the .partial check on both sides — a mutant reading only the old
    side survived the original suite (review M6)."""
    old = _doc()
    new = _doc()
    new["part"]["source_closure"]["partial"] = True
    assert _diff(old, new)["outcome"] == "indeterminate"


def test_weakening_that_flips_a_status_still_shows_the_moved_limit():
    """The flagship attack: loosen the limit until a failing check passes.
    An entry saying only 'fixed' reports the attack as an improvement
    (review S1); the claim delta must ride along."""
    old = _doc()
    new = _doc()
    old_check = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    old_check["status"] = "fail"
    old["verdict"] = "fail"
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 0.001}

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "fixed"
    assert entry["claim"]["old"] == {"limit": {"min": 2.0}}
    assert entry["claim"]["new"] == {"limit": {"min": 0.001}}


def test_a_verdict_only_tamper_is_a_difference():
    """Identical checks, tampered verdict: still different (review M1 — this
    clause was untested and a mutant deleting it survived)."""
    old = _doc()
    new = _doc(verdict="fail")
    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    assert doc["checks"] == []
    assert "verdict changed" in summary_of(doc)


def test_a_report_contradicting_its_own_counts_is_corrupt_input():
    """counts.total is redundant by construction; an input violating its own
    invariant is corrupt, and no claim over corrupt input is earned
    (review S4)."""
    bad = _doc()
    bad["counts"]["total"] = 99
    with pytest.raises(DiffUsageError, match="corrupt"):
        _diff(_doc(), bad)


def test_a_report_with_two_checks_under_one_id_is_corrupt_input():
    """Ids are the join key, so aliasing is not a lost check — it is a wrong
    answer (#148).

    `counts.total` cannot catch this: the report carries exactly the number of
    checks it claims. Uniqueness is a separate invariant, and the comparator
    builds `{id: check}`, so the second occurrence silently replaces the first.

    Measured before the guard, on this exact input: the `param_range` claim
    vanished from the analysis entirely and the survivor was reported as a
    change from `{"kind": "param_range"}` to `{"kind": "genus"}` — two
    unrelated claims diffed as one, at exit 1, with no indication anything was
    wrong. That is the failure mode this project exists to refuse, in the
    confident-wrong-answer direction rather than the silent-pass one.
    """
    bad = _doc()
    aliased = dict(bad["checks"][0])
    aliased["kind"] = "genus"
    bad["checks"] = [bad["checks"][0], aliased, *bad["checks"][1:]]
    bad["counts"]["total"] = len(bad["checks"])  # self-consistent, so the counts guard is silent
    with pytest.raises(DiffUsageError, match="unique"):
        _diff(_doc(), bad)


def test_the_id_uniqueness_guard_names_every_repeated_id():
    """The message must name what to fix; a bare 'corrupt' sends the reader
    back to a diff of two whole reports."""
    bad = _doc()
    bad["checks"] = [*bad["checks"], dict(bad["checks"][0]), dict(bad["checks"][1])]
    bad["counts"]["total"] = len(bad["checks"])
    with pytest.raises(DiffUsageError) as exc:
        _diff(_doc(), bad)
    assert "wall_gt_2" in str(exc.value) and "fits" in str(exc.value)


def test_ids_that_are_not_strings_are_refused_before_they_can_alias():
    """The guard must key the way the join keys, or it lets through exactly what
    it exists to stop.

    A `repr`-based uniqueness count — added to stop mixed-type ids raising
    TypeError out of the guard — compared ids by their RENDERING while the join
    keys a dict on their VALUE. `1` and `1.0` render differently and pass the
    count, then collapse onto one another in `{c["id"]: c}`. Measured on that
    version: a four-check report joined as three, no refusal, exit 1 — the
    confident wrong answer of #148, reached THROUGH the guard meant to prevent
    it (PR #157 review).

    `checks[].id` is typed as a string by SPEC-report §7.1 and by
    `CheckResult.id`, so refusing the type costs nothing legitimate and closes
    the numeric-alias case, the mixed-type TypeError and the unhashable-id
    TypeError together.
    """
    for ids in ([1, 1.0], [True, 1], [["a"], ["a"]], ["ok", 2]):
        bad = _doc()
        for check, value in zip(bad["checks"], ids, strict=False):
            check["id"] = value
        with pytest.raises(DiffUsageError, match="not strings"):
            _diff(_doc(), bad)


def test_a_checks_entry_that_is_not_an_object_is_refused():
    """Same precondition, one step earlier: a non-object entry was filtered out
    of the id scan and then reached the join, where `c["id"]` raised TypeError
    into the CLI's blanket catch (PR #157 review)."""
    bad = _doc()
    bad["checks"] = [*bad["checks"], "not-a-check"]
    bad["counts"]["total"] = len(bad["checks"])
    with pytest.raises(DiffUsageError, match="not objects"):
        _diff(_doc(), bad)


def test_a_null_checks_field_does_not_crash_the_guard():
    """`"checks": null` is a shape a hand-written report can take, and the
    fallback has to be spelled the same way everywhere.

    `report.get("checks", [])` returns `None` when the key EXISTS with a null
    value, so the counts check raised `TypeError: object of type 'NoneType' has
    no len()` before reaching any guard, and the join raised again further down.
    Bound once now, above the first reader (PR #157 review).
    """
    empty = _doc()
    empty["checks"] = None
    empty["counts"]["total"] = 0
    assert _diff(empty, empty)["outcome"] in {"identical", "indeterminate"}

    lying = _doc()
    lying["checks"] = None  # while counts.total still claims 4
    with pytest.raises(DiffUsageError, match=r"counts\.total"):
        _diff(lying, lying)


def test_two_checks_of_one_kind_under_distinct_ids_are_not_caught():
    """The ordinary legal case the guard must not fire on.

    `p.volume(min=).volume(max=, id="volume_ceiling")` is legal — declared so by
    `test_duplicate_kinds_are_fine_with_explicit_ids` — so a guard keying on
    anything but the id, or deduping over-broadly, must fail here.

    The first version of this test asserted `_diff(_doc(), _doc())` is
    `identical` while claiming in its docstring to cover exactly the above.
    `_doc()` carries four checks with four DISTINCT kinds, so it constructed no
    such pair, duplicated four existing tests, and passed with the guard
    deleted — a test whose docstring was a claim about itself that nothing
    executed, which is the shape #150 spent a whole slice removing (PR #157
    review). It now builds the pair.
    """
    doc = _doc()
    ceiling = dict(doc["checks"][3])  # the `envelope` check, a real vector kind
    assert ceiling["kind"] == "envelope", "fixture changed; pick another kind to duplicate"
    ceiling["id"] = "envelope_ceiling"
    doc["checks"] = [*doc["checks"], ceiling]
    doc["counts"]["total"] = len(doc["checks"])

    kinds = [c["kind"] for c in doc["checks"]]
    assert kinds.count("envelope") == 2, "the pair this test exists for"
    assert len({c["id"] for c in doc["checks"]}) == len(doc["checks"]), "ids stay distinct"

    result = _diff(doc, doc)
    assert result["outcome"] == "identical"


def test_cli_malformed_reports_and_usage_typos_exit_64_not_a_verdict(tmp_path: Path):
    """A status outside the enum, a JSON array, and a forgotten argument all
    used to reach exit 4 or argparse's exit 2 — which reads as incomplete
    (review S2/S3). All unusable input is 64."""
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_doc()))

    bogus_status = _doc()
    bogus_status["checks"][0]["status"] = "bogus"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(bogus_status))
    assert _run_cli("diff", str(good), str(tampered))[0] == 64

    array = tmp_path / "array.json"
    array.write_text("[]")
    assert _run_cli("diff", str(good), str(array))[0] == 64

    # Aliased ids, end to end. Every other test of the uniqueness guard asserts
    # `DiffUsageError`; SPEC-diff's table claims exit 64, and until this line
    # nothing checked that the exception reaches the process exit code as one
    # (PR #157 review).
    aliased = _doc()
    twin = dict(aliased["checks"][0])
    twin["kind"] = "genus"
    aliased["checks"] = [aliased["checks"][0], twin, *aliased["checks"][1:]]
    aliased["counts"]["total"] = len(aliased["checks"])
    dupes = tmp_path / "dupes.json"
    dupes.write_text(json.dumps(aliased))
    code, _, err = _run_cli("diff", str(good), str(dupes))
    assert code == 64
    assert "wall_gt_2" in err, "the exit code must arrive with the id that caused it"

    # A check with no id at all is a DIFFERENT defect and must say so, rather
    # than be reported as `None` appearing twice.
    idless = _doc()
    for check in idless["checks"][:2]:
        check.pop("id")
    missing = tmp_path / "idless.json"
    missing.write_text(json.dumps(idless))
    code, _, err = _run_cli("diff", str(good), str(missing))
    assert code == 64
    assert "no `id`" in err, f"a missing id must be diagnosed as missing, got: {err}"

    with pytest.raises(SystemExit) as excinfo:
        _run_cli("diff", str(good))  # forgotten second argument
    assert excinfo.value.code == 64
