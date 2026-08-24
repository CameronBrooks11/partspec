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
from partspec.status import Limit, Measurement, Status, epsilon


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
    assert "wall_gt_2" in summary_of(doc, new)


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
# a check that stopped being answered is not a repair (#325)
# --------------------------------------------------------------------------


def _status_pair(old_status: Status, new_status: Status) -> tuple[dict, dict]:
    docs = (_doc(), _doc())
    for doc, status in zip(docs, (old_status, new_status), strict=True):
        next(c for c in doc["checks"] if c["id"] == "wall_gt_2")["status"] = status.value
    return docs


def test_the_answered_record_keys_on_the_new_status_over_every_transition():
    """#325. `_SEVERITY` ranks `approximate`, `unsupported` and `skipped`
    below `fail` — right for a verdict — so a check that is not answered on
    the new side lands in `fixed` and is filed as one that was answered
    better.

    Asserted over EVERY ordered pair of distinct statuses, with the
    expectation derived from the vocabulary rather than listed: a check is
    answered iff `Status` calls its outcome conclusive. Enumerating pairs is
    how two drafts of the issue got the bound wrong — the first omitting
    `approximate`, the second admitting only transitions out of `fail` — and a
    hand-written table of cases here would be the same mistake with a green
    suite on top."""
    conclusive = {Status.PASS, Status.FAIL}
    seen = set()
    for old_status in Status:
        for new_status in Status:
            if old_status is new_status:
                continue
            entry = next(
                c
                for c in _diff(*_status_pair(old_status, new_status))["checks"]
                if c["id"] == "wall_gt_2"
            )
            assert entry["change"] in ("regressed", "fixed")
            where = (old_status.value, new_status.value)
            if new_status in conclusive:
                assert "answered" not in entry, where
            else:
                assert entry["answered"] == {"old": old_status in conclusive, "new": False}, where
            seen.add(where)

    # The sweep really covered the whole vocabulary, not a subset of it.
    assert len(seen) == len(Status) * (len(Status) - 1) == 20


def test_a_check_that_was_never_answered_is_recorded_too():
    """`unsupported` → `skipped` was answered on neither side, so nothing
    *stopped* being answerable — and the headline calls it `fixed` just the
    same, which is why the record keys on the new status and not on the
    transition. Both sides are carried so the two cases stay distinguishable."""
    never = next(c for c in _diff(*_status_pair(Status.UNSUPPORTED, Status.SKIPPED))["checks"])
    stopped = next(c for c in _diff(*_status_pair(Status.FAIL, Status.SKIPPED))["checks"])

    assert never["change"] == stopped["change"] == "fixed"
    assert never["answered"] == {"old": False, "new": False}
    assert stopped["answered"] == {"old": True, "new": False}


def test_the_headline_qualifier_follows_the_record_over_every_transition():
    """Review round 1, F1. The artifact got a derived sweep and the headline
    got enumeration-shaped coverage: every headline case here used a `fixed`
    entry whose old status was `fail`. Two mutants lived in the gap — one
    qualifying only the `fixed` bucket, one counting only checks that
    *stopped* being answered — and the second printed #325's original output
    verbatim for `unsupported` → `skipped`.

    So the headline is swept the same way the record is: over every ordered
    pair of distinct statuses, the qualifier appears exactly when the entry
    carries the record, in whichever bucket the entry landed. Asserted as the
    whole line, since a substring check cannot see a qualifier that should be
    absent."""
    for old_status in Status:
        for new_status in Status:
            if old_status is new_status:
                continue
            old, new = _status_pair(old_status, new_status)
            doc = _diff(old, new)
            entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")

            qualifier = " (1 not answered)" if "answered" in entry else ""
            assert summary_of(doc, new).splitlines()[0] == (
                f"different: p — 1 {entry['change']}{qualifier}"
            ), (old_status.value, new_status.value)


def test_answered_rides_a_status_change_and_only_those():
    """Review round 1, F3. §3 scopes the record to status-change entries: it
    exists to correct a bucket that names a DIRECTION, and only `regressed`
    and `fixed` do. On an entry whose status held, `status` is the single
    unchanged value a reader can already read.

    Pinned over every unanswered status and both status-holding buckets,
    because §3 read without the scope makes each of these a violation, and a
    mutant obeying that reading passed the whole suite.

    The census behind that claim, stated with its method so it can be
    re-checked rather than re-derived: 135 check variants per side — 5
    statuses × 3 claims × 3 measurement values × 3 operand sets — diffed
    against each other is 135² = 18,225 ordered pairs, of which 2,106 hold
    their status at an unanswered one and 0 carry the record. The dimensions
    are the three fields the comparison compares, plus `status`. `phase` is
    held fixed and is NOT one of them: it picks a tolerance and is never
    itself a difference, and a grid that makes it a dimension also totals
    18,225 while answering 1,944."""
    for status in (s for s in Status if s not in {Status.PASS, Status.FAIL}):
        claim_moved, value_moved = _status_pair(status, status), _status_pair(status, status)
        next(c for c in claim_moved[1]["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 1.0}
        next(c for c in value_moved[1]["checks"] if c["id"] == "wall_gt_2")["measurement"][
            "value"
        ] = 9.9

        for pair, bucket in ((claim_moved, "limit_changed"), (value_moved, "drifted")):
            entry = next(c for c in _diff(*pair)["checks"] if c["id"] == "wall_gt_2")
            assert entry["change"] == bucket, status.value
            assert entry["status"] == status.value
            assert "answered" not in entry, (status.value, bucket)


def test_the_headline_counts_the_checks_the_new_report_does_not_answer():
    """The artifact carrying the fact is half of it: the headline is the
    surface a human reads in a terminal or a PR check, and `1 fixed` there is
    the whole of #325's complaint.

    Three entries, so the count is neither zero nor the bucket total and the
    qualified entry is not the only one — a qualifier printing the bucket
    total reads identically at one entry."""
    old, new = _doc(), _doc()
    for doc, statuses in (
        (old, {"wall_gt_2": "fail", "envelope": "fail", "fits": "fail"}),
        (new, {"wall_gt_2": "pass", "envelope": "skipped", "fits": "unsupported"}),
    ):
        for check in doc["checks"]:
            if check["id"] in statuses:
                check["status"] = statuses[check["id"]]
        doc["verdict"] = "fail"

    doc = _diff(old, new)
    assert {c["id"]: "answered" in c for c in doc["checks"]} == {
        "wall_gt_2": False,  # fail -> pass is the genuine repair
        "envelope": True,
        "fits": True,
    }
    assert summary_of(doc, new).splitlines()[0] == "different: p — 3 fixed (2 not answered)"


def test_both_qualifiers_are_stated_where_both_apply():
    """A second qualifier, not a widening of the first. They answer different
    questions — whether the author moved the goalposts, and whether anyone was
    still keeping score — and an entry can earn both."""
    old, new = _status_pair(Status.FAIL, Status.SKIPPED)
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 1.0}

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert "claim" in entry and "answered" in entry
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed, 1 not answered)"
    )


# --------------------------------------------------------------------------
# the comparison tolerance keys on recorded provenance, not on type (#335)
# --------------------------------------------------------------------------


def _move(doc: dict, check_id: str, value, status: str | None = None) -> dict:
    check = next(c for c in doc["checks"] if c["id"] == check_id)
    check["measurement"]["value"] = value
    if status is not None:
        check["status"] = status
    return doc


@pytest.mark.parametrize(
    ("before", "after"),
    [(2.9, 2.9 - 1e-6), (1000.0, 1000.0 - 1e-5)],
    ids=["at 2.9mm", "at 1000mm"],
)
def test_a_parameter_phase_value_compares_exactly(before: float, after: float):
    """#335. `epsilon(reference)` is sized for what a MEASUREMENT survives — a
    binary-STL round-trip through float32 — and a parameter-phase value
    survives nothing: `runner` reads it from the declared parameters before
    any engine runs. Under the measurement tolerance a parameter could cross
    its own limit and be called unmoved.

    Two magnitudes, because `epsilon` is magnitude-dependent and a fixture at
    one value pins nothing about a tolerance that grows with the number."""
    assert abs(after - before) < epsilon(before)  # the fixture is inside the old dead band

    # status held: the drift SPEC-diff §1 exists to report
    held = _diff(_move(_doc(), "wall_gt_2", before), _move(_doc(), "wall_gt_2", after))
    entry = next(c for c in held["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "drifted"
    assert entry["value"] == {"old": before, "new": after}

    # status flipped: #335's own reproduction, where the entry named neither number
    flipped = _diff(
        _move(_doc(), "wall_gt_2", before, "pass"),
        _move(_doc(), "wall_gt_2", after, "fail"),
    )
    entry = next(c for c in flipped["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "regressed"
    assert entry["value"] == {"old": before, "new": after}


def test_a_geometry_phase_value_keeps_the_measurement_tolerance():
    """The other half of the same rule, and the half that must not move: a
    geometry value is measured off an exported artifact, and exact equality
    there reports transform-order noise as drift. Both directions are pinned,
    so this is the tolerance still working and not geometry going silent."""
    absorbed = _diff(_doc(), _move(_doc(), "envelope", [30.0 + 1e-6, 20.0 - 1e-6, 10.0 + 1e-6]))
    assert absorbed["checks"] == []
    assert absorbed["outcome"] == "identical"

    reported = _diff(_doc(), _move(_doc(), "envelope", [30.0, 20.0, 10.5]))
    entry = next(c for c in reported["checks"] if c["id"] == "envelope")
    assert entry["change"] == "drifted"
    assert entry["value"]["new"] == [30.0, 20.0, 10.5]


def test_the_tolerance_keys_on_phase_and_not_on_exactness():
    """The field that looks like the right key and is not. `exact` separates a
    point value from a bounded interval — `bounds` is required iff not
    `exact` — and says nothing about reproducibility: the fixture's geometry
    `envelope` and its parameter `wall_gt_2` are BOTH labelled
    `exactness: "exact"`.

    The pair below is the real thing, measured: `cube([120.3, 80.7, 40.1])` on
    the mesh tier reports 120.30000305175781, which is float32 quantisation
    and which `SPEC-backend.md` §5.2 lets that tier collapse *because* this
    epsilon is wider than it. One fixture, one field changed, opposite
    answers — so a comparison keyed on `exactness` fails here while passing
    every other test in this file."""
    quantised = 120.30000305175781

    def envelope_pair(phase: str) -> tuple[dict, dict]:
        docs = (_doc(), _doc())
        for doc, value in zip(docs, (120.3, quantised), strict=True):
            check = next(c for c in doc["checks"] if c["id"] == "envelope")
            check["phase"] = phase
            check["measurement"]["value"] = value
            assert check["measurement"]["exactness"] == "exact"
        return docs

    assert _diff(*envelope_pair("geometry"))["checks"] == []
    entry = next(c for c in _diff(*envelope_pair("parameter"))["checks"])
    assert entry["value"] == {"old": 120.3, "new": quantised}


def test_parameter_phase_on_either_side_is_enough():
    """A pair disagreeing about its own provenance fails toward reporting: the
    exact comparison can only report more differences, never fewer, and §2's
    rule is that "no differences found" is the positive claim."""
    for relabelled in ("old", "new"):
        docs = {"old": _doc(), "new": _move(_doc(), "wall_gt_2", 2.9 - 1e-6)}
        for side, doc in docs.items():
            check = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
            check["phase"] = "parameter" if side == relabelled else "geometry"

        entry = next(c for c in _diff(docs["old"], docs["new"])["checks"])
        assert entry["id"] == "wall_gt_2"
        assert entry["value"] == {"old": 2.9, "new": 2.9 - 1e-6}


def test_a_report_that_records_no_phase_keeps_the_measurement_tolerance():
    """Silence is not evidence of parameter provenance. Reading an absent
    `phase` as one would report float32 noise as drift for every report
    written before this comparison read the field — so it reproduces what it
    received before."""
    docs = (_doc(), _move(_doc(), "wall_gt_2", 2.9 - 1e-6))
    for doc in docs:
        del next(c for c in doc["checks"] if c["id"] == "wall_gt_2")["phase"]

    assert _diff(*docs)["checks"] == []


# --------------------------------------------------------------------------
# the bucket names the change; it does not decide what the entry carries (#330)
# --------------------------------------------------------------------------

# bucket -> (old status, new status, whether the claim moves)
_BUCKETS = {
    "regressed": ("pass", "fail", True),
    "fixed": ("fail", "pass", True),
    "limit_changed": ("pass", "pass", True),
    "drifted": ("pass", "pass", False),
}


def _every_delta_pair(old_status: str, new_status: str, claim_moves: bool) -> tuple[dict, dict]:
    """One check pair in which the claim, the measurement and the operands all
    move, so any entry carrying a subset of them is visible.

    `fits` is the fixture's second check, so this is never read at the head of
    the list. A check carrying BOTH a `measurement` and `operands` is not
    something the runner emits — `_run_parameter_check` gives a `requires`
    result no measurement — but the report schema permits it, and §2 rule 4 is
    that the comparator does not get to assume it produced its own input."""
    docs = (_doc(), _doc())
    for doc, status, limit, value, b in (
        (docs[0], old_status, 2.0, 2.9, 2.0),
        (docs[1], new_status, 1.0 if claim_moves else 2.0, 2.1, 7.9),
    ):
        check = next(c for c in doc["checks"] if c["id"] == "fits")
        check["status"] = status
        check["limit"] = {"min": limit}
        check["measurement"] = {"value": value, "unit": "mm"}
        check["operands"] = {"a": 1.0, "b": b, "c": 4.0}
        doc["verdict"] = "fail" if status == "fail" else "pass"
    return docs


@pytest.mark.parametrize("bucket", sorted(_BUCKETS))
def test_no_bucket_carries_a_subset_of_what_moved(bucket: str):
    """#330. Each branch returned as soon as it knew its own NAME, one delta
    into a chain of three — so `limit_changed` shipped the contract edit
    without the drift it was covering, and `drifted` shipped a moved
    measurement without the operands beside it. Both were computed and thrown
    away.

    Over every bucket, because the defect is a property of the chain and not
    of one branch: whichever entry a pair lands on, it carries every delta the
    comparison computed. Presence AND absence are asserted, so a fix that
    attaches deltas unconditionally fails here too."""
    old_status, new_status, claim_moves = _BUCKETS[bucket]
    old, new = _every_delta_pair(old_status, new_status, claim_moves)

    entry = next(c for c in _diff(old, new)["checks"] if c["id"] == "fits")
    assert entry["change"] == bucket
    assert set(entry) - {"id", "kind", "change", "status"} == (
        {"claim", "value", "operands"} if claim_moves else {"value", "operands"}
    )
    assert entry["value"] == {"old": 2.9, "new": 2.1}
    assert entry["operands"]["old"]["b"] == 2.0
    assert entry["operands"]["new"]["b"] == 7.9
    if claim_moves:
        assert entry["claim"] == {"old": {"limit": {"min": 2.0}}, "new": {"limit": {"min": 1.0}}}


def test_an_entry_carries_only_what_actually_moved():
    """The rule is that the bucket does not gate the deltas, not that every
    entry gets all three: an entry naming a delta that did not move would
    invent a difference, which is the mirror of the defect."""
    old, new = _doc(), _doc()
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 1.0}
    entry = next(c for c in _diff(old, new)["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "limit_changed"
    assert set(entry) - {"id", "kind", "change", "status"} == {"claim"}

    old, new = _doc(), _doc()
    next(c for c in new["checks"] if c["id"] == "fits")["operands"]["b"] = 2.5
    entry = next(c for c in _diff(old, new)["checks"] if c["id"] == "fits")
    assert entry["change"] == "drifted"
    assert set(entry) - {"id", "kind", "change", "status"} == {"operands"}


def test_a_drifted_entry_never_carries_a_claim():
    """The one structural consequence §3 states, and not an exception to the
    rule: a moved claim is exactly what would have made the entry
    `limit_changed`, so `drifted` and `claim` cannot co-occur by construction.

    Pinned as the ONE pair that differs — same movement, claim held on the
    second — because asserting "no drifted entry carries a claim" over a
    document with no drifted entry in it passes for the wrong reason."""
    moved = next(c for c in _diff(*_every_delta_pair("pass", "pass", True))["checks"])
    held = next(c for c in _diff(*_every_delta_pair("pass", "pass", False))["checks"])

    assert (moved["change"], "claim" in moved) == ("limit_changed", True)
    assert (held["change"], "claim" in held) == ("drifted", False)
    # The bucket is the only thing the claim decided: both carry the rest.
    assert moved["value"] == held["value"] == {"old": 2.9, "new": 2.1}
    assert moved["operands"] == held["operands"]


def _two_requires(status: str, operands: dict, other_status: str, other_operands: dict) -> dict:
    """A document with TWO `requires` checks, `clears` ahead of the fixture's
    own `fits`, so a rule about `requires` checks is observed somewhere other
    than at the head of the list."""
    doc = _doc()
    fits = next(c for c in doc["checks"] if c["id"] == "fits")
    fits["status"], fits["operands"] = other_status, other_operands
    doc["checks"].insert(
        0, {**fits, "id": "clears", "expr": "d <= h", "status": status, "operands": operands}
    )
    tally = {key: 0 for key in doc["counts"] if key != "total"}
    for check in doc["checks"]:
        tally[check["status"]] += 1
    doc["counts"] = {"total": len(doc["checks"]), **tally}
    doc["verdict"] = "fail" if tally["fail"] else "pass"
    return doc


def test_a_status_change_carries_the_operands_that_moved_with_it():
    """#326. §3 names `operands` as the value of a `requires` check — it is
    what `measurement.value` is for every other kind — and §3 says a
    status-change entry MUST carry the value delta. The status branch
    returned before reaching the operands comparison, so the delta was
    recorded when the status held and dropped when it changed: `1 regressed`
    and not one of the numbers that regressed it, though both reports carry
    them.

    Both directions of the severity order, two checks, and operands moving
    up on one and down on the other, because a rule about status changes is
    not pinned by one transition of one check in one direction."""
    old = _two_requires("pass", {"d": 3.0, "h": 9.0}, "fail", {"a": 1.0, "b": 28.0, "c": 4.0})
    new = _two_requires("fail", {"d": 12.0, "h": 9.0}, "pass", {"a": 1.0, "b": 2.0, "c": 4.0})

    doc = _diff(old, new)
    entries = {c["id"]: c for c in doc["checks"] if c["kind"] == "requires"}
    assert {i: e["change"] for i, e in entries.items()} == {
        "clears": "regressed",
        "fits": "fixed",
    }
    # Both sides in full, unmoved operands included: the delta is the two maps
    # the reports recorded, which is what makes `d` the answer to "which input
    # changed?" rather than one of three numbers a reader must go and fetch.
    assert entries["clears"]["operands"] == {
        "old": {"d": 3.0, "h": 9.0},
        "new": {"d": 12.0, "h": 9.0},
    }
    assert entries["fits"]["operands"] == {
        "old": {"a": 1.0, "b": 28.0, "c": 4.0},
        "new": {"a": 1.0, "b": 2.0, "c": 4.0},
    }


def test_operands_that_did_not_move_do_not_ride_a_status_change():
    """The entry carries a delta, not a dump of whatever the new side holds:
    a status that changed for a reason outside the expression must not be
    given three numbers that did not move as its explanation."""
    unmoved = {"a": 1.0, "b": 2.0, "c": 4.0}
    old = _two_requires("pass", {"d": 3.0, "h": 9.0}, "pass", dict(unmoved))
    new = _two_requires("fail", {"d": 12.0, "h": 9.0}, "fail", dict(unmoved))

    entries = {c["id"]: c for c in _diff(old, new)["checks"] if c["kind"] == "requires"}
    assert entries["fits"]["change"] == "regressed"
    assert "operands" not in entries["fits"]
    # The other check in the same document did move, so this is the comparison
    # answering per pair and not answering "no" globally.
    assert "operands" in entries["clears"]


def test_an_operand_move_below_the_measurement_epsilon_is_still_a_move():
    """Review round 1. `operands` were compared through `_values_equal`, and
    its `epsilon(reference) = 1e-6 + 1e-7·|old|` is sized for a MEASUREMENT —
    §3 justifies it by transform-order noise at ~1e-13 and `SPEC-report.md`
    §3.3 sizes it for a binary-STL float32 round-trip. An operand is neither:
    `expr.evaluate` reads the contract's declared parameters straight, before
    any build, and adjudicates the predicate EXACTLY, with no epsilon
    anywhere. So the borrowed tolerance opened a band — 3.6e-06 wide at
    26 mm — in which the predicate flips and the comparison called the
    operands unmoved, reproducing #326's own artifact on the branch that
    fixed it.

    The fixture proves it sits inside that band rather than asserting it: the
    move is smaller than `epsilon` and the predicate `bore_d + 2 * wall <=
    plate_y` still goes true → false across it."""
    before, after = 26.0, 26.000001
    assert abs(after - before) < epsilon(before)
    assert (before + 2 * 2.0 <= 30.0) and not (after + 2 * 2.0 <= 30.0)

    old = _two_requires("pass", {"d": 3.0}, "pass", {"bore_d": before, "wall": 2.0})
    new = _two_requires("fail", {"d": 3.0}, "fail", {"bore_d": after, "wall": 2.0})

    entries = {c["id"]: c for c in _diff(old, new)["checks"] if c["kind"] == "requires"}
    assert entries["fits"]["operands"] == {
        "old": {"bore_d": before, "wall": 2.0},
        "new": {"bore_d": after, "wall": 2.0},
    }
    # And the same move with the status unchanged, so the exactness is a
    # property of the comparison and not of the branch that reached it.
    held_old = _two_requires("pass", {"d": 3.0}, "pass", {"bore_d": before, "wall": 2.0})
    held_new = _two_requires("pass", {"d": 3.0}, "pass", {"bore_d": after, "wall": 2.0})
    held = {c["id"]: c for c in _diff(held_old, held_new)["checks"]}
    assert held["fits"]["change"] == "drifted"
    assert held["fits"]["operands"]["new"]["bore_d"] == after


def test_a_moved_value_and_moved_operands_are_independent_deltas():
    """Round 1 left one mutant alive — suppress `operands` whenever the
    measurement also moved — and it passes everything partspec itself emits,
    because `_run_parameter_check` builds a `requires` result with no
    measurement at all. That makes it unreachable from our own producer, not
    equivalent: `diff` consumes the report schema as a product surface and
    must not assume it produced its own input, which is the same reason the
    duplicate-id guard exists. So the case is constructed rather than excused.

    The two deltas answer different questions — what the check measured, and
    what its expression read — and one arriving is never a reason to drop the
    other."""
    old = _two_requires("pass", {"d": 3.0}, "pass", {"a": 1.0})
    new = _two_requires("fail", {"d": 3.0}, "fail", {"a": 2.0})
    for doc, value in ((old, 2.9), (new, 2.1)):
        next(c for c in doc["checks"] if c["id"] == "fits")["measurement"] = {
            "value": value,
            "unit": "mm",
        }

    entry = next(c for c in _diff(old, new)["checks"] if c["id"] == "fits")
    assert entry["change"] == "regressed"
    assert entry["value"] == {"old": 2.9, "new": 2.1}
    assert entry["operands"] == {"old": {"a": 1.0}, "new": {"a": 2.0}}


def test_a_predicate_edited_under_a_held_id_shows_the_claim_and_the_operands():
    """Review round 1. `Part.requires(expr, id=...)` lets an author keep the
    id while rewriting the predicate — §3's flagship weakening move, one
    field over from the `limit` case #293 was about — and that produces
    `claim` and `operands` on ONE entry. Every other case here moves one or
    the other, so a fix suppressing either whenever the other is present
    passed the whole suite.

    Both halves are needed and neither substitutes: the claim says the author
    rewrote the test, the operands say the inputs moved under it, and `fixed`
    with only one of them is the reading §3 wrote the rule to prevent."""
    old = _two_requires("pass", {"d": 3.0}, "fail", {"bore_d": 28.0, "plate_y": 30.0})
    new = _two_requires("pass", {"d": 3.0}, "pass", {"bore_d": 26.0, "plate_y": 30.0})
    next(c for c in old["checks"] if c["id"] == "fits")["expr"] = "bore_d <= plate_y - 4"
    next(c for c in new["checks"] if c["id"] == "fits")["expr"] = "bore_d <= plate_y"

    entry = next(c for c in _diff(old, new)["checks"] if c["id"] == "fits")
    assert entry["change"] == "fixed"
    assert entry["claim"] == {
        "old": {"expr": "bore_d <= plate_y - 4"},
        "new": {"expr": "bore_d <= plate_y"},
    }
    assert entry["operands"] == {
        "old": {"bore_d": 28.0, "plate_y": 30.0},
        "new": {"bore_d": 26.0, "plate_y": 30.0},
    }
    # The headline still qualifies on the claim alone (§3), and the entry
    # carrying operands as well does not change that count.
    assert summary_of(_diff(old, new), new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed)"
    )


def test_an_operand_that_stopped_being_recorded_is_a_moved_operand():
    """The runner writes `operands: {}` for a `requires` check it skipped
    (`runner.py`), so the map emptying is the real shape of a check that
    stopped being evaluated — and an entry saying only `fixed` there hides
    that the expression was never read. The reverse, a map that gained an
    operand, is the same comparison and is pinned with it."""
    recorded = {"a": 1.0, "b": 2.0, "c": 4.0}
    old = _two_requires("pass", {"d": 3.0}, "pass", recorded)
    new = _two_requires("skipped", {"d": 3.0, "h": 9.0}, "skipped", {})

    entries = {c["id"]: c for c in _diff(old, new)["checks"] if c["kind"] == "requires"}
    assert entries["fits"]["operands"] == {"old": recorded, "new": {}}
    assert entries["clears"]["operands"] == {"old": {"d": 3.0}, "new": {"d": 3.0, "h": 9.0}}


def test_moved_operands_are_not_counted_as_a_moved_claim_on_the_headline():
    """§3 gives the `regressed`/`fixed` qualifier to a moved *claim* and to
    nothing else: `operands` is a result, listed in `NON_CLAIM_FIELDS` as
    such. A qualifier that counted them would report a part whose inputs
    moved as a contract that was edited, which is #293's accusation aimed at
    an innocent run."""
    old = _two_requires("pass", {"d": 3.0, "h": 9.0}, "pass", {"a": 1.0, "b": 2.0, "c": 4.0})
    new = _two_requires("fail", {"d": 12.0, "h": 9.0}, "fail", {"a": 1.0, "b": 28.0, "c": 4.0})

    doc = _diff(old, new)
    assert sum(1 for c in doc["checks"] if "operands" in c) == 2
    assert summary_of(doc, new).splitlines()[0] == "different: p — 2 regressed"


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


def test_a_payload_that_declares_no_claim_is_not_a_report():
    """#292. `schema_version` was the only structural gate, and `measure` and
    `render` carry the same one — and the same `tool`/`part` identity prefix —
    by design (SPEC-report.md's Scope). So such a payload walked through it, was
    read as having no checks, skipped the `counts.total` invariant for want of
    a `counts`, and came out `identical` at exit 0. "No differences found" is a
    positive claim (§2); a document that declared nothing cannot support one.

    Each discriminator alone and both together, on each side, because a guard
    reading one field answers for every other cell and a guard reading one
    side answers for the other. A null counts as absent: `"counts": null` used
    to reach `.get("total")` on a `None`, and the `AttributeError` left this
    function through the CLI's catch-all — the right exit under a Python type
    name for a message."""
    for absent in (("verdict",), ("counts",), ("verdict", "counts")):
        for side in ("old", "new"):
            for how in ("deleted", "nulled"):
                docs = {"old": _doc(), "new": _doc()}
                for field in absent:
                    if how == "deleted":
                        del docs[side][field]
                    else:
                        docs[side][field] = None

                with pytest.raises(DiffUsageError) as excinfo:
                    _diff(docs["old"], docs["new"])
                message = str(excinfo.value)
                assert message.startswith(f"the {side} input is not a check report")
                for field in absent:
                    assert f"`{field}`" in message
                # And ONLY the missing one: a message naming both whatever is
                # wrong tells the reader to go and look at a field that is fine.
                for field in {"verdict", "counts"} - set(absent):
                    assert f"`{field}`" not in message


def test_the_refusal_states_the_inability_and_not_a_cause_it_does_not_know():
    """Review round 1. §2 rule 3 makes this a rule about wording: state the
    inability, do not state a cause. A genuine report with `verdict` stripped
    is malformed — it still carries `checks`, `counts`, `error` and `hint`,
    which this message's own field list prints — so telling its author it is
    probably a `measure` or `render` payload is a confident diagnosis of the
    wrong defect, contradicted inside the same sentence.

    Both branches, because a message that never names the payloads is as
    wrong as one that always does: the misrouted-artifact case is the one
    this guard was written for and it must still say so."""
    malformed = _doc()
    del malformed["verdict"]
    with pytest.raises(DiffUsageError) as excinfo:
        _diff(_doc(), malformed)
    assert "measure" not in str(excinfo.value)
    assert "render" not in str(excinfo.value)
    assert "cannot say" in str(excinfo.value)

    payload = {"schema_version": _doc()["schema_version"], "part": {"id": "p"}, "renders": {}}
    with pytest.raises(DiffUsageError) as excinfo:
        _diff(_doc(), payload)
    assert "a `measure` or `render` payload" in str(excinfo.value)


def test_the_refusal_names_the_payload_it_was_handed():
    """The failure this closes is a reader wired to the wrong artifact, so the
    message has to let them see which artifact that was — naming the fields
    the thing actually carries, rather than only the ones it does not."""
    payload = {"schema_version": _doc()["schema_version"], "part": {"id": "p"}, "renders": {}}
    with pytest.raises(DiffUsageError, match="renders"):
        _diff(_doc(), payload)


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


# --------------------------------------------------------------------------
# environment.packages — the field SPEC-report §8 says MUST NOT be excluded
# --------------------------------------------------------------------------


def _with_packages(doc: dict, packages: dict) -> dict:
    doc["environment"] = {**doc["environment"], "packages": packages}
    return doc


def test_a_moved_package_version_is_named_on_an_otherwise_identical_diff():
    """The paragraph's own example: a trimesh upgrade moved a number.

    `SPEC-report.md` §8 rule 2 says in bold that `environment.packages` MUST
    NOT be excluded from comparison, and this comparator excluded it entirely
    until #211 — so the one fact that distinguishes "a dependency upgrade moved
    this" from "the design changed" was recorded in every report and read in
    none of them.
    """
    old = _with_packages(_doc(), {"trimesh": "5.0.0", "numpy": "2.5.2"})
    new = _with_packages(_doc(), {"trimesh": "5.1.0", "numpy": "2.5.2"})

    doc = _diff(old, new)
    assert doc["environment"]["packages"]["changed"] == {
        "trimesh": {"old": "5.0.0", "new": "5.1.0"}
    }
    assert doc["environment"]["packages"]["added"] == {}
    assert doc["environment"]["packages"]["removed"] == {}
    # Context, not a finding: same rule as engine_version.
    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0
    assert "packages moved: trimesh 5.0.0 → 5.1.0" in summary_of(doc, new)


def test_a_package_that_appeared_is_not_reported_as_a_version_move():
    """Two facts, two message forms.

    A version that moved is a changed build input and explains a moved
    measurement. A package present on one side only is usually two machines
    resolving different transitive dependency sets — CI against a laptop — and
    explains nothing on its own. Folding them into one list would leave the
    reader to work out which had happened, which is the work the field exists
    to remove.

    Two 0.7.5-shaped reports, because an appearance against a baseline that
    predates the field's widening is a third thing and is reported as one.
    """
    old = _with_packages(_python_doc(), {"trimesh": "5.0.0", "vtk": "9.6.2"})
    new = _with_packages(_python_doc(), {"trimesh": "5.0.0", "shapely": "2.1.2"})

    packages = _diff(old, new)["environment"]["packages"]
    assert packages["changed"] == {}
    assert packages["added"] == {"shapely": "2.1.2"}
    assert packages["removed"] == {"vtk": "9.6.2"}

    summary = summary_of(_diff(old, new), new)
    assert "packages appeared: shapely 2.1.2" in summary
    assert "packages disappeared: vtk 9.6.2" in summary
    assert "moved" not in summary, f"an appearance reported as a version move: {summary}"


def test_an_unchanged_package_set_says_nothing():
    """Reported only when it changed, like every other environment key. An
    entry per unchanged distribution would bury the finding in ceremony, and
    the inventory now runs to dozens of entries."""
    doc = _diff(
        _with_packages(_doc(), {"trimesh": "5.0.0"}), _with_packages(_doc(), {"trimesh": "5.0.0"})
    )
    assert "packages" not in doc["environment"]
    assert (
        summary_of(doc, _with_packages(_doc(), {"trimesh": "5.0.0"}))
        == "identical: p — no semantic differences"
    )


def test_the_summary_bounds_a_wall_of_package_noise():
    """Two runs on different machines can differ in dozens of distributions.
    The artifact carries every one; the one-line summary names two per group
    and counts the rest, or it stops being one line."""
    old = _with_packages(_doc(), {f"dist{i}": "1.0" for i in range(9)})
    new = _with_packages(_doc(), {f"dist{i}": "2.0" for i in range(9)})

    doc = _diff(old, new)
    assert len(doc["environment"]["packages"]["changed"]) == 9, "the artifact keeps all of them"
    summary = summary_of(doc, new)
    assert "packages moved: dist0 1.0 → 2.0, dist1 1.0 → 2.0, +7 more" in summary
    assert len(summary.splitlines()) == 1


def test_a_report_with_no_packages_map_says_so_rather_than_nothing():
    """Silence must not read as "no dependency moved".

    An older report, or a hand-written one, may carry no `environment.packages`
    map. Omitting the key would be indistinguishable from a comparison that ran
    and found nothing — the exact silence-as-success shape the tool refuses. It
    is stated, and it changes no outcome: the diff still runs.
    """
    old = _doc()
    old["environment"] = {"python": "3.12.7"}
    doc = _diff(old, _with_packages(_doc(), {"trimesh": "5.0.0"}))

    assert (
        doc["environment"]["packages"]["uncomparable"]
        == "no environment.packages map on the old side, so whether a dependency moved is unknown"
    )
    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0
    assert "packages not compared:" in summary_of(doc, _with_packages(_doc(), {"trimesh": "5.0.0"}))

    both = _diff(old, {**_doc(), "environment": {"python": "3.12.7"}})
    assert "on both sides" in both["environment"]["packages"]["uncomparable"]


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
    # The reason must say the closure is ABSENT. A first cut of the #190
    # rewrite phrased this branch as "the old report carries a source
    # closure", which states the opposite of the condition that reached it —
    # code right, words wrong, on the one line a reader acts on.
    assert result["indeterminate"][0]["reason"].startswith(
        "no differences found, but neither report carries a source closure,"
    )
    one_side = _doc()
    one_side["part"].pop("source_closure")
    assert (
        "the old report carries no source closure"
        in (_diff(one_side, _doc())["indeterminate"][0]["reason"])
    )


# --------------------------------------------------------------------------
# end to end, on real runs
# --------------------------------------------------------------------------

from support import needs_build123d, needs_scad_tier  # noqa: E402


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


@needs_scad_tier
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


@needs_scad_tier
def test_cli_a_check_that_stopped_being_evaluated_is_not_reported_as_a_repair(
    tmp_path: Path,
):
    """#325's own reproduction. A failing `envelope`, then a `requires`
    precondition breaks so the geometry phase never runs — and the check that
    stopped being evaluated was filed in the same bucket as a genuine repair,
    with an unqualified `1 fixed` on the console."""
    scad = tmp_path / "plate.scad"
    # Both parameters are declared: partspec refuses a `-D` that matches no
    # top-level variable rather than letting the engine drop it silently.
    scad.write_text("bore_d = 8;\nplate_y = 30;\ncube([40, 30, 6]);\n")
    contract = tmp_path / "spec.py"

    def write(bore_d: float) -> None:
        contract.write_text(
            "from partspec import Part, openscad\n\n\n"
            "def make() -> Part:\n"
            f"    p = Part('plate', openscad('plate.scad', bore_d={bore_d}, plate_y=30.0))\n"
            "    p.requires('bore_d <= plate_y')\n"
            "    p.envelope(max=(40, 30, 4))\n"
            "    return p\n"
        )

    target = f"{contract}:make"
    write(8.0)
    assert _run_cli("check", target, "--out", str(tmp_path / "a"), "--quiet")[0] == 1
    write(48.0)  # breaks the precondition, so the geometry phase never runs
    assert _run_cli("check", target, "--out", str(tmp_path / "b"), "--quiet")[0] == 1

    code, out, err = _run_cli(
        "diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "b" / "report.json")
    )
    assert code == 1, err
    entry = next(c for c in json.loads(out)["checks"] if c["id"] == "envelope")
    assert entry["change"] == "fixed"
    assert entry["status"] == {"old": "fail", "new": "skipped"}
    assert entry["answered"] == {"old": True, "new": False}
    assert "1 fixed (1 not answered)" in err.splitlines()[0]


@needs_scad_tier
def test_cli_a_loosened_bound_shows_the_drift_it_was_covering(tmp_path: Path):
    """#330, end to end and on the flagship shape. The bound is loosened and
    the parameter it bounds moves toward it in the same edit; both sides pass,
    so no status changes and the entry is `limit_changed`. Reporting the
    contract edit alone tells the reader the bound moved and the part did not,
    which is §1's second job dropped on the one entry where the two facts
    explain each other."""
    scad = tmp_path / "plate.scad"
    scad.write_text("wall = 2.9;\ncube([40, 30, 6]);\n")
    contract = tmp_path / "spec.py"

    def write(wall: float, minimum: float) -> None:
        contract.write_text(
            "from partspec import Part, openscad\n\n\n"
            "def make() -> Part:\n"
            f"    p = Part('plate', openscad('plate.scad', wall={wall}))\n"
            f"    p.param('wall', min={minimum})\n"
            "    return p\n"
        )

    target = f"{contract}:make"
    write(2.9, 2.0)
    assert _run_cli("check", target, "--out", str(tmp_path / "a"), "--quiet")[0] == 0
    write(2.1, 1.0)
    assert _run_cli("check", target, "--out", str(tmp_path / "b"), "--quiet")[0] == 0

    code, out, err = _run_cli(
        "diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "b" / "report.json")
    )
    assert code == 1, err
    entry = next(c for c in json.loads(out)["checks"] if c["id"] == "param:wall")
    assert entry["change"] == "limit_changed"
    assert entry["claim"] == {"old": {"limit": {"min": 2.0}}, "new": {"limit": {"min": 1.0}}}
    assert entry["value"]["old"] == pytest.approx(2.9)
    assert entry["value"]["new"] == pytest.approx(2.1)


@needs_scad_tier
def test_cli_a_loosened_predicate_shows_the_claim_and_the_operands(tmp_path: Path):
    """Review round 1, end to end. `Part.requires(expr, id=...)` lets an
    author hold the id and rewrite the predicate, so the weakening move #293
    is about reaches `requires` too — and there the numbers under the
    predicate are `operands`. Production emits both halves on one entry; no
    test observed it, which is how a fix suppressing either could have
    passed."""
    scad = tmp_path / "plate.scad"
    scad.write_text("plate_y = 30;\nbore_d = 28;\nwall = 2;\ncube([40, plate_y, 6]);\n")
    contract = tmp_path / "spec.py"

    def write(bore_d: float, expr: str) -> None:
        contract.write_text(
            "from partspec import Part, openscad\n\n\n"
            "def make() -> Part:\n"
            "    p = Part('plate', openscad('plate.scad', plate_y=30.0, "
            f"bore_d={bore_d}, wall=2.0))\n"
            f"    p.requires({expr!r}, id='fits')\n"
            "    return p\n"
        )

    target = f"{contract}:make"
    # The bore grows past the wall the predicate protects, and the predicate is
    # loosened until it passes anyway: the part got worse and the claim moved.
    write(28.0, "bore_d + 2 * wall <= plate_y")
    assert _run_cli("check", target, "--out", str(tmp_path / "a"), "--quiet")[0] == 1
    write(34.0, "bore_d + 2 * wall <= 2 * plate_y")
    assert _run_cli("check", target, "--out", str(tmp_path / "b"), "--quiet")[0] == 0

    code, out, err = _run_cli(
        "diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "b" / "report.json")
    )
    assert code == 1, err
    entry = next(c for c in json.loads(out)["checks"] if c["id"] == "fits")
    assert entry["change"] == "fixed"
    assert entry["claim"]["old"] == {"expr": "bore_d + 2 * wall <= plate_y"}
    assert entry["claim"]["new"] == {"expr": "bore_d + 2 * wall <= 2 * plate_y"}
    assert entry["operands"]["old"]["bore_d"] == pytest.approx(28.0)
    assert entry["operands"]["new"]["bore_d"] == pytest.approx(34.0)
    # `builds` was skipped behind the failing precondition on the old side and
    # runs on the new one, so the bucket holds two — and the qualifier still
    # counts the one entry whose claim moved.
    assert err.splitlines()[0] == "different: plate — 2 fixed (1 with the claim changed)"


@needs_scad_tier
def test_cli_diff_refuses_two_measure_payloads_instead_of_calling_them_identical(
    tmp_path: Path,
):
    """#292's reproduction, end to end. The two runs are of genuinely
    different geometry — a plate that grew 4mm — and `measure` records the
    difference in the payloads it writes. Compared, they used to answer
    `identical` at exit 0, which is what a CI gate reads."""
    scad = tmp_path / "plate.scad"
    scad.write_text("cube([30, 20, 4]);\n")
    contract = tmp_path / "spec.py"
    contract.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def make() -> Part:\n"
        "    p = Part('plate', openscad('plate.scad'))\n"
        "    p.envelope(max=(40, 30, 10))\n"
        "    return p\n"
    )
    target = f"{contract}:make"

    code, first, _ = _run_cli("measure", target)
    assert code == 0
    scad.write_text("cube([30, 20, 8]);\n")
    code, second, _ = _run_cli("measure", target)
    assert code == 0
    # The payloads really do differ, so a refusal here is not a comparison
    # that found nothing.
    assert json.loads(first) != json.loads(second)

    for name, text in (("m1.json", first), ("m2.json", second)):
        (tmp_path / name).write_text(text)
    code, _, err = _run_cli("diff", str(tmp_path / "m1.json"), str(tmp_path / "m2.json"))
    assert code == 64, err
    assert "not a check report" in err


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


# --------------------------------------------------------------------------
# #190 stage 3: the gap-class rule
# --------------------------------------------------------------------------

SENTENCE = "nothing this diff can see changed, which is not the same claim as nothing changed"
"""The load-bearing half of every indeterminate message.

It says what the verdict means, and #190 is explicit that it must not change
while the rule around it does: an indeterminate that stopped saying this
would be an exit code with no argument attached."""


def _python_doc(
    imports: dict | None = None,
    unseen: list[str] | None = None,
    preloaded: list[str] | None = None,
    reached: list[str] | None = None,
    **overrides,
) -> dict:
    """A report whose closure has the 0.7.5 shape — the Python tier's.

    `reached` is omitted entirely when not asked for, which is the pre-#216
    producer shape every other test in this file exercises.
    """
    doc = _doc(**overrides)
    doc["part"]["source_closure"] = {
        "digest": "sha256:k1",
        "files": 2,
        "scope": "model_directory",
        "partial": True,
        "imports": {} if imports is None else imports,
        "preloaded": [] if preloaded is None else preloaded,
        "unseen": ["native_reads"] if unseen is None else unseen,
    }
    if reached is not None:
        doc["part"]["source_closure"]["reached"] = reached
    return doc


def _dist(version: str | None, digest: str, identity: str = "metadata") -> dict:
    return {"identity": identity, "version": version, "digest": f"sha256:{digest}"}


def _unidentified() -> dict:
    return {"identity": "unidentified", "version": None, "digest": None}


def test_an_irreducible_gap_alone_no_longer_blocks_the_identical_claim():
    """#190's headline. `native_reads` is present in every Python-tier report
    that will ever be written, so it cannot discriminate between two of them,
    and a verdict that cannot discriminate is not evidence. It is printed on
    every outcome instead — which is the whole of the mitigation, so the line
    is asserted here and not merely the exit code."""
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}
    doc = _diff(_python_doc(imports), _python_doc(imports))

    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0
    assert doc["source"]["closure"] == "same"
    assert (
        "  not covered: files read inside C extensions — irreducible on the Python tier"
        in summary_of(doc, _python_doc(imports)).splitlines()
    )
    # Permanent output, so it is written in English: `1 distributions` was
    # there while the `files` count on the same line was pluralised properly.
    assert "  covered: model directory (2 files); 1 imported distribution, all unchanged" in (
        summary_of(doc, _python_doc(imports)).splitlines()
    )
    two = {"cqgridfinity": _dist("0.5.7", "aaa"), "vtk": _dist("9.6.2", "ccc")}
    assert "; 2 imported distributions, all unchanged" in summary_of(
        _diff(_python_doc(two), _python_doc(two)), _python_doc(two)
    )


def test_a_library_that_moved_under_an_unchanged_part_is_identical_and_named():
    """The version-bump gate finally answering: exit 0, because OpenSCAD
    already gets exit 0 for a changed `.scad` closure with no moved check and
    a second rule for Python would rebuild the asymmetry #190 removes. The
    moved distribution named on the headline is what makes that acceptable —
    an unqualified "no semantic differences" here would be the silence."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa")})
    new = _python_doc({"cqgridfinity": _dist("0.6.0", "bbb")})

    doc = _diff(old, new)
    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0
    assert doc["source"]["closure"] == "changed"
    assert doc["source"]["imports"]["changed"]["cqgridfinity"]["new"]["version"] == "0.6.0"

    summary = summary_of(doc, new)
    assert summary.splitlines()[0] == (
        "identical: p — no semantic differences; inputs moved: cqgridfinity 0.5.7 → 0.6.0"
    )
    assert "  every declared claim held across the change" in summary.splitlines()
    assert "  not covered: files read inside C extensions" in summary


def test_a_moved_model_directory_alone_still_holds_the_claims_line():
    """The other half of the gate on that sentence, and the commonest real
    case: an edited model directory with no import movement at all.

    Every positive test around it holds the closure digest equal and moves a
    version instead, so the digest half went unexecuted — mutating
    `closure_digest_changed` out of the gate deleted the line from exactly
    this case with 934 tests still green.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}
    old = _python_doc(dict(imports))
    new = _python_doc(dict(imports))
    new["part"]["source_closure"]["digest"] = "sha256:moved"

    doc = _diff(old, new)
    assert doc["outcome"] == "identical"
    assert doc["source"]["closure"] == "changed"
    assert doc["source"]["closure_digest_changed"] is True
    assert doc["source"]["imports"]["changed"] == {}, "the digest alone, no import movement"
    assert "  every declared claim held across the change" in summary_of(doc, new).splitlines()


def _verdict_doc(status: Status | None, imports: dict) -> dict:
    """A 0.7.5-shaped report whose single check has `status`, and whose verdict
    is therefore DERIVED rather than asserted — the point being to exercise the
    real path from a check's outcome to the sentence, not to stub the verdict.
    """
    report = Report(
        part_id="p",
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
                status=status,
                measurement=Measurement(1.5, "mm"),
                limit=Limit(min=2.0),
            )
        ]
        if status is not None
        else [],
    )
    doc = report.to_json()
    doc["part"]["source_closure"] = {
        "digest": "sha256:k1",
        "files": 2,
        "scope": "model_directory",
        "partial": True,
        "imports": imports,
        "preloaded": [],
        "unseen": ["native_reads"],
    }
    return doc


@pytest.mark.parametrize(
    ("status", "verdict", "sentence"),
    [
        (Status.PASS, "pass", "every declared claim held across the change"),
        (
            Status.FAIL,
            "fail",
            "no declared claim changed status across the change — both sides fail",
        ),
        (
            Status.UNSUPPORTED,
            "incomplete",
            "no declared claim changed status across the change — both sides incomplete",
        ),
        (None, "empty", "neither side declared a claim, so none held across the change"),
    ],
)
def test_the_claims_line_says_what_the_claims_actually_did(status, verdict, sentence):
    """#220: the sentence was unconditional, and "held" is only true of one of
    these four.

    Two reports whose SAME check fails identically on both sides were told
    `every declared claim held across the change`. It did not hold — it failed,
    twice. `identical` at exit 0 is right and unchanged; only the sentence was
    wrong, in permanent output, on the honesty line the #190 work added
    precisely to stop a silent claim.

    `empty` is the one worth reading twice: no DECLARED claim makes "every
    declared claim held" vacuously true, which is the shape this project exists
    to refuse rather than a technicality it gets to lean on. Zero *declared*
    checks, not zero checks — a real `empty` report carries the `builds` check
    partspec adds itself, which
    `test_an_empty_report_carries_one_check_not_zero` covers.

    The verdict is derived from the check rather than stubbed, so this
    exercises the real path from an outcome to the sentence.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}
    old = _verdict_doc(status, dict(imports))
    new = _verdict_doc(status, {"cqgridfinity": _dist("0.6.0", "bbb")})

    assert old["verdict"] == verdict, "premise: the check drives the verdict"
    doc = _diff(old, new)
    assert doc["outcome"] == "identical", "premise: nothing about the reports differs"
    assert exit_code_of(doc["outcome"]) == 0, "and the verdict is not what changed"

    lines = summary_of(doc, new).splitlines()
    assert f"  {sentence}" in lines, lines
    if verdict != "pass":
        assert not any("every declared claim held" in line for line in lines), (
            "a claim that did not hold must not be reported as one that did"
        )


def test_a_failing_build_is_a_claim_that_did_not_hold():
    """The blocker round 2 found: `builds` was excluded one question too far.

    `Report.verdict` excludes implicit kinds from the EMPTINESS test — partspec
    adds `builds`, so a contract asserting nothing would otherwise look
    asserted — and then collapses status over EVERY check, because a build that
    failed is a claim that failed. The first fix applied the exclusion to both
    questions, so a model that does not compile, with one passing declared
    claim beside the failure, was told `every declared claim held across the
    change` — #220 reproduced by its own fix, on two reports `partspec check`
    wrote unmodified.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}

    def with_failing_build(imps: dict) -> dict:
        doc = _verdict_doc(Status.PASS, imps)
        doc["checks"].append(
            {"id": "builds", "kind": "builds", "phase": "geometry", "status": "fail"}
        )
        doc["counts"]["total"] = len(doc["checks"])
        return doc

    old = with_failing_build(dict(imports))
    new = with_failing_build({"cqgridfinity": _dist("0.6.0", "bbb")})
    assert [c["status"] for c in new["checks"]] == ["pass", "fail"], "premise: one of each"

    lines = summary_of(_diff(old, new), new).splitlines()
    assert "  no declared claim changed status across the change — both sides fail" in lines
    assert not any("every declared claim held" in line for line in lines), (
        "the model does not compile; nothing about it held"
    )


def test_one_claim_passing_beside_one_failing_is_not_every_claim_holding():
    """The boundary the function exists to draw, which no fixture crossed.

    Every case in the parametrisation above carries exactly ONE declared check,
    so `statuses == {"pass"}` and `"pass" in statuses` are indistinguishable —
    and swapping the equality for membership passed the whole suite (round-2
    review of #239). Under that mutant a report with one passing and one
    failing declared claim prints the strong sentence: #220 verbatim.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}

    def mixed(imps: dict) -> dict:
        doc = _verdict_doc(Status.PASS, imps)
        doc["checks"].append(
            {"id": "genus", "kind": "genus", "phase": "geometry", "status": "fail"}
        )
        doc["counts"]["total"] = len(doc["checks"])
        return doc

    old = mixed(dict(imports))
    new = mixed({"cqgridfinity": _dist("0.6.0", "bbb")})

    lines = summary_of(_diff(old, new), new).splitlines()
    assert "  no declared claim changed status across the change — both sides fail" in lines
    assert not any("every declared claim held" in line for line in lines)


def test_a_forged_verdict_cannot_buy_the_strong_sentence():
    """The first fix keyed on the artifact's `verdict`, which is copied from
    the input and cross-checked against nothing (adversarial review of #239).

    A report claiming `pass` over a failing check therefore printed #220's
    sentence verbatim — the fix reproducing the defect it closed — and one
    claiming `empty` over a report full of checks printed a NEW falsehood. The
    sentence is read off the checks now, which `diff` has already joined and
    compared, so the claim rests on evidence rather than on a self-report.

    `diff` states this standard itself: a guarantee that holds only for reports
    we produced is not one the comparator may assume.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}
    old = _verdict_doc(Status.FAIL, dict(imports))
    new = _verdict_doc(Status.FAIL, {"cqgridfinity": _dist("0.6.0", "bbb")})
    assert old["checks"] and old["checks"][0]["status"] == "fail", "premise: it failed"

    for forged in ("pass", "empty"):
        old["verdict"] = new["verdict"] = forged
        lines = summary_of(_diff(old, new), new).splitlines()
        assert "  no declared claim changed status across the change — both sides fail" in lines
        assert not any("every declared claim held" in line for line in lines), forged
        assert not any("neither side declared a claim" in line for line in lines), forged


def test_an_empty_report_carries_one_check_not_zero():
    """The shape a real `empty` run writes, which the first fix's fixture did
    not have.

    `builds` is added by partspec, so a contract asserting nothing still
    produces one passing check — that is exactly why `Report.verdict` excludes
    it from the emptiness test, and why `diff` must too. A fixture with
    `checks: []` exercises a shape no partspec run emits, and the first version
    of this slice tested only that one (adversarial review of #239).
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}

    def only_builds(imps: dict) -> dict:
        doc = _verdict_doc(None, imps)
        doc["checks"] = [{"id": "builds", "kind": "builds", "phase": "geometry", "status": "pass"}]
        doc["counts"] = {"total": 1, "pass": 1, "fail": 0}
        return doc

    old = only_builds(dict(imports))
    new = only_builds({"cqgridfinity": _dist("0.6.0", "bbb")})
    doc = _diff(old, new)

    assert doc["outcome"] == "identical"
    lines = summary_of(doc, new).splitlines()
    assert "  neither side declared a claim, so none held across the change" in lines
    assert not any("every declared claim held" in line for line in lines), (
        "one implicit passing check is not a claim that held"
    )


def test_the_covered_line_claims_nothing_about_the_claims():
    """#220 asked for the neighbouring phrasing to be checked for the same
    overreach. It does not have it, and this pins that.

    `covered:` is built by `_covered_clause` from the closure and the imports —
    it describes which INPUTS the comparison could account for, and says
    nothing about what the checks did. That separation is the reason the claims
    line could be wrong on its own.
    """
    imports = {"cqgridfinity": _dist("0.5.7", "aaa")}
    old = _verdict_doc(Status.FAIL, dict(imports))
    new = _verdict_doc(Status.FAIL, {"cqgridfinity": _dist("0.6.0", "bbb")})

    covered = next(
        line
        for line in summary_of(_diff(old, new), new).splitlines()
        if line.startswith("  covered: ")
    )
    # The equality alone. A word-loop beside it was dead below it in the first
    # version and merely subsumed after being reordered — any input that trips
    # a forbidden word also fails the equality, so it never had discriminating
    # power (round-2 review of #239). What the loop was FOR is written down
    # instead: this line is built by `_covered_clause` from the closure and the
    # imports, and adjudicates nothing.
    assert covered == "  covered: model directory (2 files); 1 imported distribution, 1 changed"


def test_a_regression_beside_a_moved_library_names_the_input_that_moved():
    """SPEC-report §8 rule 2's stated purpose: the reader must not have to
    guess whether the dependency bump or the design moved the number."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa")})
    new = _python_doc({"cqgridfinity": _dist("0.6.0", "bbb")})
    new["checks"][0]["status"] = "fail"
    new["counts"]["pass"] -= 1
    new["counts"]["fail"] = 1

    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    assert exit_code_of(doc["outcome"]) == 1
    summary = summary_of(doc, new)
    assert summary.splitlines()[0] == (
        "different: p — 1 regressed; inputs moved: cqgridfinity 0.5.7 → 0.6.0"
    )
    # Permanently, on every outcome — a caveat printed only on the clean path
    # would be worth less than the verdict it replaced.
    assert "  not covered: files read inside C extensions" in summary


def test_a_bounded_gap_still_blocks_the_identical_claim():
    """`unidentified_imports` is a gap a run could in principle close, so it
    keeps doing what `partial` used to do for every gap alike."""
    imports = {
        "cqgridfinity": _dist("0.5.7", "aaa"),
        "shims": {"identity": "unidentified", "version": None, "digest": None},
    }
    unseen = ["native_reads", "unidentified_imports"]
    doc = _diff(_python_doc(imports, unseen), _python_doc(imports, unseen))

    assert doc["outcome"] == "indeterminate"
    assert exit_code_of(doc["outcome"]) == 2
    assert doc["source"]["closure"] == "inconclusive"
    assert doc["indeterminate"][0]["code"] == "partial_closure"
    assert doc["indeterminate"][0]["reason"] == (
        "no differences found, but 1 import could not be identified (shims: a namespace "
        "package, which has no file on disk for partspec to hash, and no partspec option "
        f"closes that), so {SENTENCE}"
    )
    assert SENTENCE in summary_of(doc, _python_doc(imports, unseen))


def test_an_unrecognised_gap_token_is_read_as_a_gap():
    """SPEC-report §8.3 makes this a MUST, and it is the only rule that keeps
    a closed vocabulary safe to extend: an older `diff` reading a newer
    report goes inconclusive rather than ignoring a gap it cannot name."""
    unseen = ["native_reads", "runtime_data_reads"]
    doc = _diff(_python_doc(unseen=unseen), _python_doc(unseen=unseen))

    assert doc["outcome"] == "indeterminate"
    assert exit_code_of(doc["outcome"]) == 2
    assert "runtime_data_reads" in doc["indeterminate"][0]["reason"]
    assert SENTENCE in doc["indeterminate"][0]["reason"]
    assert list(doc["source"]["unseen"]["bounded"]) == ["runtime_data_reads"]


def test_an_install_that_changed_tier_is_a_changed_input_not_a_gap():
    """`metadata` on one side and `content` on the other is an ordinary
    install against an editable one or a `sys.path` checkout. The install
    genuinely is a different build input, and the two digests are over
    different things — RECORD rows against bytes — so they cannot be compared
    for sameness at all."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa", identity="metadata")})
    new = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa", identity="content")})

    doc = _diff(old, new)
    assert doc["source"]["closure"] == "changed"
    assert "cqgridfinity" in doc["source"]["imports"]["changed"]
    assert "inputs moved: cqgridfinity metadata → content install" in summary_of(doc, new)


def test_an_import_that_appeared_is_not_reported_as_a_version_move():
    """Design risk R4, one layer below the same split in
    `environment.packages`: two machines resolving different transitive sets
    explain nothing about the part, and folding them in with a version bump
    would leave the reader to separate them by hand."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa"), "vtk": _dist("9.6.2", "ccc")})
    new = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa"), "shapely": _dist("2.1.2", "ddd")})

    doc = _diff(old, new)
    imports = doc["source"]["imports"]
    assert imports["changed"] == {}
    assert list(imports["added"]) == ["shapely"]
    assert list(imports["removed"]) == ["vtk"]
    summary = summary_of(doc, new)
    assert "inputs appeared: shapely 2.1.2" in summary
    assert "inputs disappeared: vtk 9.6.2" in summary
    assert "moved" not in summary.splitlines()[0], f"an appearance read as a move: {summary}"


def test_an_inherited_import_is_not_reported_as_an_appearance():
    """The v0.7.5 pre-tag audit's blocker, reproduced from its own numbers.

    `imports` is read from `sys.modules`, so a Python part behind another
    target in one batch inherits its imports: the same build123d cube
    recorded 38 imports alone and 44 behind a CadQuery target. Diffed against
    itself — same part, same source, same versions — that said `inputs
    appeared: cadquery 2.8.0, casadi 3.7.2, +4 more`, which is a positive
    finding about build inputs assembled out of the batch order.

    The map still names all 44, because over-reporting cannot turn a real
    build input into silence. What changes is the claim made over it.
    """
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")})
    new = _python_doc(
        {"build123d": _dist("0.10.1", "aaa"), "cadquery": _dist("2.8.0", "bbb")},
        preloaded=["build123d", "cadquery"],
    )

    doc = _diff(old, new)
    assert doc["outcome"] == "identical", "the outcome is unchanged by the qualification"
    assert exit_code_of(doc["outcome"]) == 0
    assert doc["source"]["imports"]["added"] == {"cadquery": _dist("2.8.0", "bbb")}, (
        "the entry stays in the delta — the artifact loses nothing"
    )
    assert doc["source"]["imports"]["unattributable"] == ["cadquery"]
    assert doc["source"]["closure"] == "changed", "the recorded maps did differ"

    summary = summary_of(doc, new)
    assert "appeared" not in summary, f"an inherited import read as a finding: {summary}"
    assert summary.splitlines()[0] == (
        "identical: p — no semantic differences; inputs not attributable: cadquery 2.8.0 — "
        "on one side only, and already loaded when that target began, so this comparison "
        "cannot tell an input that moved from one inherited from an earlier target"
    )
    assert "  covered: model directory (2 files); 2 imported distributions, 1 not attributable" in (
        summary.splitlines()
    )
    assert "every declared claim held across the change" not in summary


def test_an_unattributable_difference_is_still_a_recorded_difference():
    """`closure` says what the two reports RECORDED; `unattributable` says
    what is unknown about it. Neither field does the other's job.

    Suppressing the entry here made the artifact read `closure: "same"` while
    carrying `imports.added: ["helper29"]` in the same object — sameness
    asserted over a difference it had recorded, which is the stage-3 review's
    B2 finding one field over. It costs no verdict: `different` is computed
    from checks alone and only `inconclusive` is outcome-bearing, so a
    `changed` closure falls through to `identical` at exit 0.
    """
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")}, preloaded=["build123d"])
    new = _python_doc(
        {"build123d": _dist("0.10.1", "aaa"), "helper29": _dist("1.0", "bbb")},
        preloaded=["build123d", "helper29"],
    )

    doc = _diff(old, new)
    assert doc["source"]["closure"] == "changed"
    assert doc["source"]["imports"]["unattributable"] == ["helper29"]
    assert doc["source"]["closure_digest_changed"] is False, "the map alone, not the digest"
    assert doc["outcome"] == "identical", "recording it moves no verdict"
    assert exit_code_of(doc["outcome"]) == 0

    # The sentence names "the change" as the part's, and no change was
    # attributed to the part — the headline states the inability instead.
    assert "every declared claim held across the change" not in summary_of(doc, new)


def test_two_reports_carrying_one_preloaded_set_say_nothing_about_it():
    """The qualification fires on movement, never on the field's presence.

    Two runs of one part in the same batch position inherit the same imports,
    and there is nothing to qualify: a caveat printed on every comparison
    would be noise, and noise is what taught three fleet agents to filter the
    `not covered:` line.
    """
    imports = {"build123d": _dist("0.10.1", "aaa"), "cadquery": _dist("2.8.0", "bbb")}
    new = _python_doc(dict(imports), preloaded=["cadquery"])
    doc = _diff(_python_doc(dict(imports), preloaded=["cadquery"]), new)
    assert doc["source"]["imports"]["unattributable"] == []
    summary = summary_of(doc, new)
    assert summary.splitlines()[0] == "identical: p — no semantic differences"
    assert "attributable" not in summary
    assert "  covered: model directory (2 files); 2 imported distributions, all unchanged" in (
        summary.splitlines()
    )


def test_an_appearance_the_batch_cannot_explain_keeps_todays_wording():
    """The qualification is bounded by the `preloaded` set, not by its
    existence. An import that appeared and was not inherited is exactly what
    v0.7.5 says it is, on the same line as one that was."""
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")})
    new = _python_doc(
        {
            "build123d": _dist("0.10.1", "aaa"),
            "cadquery": _dist("2.8.0", "bbb"),
            "shapely": _dist("2.1.2", "ccc"),
        },
        preloaded=["build123d", "cadquery"],
    )

    doc = _diff(old, new)
    assert doc["source"]["imports"]["unattributable"] == ["cadquery"]
    assert doc["source"]["closure"] == "changed", "the unexplained appearance is still movement"
    summary = summary_of(doc, new)
    assert "inputs appeared: shapely 2.1.2" in summary
    assert "inputs not attributable: cadquery 2.8.0" in summary


def test_an_unattributable_import_is_not_denied_to_have_moved():
    """The qualification states an inability and MUST NOT state a cause.

    `preloaded` evidences that this comparison cannot attribute the entry. It
    evidences nothing about *why* the entry is on one side, and the first cut
    of this clause said "the difference is its position in a batch, not an
    input that moved" — which the audit reproduced as false: a follower whose
    model began importing a shared module its leader's contract also imports
    is a genuine new build input, at batch position 2 of 2 in BOTH runs, and
    its content digest was sitting in `source.imports.added` while the line
    denied that anything had moved. Reversing the pair denies a real
    disappearance the same way.
    """
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")}, preloaded=["build123d"])
    new = _python_doc(
        {
            "build123d": _dist("0.10.1", "aaa"),
            "helper29": {**_dist(None, "bbb", "content"), "files": 1},
        },
        preloaded=["build123d", "helper29"],
    )

    doc = _diff(old, new)
    assert doc["source"]["imports"]["unattributable"] == ["helper29"]
    assert "helper29" in doc["source"]["imports"]["added"], "the evidence stays in the artifact"

    summary = summary_of(doc, new)
    assert "inputs not attributable: helper29" in summary
    assert "cannot tell an input that moved from one inherited from an earlier target" in summary
    for denial in ("not an input that moved", "position in a batch", "not the part"):
        assert denial not in summary, f"a real appearance reported as a non-event: {summary}"

    # Executed, not merely claimed: the disappearance is the OLD side's
    # `preloaded`, so this is also what holds the union to both halves —
    # reading only the new side's leaves this reporting `inputs disappeared`.
    backwards = _diff(new, old)
    assert list(backwards["source"]["imports"]["removed"]) == ["helper29"]
    assert backwards["source"]["imports"]["unattributable"] == ["helper29"]
    reversed_summary = summary_of(backwards, old)
    assert "disappeared" not in reversed_summary, (
        f"a real disappearance reported as a non-event: {reversed_summary}"
    )
    assert "inputs not attributable: helper29" in reversed_summary


def test_a_version_that_moved_under_an_inherited_import_is_still_a_move():
    """Attribution qualifies *who loaded it*, not *whether it moved*. A
    distribution present on both sides at two versions is a changed build
    input whichever target imported it first, and dropping that would be the
    under-report the wide map exists to avoid."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa")}, preloaded=["cqgridfinity"])
    new = _python_doc({"cqgridfinity": _dist("0.6.0", "bbb")}, preloaded=["cqgridfinity"])

    doc = _diff(old, new)
    assert doc["source"]["imports"]["unattributable"] == []
    assert doc["source"]["closure"] == "changed"
    assert "inputs moved: cqgridfinity 0.5.7 → 0.6.0" in summary_of(doc, new)


def test_an_inherited_import_beside_a_gap_does_not_claim_nothing_was_seen():
    """The indeterminate reason has two shapes and only one is true at a
    time (SPEC-diff §2 rule 3). An inherited import was observed, so the
    verbatim nothing-was-seen sentence must not be uttered — and it must not
    be counted as an import that appeared either."""
    old = _python_doc({"shims": _unidentified()}, unseen=["native_reads", "unidentified_imports"])
    new = _python_doc(
        {"shims": _unidentified(), "cadquery": _dist("2.8.0", "bbb")},
        unseen=["native_reads", "unidentified_imports"],
        preloaded=["cadquery"],
    )

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate", "the bounded gap still blocks, as before"
    assert exit_code_of(doc["outcome"]) == 2
    reason = doc["indeterminate"][0]["reason"]
    assert SENTENCE not in reason
    assert reason.startswith(
        "no declared claim changed, but 1 import on one side only cannot be attributed to "
        "either target;"
    )


def test_one_moved_library_is_named_once_not_twice():
    """Every entry of `source_closure.imports` is also an installed
    distribution, so the two clauses would otherwise both name a library bump
    on one line — in the exact case #190 exists for. The artifact keeps both
    maps whole; only the courtesy line dedupes."""
    old = _with_packages(
        _python_doc({"cqgridfinity": _dist("0.5.7", "aaa")}), {"cqgridfinity": "0.5.7"}
    )
    new = _with_packages(
        _python_doc({"cqgridfinity": _dist("0.6.0", "bbb")}), {"cqgridfinity": "0.6.0"}
    )

    doc = _diff(old, new)
    assert doc["environment"]["packages"]["changed"] == {
        "cqgridfinity": {"old": "0.5.7", "new": "0.6.0"}
    }
    assert summary_of(doc, new).splitlines()[0].count("cqgridfinity") == 1
    assert "packages moved" not in summary_of(doc, new)


# --------------------------------------------------------------------------
# #190 stage 3 review: the sentence must only be uttered where it is true
# --------------------------------------------------------------------------


def test_a_gap_beside_observed_movement_does_not_claim_nothing_was_seen():
    """Through v0.7.4 `digest != digest` returned `changed` BEFORE the partial
    check, so the load-bearing sentence was only reachable with matching
    digests and was always true. Removing that short-circuit — correctly —
    put it on comparisons that had demonstrably seen movement, one line above
    a line naming what moved. The sentence is unchanged and still verbatim
    where it holds; here it must not appear at all."""
    old = _python_doc({"cqgridfinity": _dist("0.5.7", "aaa"), "shims": _unidentified()})
    new = _python_doc({"cqgridfinity": _dist("0.6.0", "bbb"), "shims": _unidentified()})
    for doc in (old, new):
        doc["part"]["source_closure"]["unseen"] = ["native_reads", "unidentified_imports"]

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    reason = doc["indeterminate"][0]["reason"]
    assert SENTENCE not in reason, f"asserted nothing was seen while naming a move: {reason}"
    assert reason == (
        "no declared claim changed, but 1 imported distribution moved; 1 import could not "
        "be identified (shims: a namespace package, which has no file on disk for partspec "
        "to hash, and no partspec option closes that) — so the change this diff names is "
        "not necessarily all that changed"
    )
    summary = summary_of(doc, new)
    assert "inputs moved: cqgridfinity 0.5.7 → 0.6.0" in summary
    assert SENTENCE not in summary


def test_a_gap_beside_a_moved_closure_digest_names_the_digest():
    """The variant with no coverage block to contradict — two pre-0.7.5
    OpenSCAD reports, where `covered` is null and the false sentence would
    have stood alone under the headline."""
    old = _legacy(dict(LEGACY_SCAD_EXTERNAL))
    new = _legacy({**LEGACY_SCAD_EXTERNAL, "digest": "sha256:moved"})

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate"
    assert doc["indeterminate"][0]["reason"] == (
        "no declared claim changed, but the source closure digest moved; the model reads "
        "external data (import()/surface()) and this run carries no complete "
        "engine-reported input set, so which files those were is unrecorded (a successful "
        "render on an engine that accepts -d records them) — so the change this diff names "
        "is not necessarily all that changed"
    )
    assert SENTENCE not in summary_of(doc, new)
    # And the movement reaches the artifact, not only the prose.
    assert doc["source"]["closure_digest_changed"] is True


def test_a_moved_closure_digest_survives_an_inconclusive_verdict():
    """`source.closure` collapses to `inconclusive` under a bounded gap, and
    on v0.7.4 that field was the only record of closure movement — so a
    consumer keying on it went blind to input movement on exactly the
    comparisons where it matters most. It has its own field now."""
    old = _python_doc(unseen=["native_reads", "unidentified_imports"])
    new = _python_doc(unseen=["native_reads", "unidentified_imports"])
    new["part"]["source_closure"]["digest"] = "sha256:moved"

    doc = _diff(old, new)
    assert doc["source"]["closure"] == "inconclusive"
    assert doc["source"]["closure_digest_changed"] is True
    assert doc["source"]["digest_changed"] is False, "the entry-file digest is a separate fact"
    # Null, not False, where a side carries no closure: unasked is not "no".
    absent = _doc()
    absent["part"].pop("source_closure")
    assert _diff(absent, _doc())["source"]["closure_digest_changed"] is None


def test_a_partial_flag_that_contradicts_an_empty_unseen_fails_closed():
    """§8.3's invariant is `partial == bool(unseen)`. A report violating it is
    malformed, and the malformation CLOSEST to the real vocabulary was the one
    that escaped: v0.7.4 exits 2 on `partial: true`, and the first cut of the
    gap-class rule exited 0 because `unnamed_partial` was synthesised only on
    the pre-0.7.5 branch."""
    doc = _diff(_python_doc(unseen=[]), _python_doc(unseen=[]))
    assert doc["outcome"] == "indeterminate", "fail-open regression against v0.7.4"
    assert exit_code_of(doc["outcome"]) == 2
    assert list(doc["source"]["unseen"]["bounded"]) == ["unnamed_partial"]


@pytest.mark.parametrize("scope", ["model_directory", None], ids=["python", "openscad"])
def test_an_unreadable_closure_fails_closed_on_both_tiers(scope: str | None):
    """One malformation must not get two verdicts. Routing a non-list `unseen`
    through the pre-0.7.5 branch made it block on Python — via the `scope`
    guard — and exit 0 on OpenSCAD, which has no other gap to catch it."""
    closure = {"digest": "sha256:k1", "files": 2, "imports": {}, "unseen": "native_reads"}
    if scope:
        closure["scope"] = scope
    doc = _diff(_legacy(dict(closure)), _legacy(dict(closure)))

    assert doc["outcome"] == "indeterminate"
    assert exit_code_of(doc["outcome"]) == 2
    assert list(doc["source"]["unseen"]["bounded"]) == ["malformed_closure"]
    assert doc["indeterminate"][0]["reason"] == (
        "no differences found, but the old and new reports carry a source closure this "
        "diff cannot read (unseen is not the shape SPEC-report.md §8.3 defines), and a "
        f"closure that cannot be read is read as a gap, so {SENTENCE}"
    )


def test_a_preloaded_field_in_the_wrong_shape_fails_closed():
    """An uninterpretable field must not read as an empty one.

    A non-list `preloaded` was silently taken as "nothing preloaded", which
    put the entry back in the appeared group: measured, two closures carrying
    `"preloaded": "build123d,cadquery"` reported `identical: p — no semantic
    differences; inputs appeared: cadquery 2.8.0` at exit 0 — the positive
    claim this field exists to prevent, assembled out of a field the reader
    could not read. SPEC-diff §2 rule 3 already ruled it: a field present in
    the wrong shape is `malformed_closure`, on either tier.
    """
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")}, preloaded=[])
    new = _python_doc({"build123d": _dist("0.10.1", "aaa"), "cadquery": _dist("2.8.0", "bbb")})
    for doc_ in (old, new):
        doc_["part"]["source_closure"]["preloaded"] = "build123d,cadquery"

    doc = _diff(old, new)
    assert doc["outcome"] == "indeterminate", "an unreadable field must not exit 0"
    assert exit_code_of(doc["outcome"]) == 2
    assert list(doc["source"]["unseen"]["bounded"]) == ["malformed_closure"]
    assert "preloaded is not the shape" in doc["indeterminate"][0]["reason"]


@pytest.mark.parametrize(
    "closure",
    [
        {"digest": "sha256:k1", "files": 16},
        {"digest": "sha256:k1", "files": 16, "imports": {}, "unseen": []},
    ],
    ids=["pre-0.7.5", "0.7.5-openscad"],
)
def test_an_absent_preloaded_is_not_a_malformed_one(closure: dict):
    """The direction the shape check must never reach. `preloaded` is absent
    from every pre-0.7.5 closure and from every OpenSCAD one — whose render is
    a subprocess that imports nothing (§8.3 rule 7) — and absence is not a
    shape. Reading it as one would flip both to exit 2 on upgrade, which is
    the false alarm the whole absence rule exists to avoid."""
    doc = _diff(_legacy(dict(closure)), _legacy(dict(closure)))
    assert doc["outcome"] == "identical"
    assert exit_code_of(doc["outcome"]) == 0


def test_a_malformed_0_7_5_closure_is_not_blamed_on_its_age():
    """Fails closed either way, but `imports_not_recorded` names a cause —
    "written before partspec recorded imports" — and a remedy, re-record the
    baseline, that would not help a 0.7.5 report whose `imports` is the wrong
    shape. Absent and malformed are different states."""
    closure = {
        "digest": "sha256:k1",
        "files": 2,
        "scope": "model_directory",
        "imports": ["cqgridfinity"],
        "unseen": ["native_reads"],
    }
    doc = _diff(_legacy(dict(closure)), _legacy(dict(closure)))
    assert doc["outcome"] == "indeterminate"
    assert list(doc["source"]["unseen"]["bounded"]) == ["malformed_closure"]
    assert "0.7.4 or earlier" not in doc["indeterminate"][0]["reason"]
    assert "imports is not the shape" in doc["indeterminate"][0]["reason"]


def test_a_bounded_gap_is_stated_on_the_different_path_too():
    """It was silent there. "This diff is older than the report it read" is a
    fact about the tool and does not stop mattering because a check
    regressed — and `different: 1 regressed` with no note that the input
    inventory could not be compared invites the reading that the named
    regression is the whole story."""
    old = _python_doc(unseen=["native_reads", "runtime_data_reads"])
    new = _python_doc(unseen=["native_reads", "runtime_data_reads"])
    new["checks"][0]["status"] = "fail"
    new["counts"]["pass"] -= 1
    new["counts"]["fail"] = 1

    summary = summary_of(_diff(old, new), new)
    assert summary.splitlines()[0] == "different: p — 1 regressed"
    assert "  not covered: the old and new reports name a gap this diff does not recognise" in (
        summary
    )
    # And never twice: the indeterminate path states it in the headline.
    stated = summary_of(
        _diff(_python_doc(unseen=["runtime_data_reads"]), _python_doc()), _python_doc()
    )
    assert stated.count("does not recognise") == 1


def test_an_import_that_appeared_does_not_hide_a_package_that_moved():
    """Only `changed` against `changed` is a true duplicate. Matching by name
    across all three groups dropped a real upgrade off the human line: an
    import that *appeared* suppressed `packages moved: numpy 1.0.0 → 2.0.0`,
    which v0.7.4 printed."""
    old = _with_packages(_python_doc({}), {"numpy": "1.0.0"})
    new = _with_packages(_python_doc({"numpy": _dist("2.0.0", "n2")}), {"numpy": "2.0.0"})

    summary = summary_of(_diff(old, new), new)
    assert "packages moved: numpy 1.0.0 → 2.0.0" in summary
    assert "inputs appeared: numpy 2.0.0" in summary


def test_the_absent_closure_reason_chains_one_consequence_not_two():
    """The blocking phrase already ended in a `so` clause, and the caller
    appends another: "…beyond its entry file, so nothing this diff can see
    changed…". One observation, two consequences, on the line a reader acts
    on."""
    old, new = _doc(), _doc()
    for doc in (old, new):
        doc["part"].pop("source_closure")
    reason = _diff(old, new)["indeterminate"][0]["reason"]
    assert reason.count(", so ") == 1, reason
    assert reason.endswith(SENTENCE)


def test_a_files_count_that_moved_under_an_unchanged_digest_is_a_change():
    """`_content_digest` derives both from one walk, so they cannot honestly
    disagree; where they do, reading "all unchanged" off the digest is the
    failing-open direction."""
    old = _python_doc({"cqgridfinity": {**_dist(None, "aaa", "content"), "files": 16}})
    new = _python_doc({"cqgridfinity": {**_dist(None, "aaa", "content"), "files": 17}})
    assert _diff(old, new)["source"]["closure"] == "changed"


# --------------------------------------------------------------------------
# #190 stage 3 migration: what a pre-0.7.5 report gets
# --------------------------------------------------------------------------


def _legacy(closure: dict) -> dict:
    doc = _doc()
    doc["part"]["source_closure"] = closure
    return doc


LEGACY_PYTHON = {"digest": "sha256:k1", "files": 2, "scope": "model_directory", "partial": True}
LEGACY_SCAD_COMPLETE = {"digest": "sha256:k1", "files": 16}
LEGACY_SCAD_UNRESOLVED = {**LEGACY_SCAD_COMPLETE, "unresolved": ["missing.scad"], "partial": True}
LEGACY_SCAD_EXTERNAL = {**LEGACY_SCAD_COMPLETE, "reads_external_data": True, "partial": True}


@pytest.mark.parametrize(
    ("closure", "outcome"),
    [
        (LEGACY_PYTHON, "indeterminate"),
        (LEGACY_SCAD_COMPLETE, "identical"),
        (LEGACY_SCAD_UNRESOLVED, "indeterminate"),
        (LEGACY_SCAD_EXTERNAL, "indeterminate"),
    ],
    ids=["python", "scad-complete", "scad-unresolved", "scad-external-data"],
)
def test_a_pre_0_7_5_report_diffs_exactly_as_it_did_before(closure: dict, outcome: str):
    """The absence rule applies where the field could have carried an answer.

    SPEC-report §8.3 says a closure missing `imports` MUST NOT be read as an
    answer, and for the Python tier that reproduces today's exit 2 exactly.
    Blanket-applying it would have flipped the second row here from exit 0 to
    exit 2 on upgrade — a false alarm on a tier where `imports` was never a
    question that could have an answer, and stage 2 emits `"imports": {}` for
    OpenSCAD precisely so that absence stays unambiguous.
    """
    doc = _diff(_legacy(dict(closure)), _legacy(dict(closure)))
    assert doc["outcome"] == outcome
    assert exit_code_of(doc["outcome"]) == (0 if outcome == "identical" else 2)
    # A pre-0.7.5 pair also gets the output it got before: no coverage block
    # is invented for a report that never recorded coverage. The remedy is the
    # one line added under the headline, and only where there is one to name.
    trailing = summary_of(doc, _legacy(dict(closure))).splitlines()[1:]
    assert all(line.startswith("  remedy: ") for line in trailing), trailing


def test_a_pre_0_7_5_pair_whose_closure_moved_gets_no_orphaned_line():
    """`every declared claim held across the change` sits under `covered:` and
    reads off it. Emitted on its own — which is what two pre-0.7.5 reports
    got, since neither carries `unseen` and so neither gets a coverage
    block — it refers to a change nothing on the screen has named."""
    old = _legacy(dict(LEGACY_SCAD_COMPLETE))
    new = _legacy({**LEGACY_SCAD_COMPLETE, "digest": "sha256:moved"})

    doc = _diff(old, new)
    assert doc["outcome"] == "identical", "v0.7.4's answer, unchanged"
    assert doc["source"]["closure"] == "changed"
    assert doc["source"]["closure_digest_changed"] is True
    summary = summary_of(doc, new)
    assert summary == "identical: p — no semantic differences"
    assert "every declared claim held" not in summary


def test_the_message_for_a_pre_0_7_5_baseline_names_the_remedy():
    """Message (f): what a user upgrading sees, and why re-recording the
    baseline is the fix rather than a flag.

    Named in the output and in the artifact, not only in the specs: three
    documents and a comment said this comparison "names re-recording the
    baseline as the fix" while the code printed the cause and stopped, on the
    one exit 2 every upgrading user meets.
    """
    doc = _diff(_legacy(dict(LEGACY_PYTHON)), _python_doc())
    assert doc["indeterminate"][0]["reason"] == (
        "no differences found, but the old report was written before partspec recorded "
        f"imports (0.7.4 or earlier): its source identity covers one directory, so {SENTENCE}"
    )
    assert doc["indeterminate"][0]["remedy"] == (
        "re-record the baseline with this version — run `partspec check` over the old side "
        "again and keep that report — so both sides carry an import map"
    )
    assert summary_of(doc, _python_doc()).splitlines()[1] == (
        "  remedy: re-record the baseline with this version — run `partspec check` over "
        "the old side again and keep that report — so both sides carry an import map"
    )
    assert doc["source"]["imports"]["uncomparable"].startswith("no source_closure.imports map")


def test_a_gap_with_no_remedy_is_not_given_one():
    """An invented remedy is worse than none: it sends a reader to do work
    that cannot help, which is what naming the cause alone already did. A
    namespace package has no file to hash and no partspec option closes it."""
    imports = {"shims": _unidentified()}
    unseen = ["native_reads", "unidentified_imports"]
    doc = _diff(_python_doc(imports, unseen), _python_doc(imports, unseen))

    assert doc["outcome"] == "indeterminate"
    assert "remedy" not in doc["indeterminate"][0]
    assert "remedy:" not in summary_of(doc, _python_doc(imports, unseen))


def test_the_widened_packages_field_is_not_reported_as_installations():
    """`SPEC-diff.md` §3 and the #211 entry both say "nothing was installed;
    re-record the baseline to clear it" — and the tool said `packages
    appeared: PyJWT 2.13.0, PyYAML 6.0.3, +107 more`, on the first diff after
    an upgrade. It can tell: the old report's closure carries no `imports`,
    which is the same signal `_gap_tokens` reads to date a report.
    """
    old = _with_packages(_legacy(dict(LEGACY_SCAD_COMPLETE)), {"trimesh": "4.0.0"})
    new = _with_packages(_python_doc(), {"trimesh": "4.0.0", "PyJWT": "2.13.0", "PyYAML": "6.0.3"})

    doc = _diff(old, new)
    assert doc["outcome"] == "identical", "a widened record is not a finding about the part"
    assert exit_code_of(doc["outcome"]) == 0
    assert doc["environment"]["packages"]["added"] == {"PyJWT": "2.13.0", "PyYAML": "6.0.3"}, (
        "the group is unchanged — the artifact loses nothing"
    )
    assert doc["environment"]["packages"]["first_recorded"] == ["PyJWT", "PyYAML"]

    summary = summary_of(doc, new)
    assert "packages appeared" not in summary, f"a widened record read as an install: {summary}"
    assert (
        "2 packages recorded for the first time: PyJWT 2.13.0, PyYAML 6.0.3 — the baseline "
        "predates 0.7.5, when this field held five engine names; nothing was installed, and "
        "re-recording the baseline clears it"
    ) in summary


def test_a_package_the_old_field_did_record_still_appears():
    """The split is why the widening is nameable at all. The pre-0.7.5 field
    held five engine names, so those five it could record — `trimesh` absent
    from an old report means it genuinely was not installed, and calling that
    a first recording would misname a real install on the same line."""
    old = _with_packages(_legacy(dict(LEGACY_SCAD_COMPLETE)), {"cadquery": "2.8.0"})
    new = _with_packages(_python_doc(), {"cadquery": "2.8.0", "trimesh": "4.0.0", "idna": "3.11"})

    doc = _diff(old, new)
    assert doc["environment"]["packages"]["first_recorded"] == ["idna"]
    summary = summary_of(doc, new)
    assert "packages appeared: trimesh 4.0.0" in summary
    assert "1 packages recorded for the first time: idna 3.11" in summary


def test_a_0_7_5_baseline_reports_an_install_as_an_install():
    """The qualification is bounded by the baseline's age, not by the group.
    Two 0.7.5 reports get v0.7.5's wording, because there the appearance is
    exactly what it says."""
    old = _with_packages(_python_doc(), {"cadquery": "2.8.0"})
    new = _with_packages(_python_doc(), {"cadquery": "2.8.0", "idna": "3.11"})

    doc = _diff(old, new)
    assert doc["environment"]["packages"]["first_recorded"] == []
    assert "packages appeared: idna 3.11" in summary_of(doc, new)
    assert "recorded for the first time" not in summary_of(doc, new)


def test_an_openscad_model_reading_external_data_keeps_its_message():
    """#198's case, unchanged by stage 3 except that the gap now has a name:
    the design handles both tiers through one mechanism and narrows
    OpenSCAD's honesty by no case."""
    closure = {
        "digest": "sha256:k1",
        "files": 16,
        "reads_external_data": True,
        "partial": True,
        "imports": {},
        "unseen": ["external_data_reads"],
    }
    doc = _diff(_legacy(dict(closure)), _legacy(dict(closure)))
    assert doc["outcome"] == "indeterminate"
    assert doc["indeterminate"][0]["reason"] == (
        "no differences found, but the model reads external data (import()/surface()) and "
        "this run carries no complete engine-reported input set, so which files those were "
        "is unrecorded (a successful render on an engine that accepts -d records them), "
        f"so {SENTENCE}"
    )
    # No Python tier, so no irreducible caveat to print.
    assert "not covered" not in summary_of(doc, _legacy(dict(closure)))


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


def _loosened() -> tuple[dict, dict]:
    """The flagship weakening move: an unchanged 1.4 mm wall, its floor
    dropped from 2.0 to 0.001, and a check that now passes.

    The measurement is moved on *both* sides. Leaving `_doc`'s 2.9 under a
    stamped `fail` would model a report that contradicts itself, and moving it
    on one side only would put a `value` delta in the entry — the geometry
    changing is the one thing this fixture must not say happened.

    #293's own end-to-end reproduction was a live build of a different check
    (an `envelope` bound over `examples/spacer`'s `spacer.scad`); this is the
    same shape as a unit fixture, not a transcript of that run.
    """
    old, new = _doc(), _doc()
    old_check = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    old_check["status"] = "fail"
    old_check["measurement"]["value"] = 1.4
    old["verdict"] = "fail"
    new_check = next(c for c in new["checks"] if c["id"] == "wall_gt_2")
    new_check["measurement"]["value"] = 1.4
    new_check["limit"] = {"min": 0.001}
    return old, new


def test_a_status_flipped_by_a_moved_claim_says_so_on_the_headline_too():
    """#293. §3's reason for making the claim delta ride the entry is that
    "an entry saying only 'fixed' would report the attack as an improvement" —
    and the stderr headline, which is the surface a human reads in a terminal
    or a PR check, said exactly `1 fixed`. The artifact carried the delta the
    whole time; nothing printed it."""
    old, new = _loosened()
    doc = _diff(old, new)

    # The fixture says what it claims to say: the claim moved and the geometry
    # did not, so the note is answering for the bound and nothing else.
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["claim"]["old"] == {"limit": {"min": 2.0}}
    assert "value" not in entry

    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed)"
    )


def test_a_genuine_fix_is_not_slurred_as_a_moved_claim():
    """The note must fire on the weakening move and not on a repair. Same
    floor, thicker wall: the part got better and the headline must say so
    without a caveat, or the caveat means nothing where it matters."""
    old, new = _doc(), _doc()
    old_check = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    old_check["status"] = "fail"
    old_check["measurement"]["value"] = 1.4
    old["verdict"] = "fail"

    summary = summary_of(_diff(old, new), new)
    assert summary.splitlines()[0] == "different: p — 1 fixed"
    assert "claim changed" not in summary


def test_the_qualifier_counts_the_moved_claims_and_not_the_bucket():
    """One bucket, one weakening and one genuine repair. Every other test here
    puts a single entry in the qualified bucket, where the two numbers cannot
    be told apart — and a mutant printing the bucket total inside the
    parentheses passed all 1178 (review round 2).

    `2 fixed (2 with the claim changed)` accuses the repair of being the
    attack, which is the same defect as #293 pointed the other way.

    Three shapes, because one is not enough to pin a count (review round 4).
    A qualified entry first is what `1` and `any()` and `entries[:1]` all
    agree on; the number is only observable where it is neither 0 nor the
    bucket total, and the position only where the qualified entry is not the
    one a truncating read would find."""

    def _fixed(doc):
        return [(c["id"], "claim" in c) for c in doc["checks"] if c["change"] == "fixed"]

    # 1. The weakening first, a genuine repair behind it.
    old, new = _loosened()
    envelope = next(c for c in old["checks"] if c["id"] == "envelope")
    envelope["status"] = "fail"
    envelope["measurement"]["value"] = [31.0, 20.0, 10.0]

    doc = _diff(old, new)
    assert _fixed(doc) == [("wall_gt_2", True), ("envelope", False)]
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 2 fixed (1 with the claim changed)"
    )

    # 2. The same pair with the roles swapped, so the qualified entry is not
    #    the first one. `entries[:1]` reads this as an unqualified `2 fixed` —
    #    #293's own defect, restored, under a green suite.
    old, new = _doc(), _doc()
    wall_old = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    wall_old["status"] = "fail"
    wall_old["measurement"]["value"] = 1.4
    env_old = next(c for c in old["checks"] if c["id"] == "envelope")
    env_old["status"] = "fail"
    old["verdict"] = "fail"
    next(c for c in new["checks"] if c["id"] == "envelope")["limit"] = {"max": [40, 30, 10]}

    doc = _diff(old, new)
    assert _fixed(doc) == [("wall_gt_2", False), ("envelope", True)]
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 2 fixed (1 with the claim changed)"
    )

    # 3. Both claims moved. `any()` and a `min(n, 1)` clamp both under-report
    #    here, filing one of two weakenings as a repair.
    wall_new = next(c for c in new["checks"] if c["id"] == "wall_gt_2")
    wall_new["measurement"]["value"] = 1.4
    wall_new["limit"] = {"min": 0.001}

    doc = _diff(old, new)
    assert _fixed(doc) == [("wall_gt_2", True), ("envelope", True)]
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 2 fixed (2 with the claim changed)"
    )

    # 4. Each count reads its own bucket. Every block above puts every entry
    #    in one bucket, so nothing observed the domain — a mutant counting the
    #    claim-moved entries across all the status buckets, or across the
    #    whole diff, passed all 1179 (review round 5). §3 makes the scope
    #    normative twice ("how many of *its* entries", "*within* a status
    #    bucket") and neither sentence was executed.
    #
    #    A tightened bound that breaks a check, a genuine repair beside it,
    #    and a claim moved under a status that held. The qualifier belongs to
    #    the first and to nothing else.
    old, new = _doc(), _doc()
    repaired = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    repaired["status"] = "fail"
    repaired["measurement"]["value"] = 1.4
    old["verdict"] = "fail"
    broken = next(c for c in new["checks"] if c["id"] == "envelope")
    broken["status"] = "fail"
    broken["limit"] = {"max": [29, 20, 10]}
    next(c for c in new["checks"] if c["id"] == "fits")["expr"] = "a + b <= 2 * c"

    doc = _diff(old, new)
    assert [(c["id"], c["change"], "claim" in c) for c in doc["checks"]] == [
        ("wall_gt_2", "fixed", False),
        ("fits", "limit_changed", True),
        ("envelope", "regressed", True),
    ]
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 1 regressed (1 with the claim changed); 1 fixed; 1 limit_changed"
    )

    # 5. The whole claim, not the bound. Every block above moves `limit`, so a
    #    mutant counting only entries whose `limit` moved passed the suite —
    #    and §3 calls a stripped citation "the quiet half of the weakening
    #    move": same number, authority now the author's say-so. A status that
    #    flips under it must qualify exactly as a loosened bound does.
    old, new = _doc(), _doc()
    cited = next(c for c in old["checks"] if c["id"] == "wall_gt_2")
    cited["status"] = "fail"
    cited["source"] = {"standard": "iso15", "subject": "608", "field": "bore"}
    old["verdict"] = "fail"

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert entry["change"] == "fixed"
    assert list(entry["claim"]["new"]) == ["source"]
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed)"
    )

    # 6. The bound moved and so did the part. Every qualified entry above
    #    carries a claim and no value, so the one shape a reader is most
    #    likely to meet — an author who loosened a bound while the geometry
    #    was also changing — was nowhere in the suite. The qualifier reads
    #    the claim whether or not a value rode along with it.
    cited["measurement"]["value"] = 1.4

    doc = _diff(old, new)
    entry = next(c for c in doc["checks"] if c["id"] == "wall_gt_2")
    assert "claim" in entry and "value" in entry
    assert summary_of(doc, new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed)"
    )


def test_the_note_rides_beside_the_moved_inputs_clause_rather_than_over_it():
    """Both clauses land on one line and the first draft of this fix bound its
    count to the name the imports/packages clause already held, printing
    `...changed)1` — the headline reporting its own arithmetic. Two facts, one
    line, neither swallowing the other."""
    old, new = _loosened()
    old["environment"]["packages"] = {"trimesh": "5.0.0"}
    new["environment"]["packages"] = {"trimesh": "5.1.0"}

    assert summary_of(_diff(old, new), new).splitlines()[0] == (
        "different: p — 1 fixed (1 with the claim changed); packages moved: trimesh 5.0.0 → 5.1.0"
    )


def test_a_tightened_claim_that_breaks_a_check_is_distinguished_from_a_worse_part():
    """The mirror case, and the same ambiguity: `1 regressed` alone cannot
    tell a part that got worse from a contract that got stricter. One is a
    defect and the other is the author doing their job.

    Mixed as well as alone. Review round 3: a mutant confined to the
    `regressed` bucket survived all 1179, because no test anywhere put more
    than one entry in it — the same shape as round 2's finding, on the half of
    the rule the round-2 fix did not reach."""
    old, new = _doc(), _doc()
    tightened = next(c for c in new["checks"] if c["id"] == "wall_gt_2")
    tightened["limit"] = {"min": 3.5}
    tightened["status"] = "fail"
    new["verdict"] = "fail"

    assert summary_of(_diff(old, new), new).splitlines()[0] == (
        "different: p — 1 regressed (1 with the claim changed)"
    )

    # And a second regression beside it whose claim held: the part got worse.
    worse = next(c for c in new["checks"] if c["id"] == "envelope")
    worse["status"] = "fail"
    worse["measurement"]["value"] = [31.0, 20.0, 10.0]

    assert summary_of(_diff(old, new), new).splitlines()[0] == (
        "different: p — 2 regressed (1 with the claim changed)"
    )


def test_the_note_is_not_repeated_where_it_would_be_tautological():
    """`limit_changed` IS the claim moving, so the qualifier would restate the
    bucket's own name; a `drifted` entry cannot carry a claim at all, because
    `_check_entry` returns `limit_changed` before reaching that branch."""
    old, new = _doc(), _doc()
    next(c for c in new["checks"] if c["id"] == "wall_gt_2")["limit"] = {"min": 0.001}
    next(c for c in new["checks"] if c["id"] == "envelope")["measurement"]["value"] = [
        29.0,
        20.0,
        10.0,
    ]

    doc = _diff(old, new)
    assert {c["change"] for c in doc["checks"]} == {"limit_changed", "drifted"}
    assert summary_of(doc, new).splitlines()[0] == "different: p — 1 drifted; 1 limit_changed"


def test_a_verdict_only_tamper_is_a_difference():
    """Identical checks, tampered verdict: still different (review M1 — this
    clause was untested and a mutant deleting it survived)."""
    old = _doc()
    new = _doc(verdict="fail")
    doc = _diff(old, new)
    assert doc["outcome"] == "different"
    assert doc["checks"] == []
    assert "verdict changed" in summary_of(doc, new)


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
    # `== "identical"`, not `in {...}`: an assertion that passes whichever way
    # the code goes answers nothing, which is the shape a93df3a went through the
    # whole suite to remove. The fixture carries a complete `source_closure`, so
    # the partial-closure rule does not fire and the answer is determinate.
    assert _diff(empty, empty)["outcome"] == "identical"

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


# --------------------------------------------------------------------------
# tests that live here because their subject is the DIFF
#
# Both were written beside the slice whose fixture they borrowed (#153): the
# citation one in `test_provenance.py`, the pull-axis one in `test_draft.py`.
# Each asserts a property of the comparator — that stripping authority is
# visible, that a rotated axis is a claim change — so this is where a reader
# looking for "what does diff notice?" will look for them.
# --------------------------------------------------------------------------

_A_CITATION = {"standard": "TEST", "subject": "x", "field": "f"}


def test_stripping_a_citation_is_diff_visible():
    """The quiet half of the weakening move: same number, authority gone.
    'No semantic differences' over it would be exactly the silence the diff
    verb exists to refuse (#92's design constraint, missed on first cut)."""
    from partspec.diff import diff_reports
    from partspec.report import CheckResult, Report
    from partspec.status import Limit, Status

    def doc(source):
        r = Report(part_id="p", contract="c", tool_version="t", contract_digest="sha256:x")
        r.checks = [
            CheckResult(
                id="envelope",
                kind="envelope",
                phase="geometry",
                status=Status.PASS,
                limit=Limit(max=(50.0, 50.0, 7.0)),
                source=source,
            )
        ]
        return r.to_json()

    diff = diff_reports(doc({"max.2": _A_CITATION}), doc(None), tool_version="t")
    assert diff["outcome"] == "different"
    entry = diff["checks"][0]
    assert entry["change"] == "limit_changed"
    assert entry["claim"]["old"]["source"] == {"max.2": _A_CITATION}
    assert entry["claim"]["new"]["source"] is None


@needs_build123d
def test_the_diff_verb_sees_a_rotated_pull_axis(tmp_path):
    """PR #141 review, F2: rotating the pull axis is a claim change the
    semantic diff must name — a draft claim without its axis is not
    reproducible, so the axis is part of the claim's identity."""
    from partspec.cli import main

    model = "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    (tmp_path / "m.py").write_text(model)
    for name, direction in (("a", "(0, 0, 1)"), ("b", "(1, 0, 0)")):
        (tmp_path / f"spec_{name}.py").write_text(
            "from partspec import Part, build123d\n\n\ndef make():\n"
            "    p = Part('subject', build123d('m.py'))\n"
            f"    p.draft_angle(min=1.0, direction={direction})\n"
            "    return p\n"
        )
        main(
            [
                "check",
                f"{tmp_path / f'spec_{name}.py'}:make",
                "--quiet",
                "--out",
                str(tmp_path / name),
            ]
        )
    code = main(["diff", str(tmp_path / "a" / "report.json"), str(tmp_path / "b" / "report.json")])
    assert code == 1, "a rotated pull axis is a difference, not silence"


def test_a_status_that_is_not_a_status_is_corrupt_input():
    """The summary reads `status` into a SET, so a non-string one crashed.

    `_check_entry` only asks `!=`, so a non-string status equal on BOTH sides
    sailed past every comparison and then raised `TypeError: cannot use 'list'
    as a set element` out of `summary_of` — after the complete diff artifact
    had already been written to stdout. Exit 4 with a traceback, where
    `SPEC-diff.md` §2 promises 64 for a malformed report and where `main`
    answered 0 (round-3 review of #239).

    Introduced by removing an `isinstance` filter that the removing commit's
    own comment called dead: the upstream guard it cited refuses a non-object
    ENTRY, and says nothing about the field the next line reads.
    """
    from partspec.diff import DiffUsageError

    bad = _doc()
    bad["checks"][0]["status"] = ["pass"]
    with pytest.raises(DiffUsageError, match="`status` is not a string"):
        _diff(bad, _doc())
    with pytest.raises(DiffUsageError, match="`status` is not a string"):
        _diff(_doc(), bad)


def test_an_import_the_target_provably_reached_is_attributable_after_all():
    """`preloaded` names an inability, and #216 is the half of it that can be
    settled: a distribution the target's OWN module graph reaches is its build
    input whoever imported it first.

    Without this the under-report is real, not theoretical. A follower whose
    model begins importing a library the leader also loads produces exactly
    this shape — the entry is on one side only AND preloaded — and it is a
    genuine new build input reported as a non-event.
    """
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")})
    new = _python_doc(
        {"build123d": _dist("0.10.1", "aaa"), "cqgridfinity": _dist("0.5.7", "bbb")},
        preloaded=["build123d", "cqgridfinity"],
        reached=["build123d", "cqgridfinity"],
    )

    doc = _diff(old, new)
    assert doc["source"]["imports"]["added"] == {"cqgridfinity": _dist("0.5.7", "bbb")}
    assert doc["source"]["imports"]["unattributable"] == [], (
        "the model's own graph reaches it, so the inability preloaded records does not apply"
    )
    assert "appeared" in summary_of(doc, new), "a real new build input must read as a finding"


def test_reach_may_attribute_an_import_but_never_dismiss_one():
    """One-directional, and the direction is the whole safety argument.

    `reached` proves reach and cannot disprove it — `from mylib import
    WALL_THICKNESS` binds a float, a float has no `__module__`, and the edge
    does not exist in the object graph at all. So an entry absent from
    `reached` is *not proven reached*, never *proven unreached*, and must be
    governed exactly as it was before the field existed.
    """
    imports_new = {"build123d": _dist("0.10.1", "aaa"), "cadquery": _dist("2.8.0", "bbb")}
    old = _python_doc({"build123d": _dist("0.10.1", "aaa")})

    # Present and empty, and absent entirely: both mean "nothing proven", and
    # both must leave the qualification exactly where it was.
    for reached in ([], None):
        new = _python_doc(imports_new, preloaded=["build123d", "cadquery"], reached=reached)
        doc = _diff(old, new)
        assert doc["source"]["imports"]["unattributable"] == ["cadquery"], (
            f"reached={reached!r} must not dismiss the qualification"
        )
        assert "appeared" not in summary_of(doc, new)
