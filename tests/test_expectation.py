"""The claims pin (#31): contract weakening caught with no baseline in hand.

"Make the check pass" and "delete the check" are the same action from where a
model sits. `diff` sees the second on comparison; the pin sees it in a single
run — the fresh CI checkout, or the loop whose first run is already
post-tamper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import needs_openscad, report_of

from partspec.cli import main
from partspec.expectation import LockError, compare, read_lock

# --------------------------------------------------------------------------
# the comparison, engine-free
# --------------------------------------------------------------------------


def test_matching_sets_have_no_differences():
    claims = {"a": "envelope max=[40, 40, 15]", "b": "watertight"}
    assert compare(claims, dict(claims)) == []


def test_every_direction_is_named():
    pinned = {"gone": "volume min=5", "kept": "watertight", "moved": "envelope max=[40]"}
    declared = {"kept": "watertight", "moved": "envelope max=[99]", "new": "area min=1"}
    diffs = compare(pinned, declared)
    assert any(d.startswith("removed: gone") for d in diffs)
    assert any(d.startswith("added: new") for d in diffs)
    assert any("changed: moved" in d and "max=[40]" in d and "max=[99]" in d for d in diffs)


def test_a_swap_under_the_same_count_is_caught():
    """The acceptance criterion that rules out pinning a bare count."""
    pinned = {"wall": "volume min=100"}
    declared = {"wall": "volume min=1"}
    assert compare(pinned, declared), "same id, same count, weaker claim — must not slip"


def test_the_shell_thickness_is_part_of_the_claim():
    """A keep_out with a thinner verification shell is a weaker claim; the
    slug must see it (PR #105 review, mutation survivor F3)."""
    from partspec import Part, openscad
    from partspec.expectation import claims_of
    from partspec.region import box

    def bracket(shell: float) -> dict[str, str]:
        p = Part("b", openscad("m.scad"))
        p.keep_out(box(min=(0, 0, 0), max=(5, 5, 5)), shell=shell, id="clearance")
        return claims_of(p)

    assert compare(bracket(5.0), bracket(1.0)), "a thinned shell must not slip the pin"
    assert compare(bracket(5.0), bracket(5.0)) == []


def test_a_missing_or_corrupt_lock_is_a_named_refusal(tmp_path: Path):
    with pytest.raises(LockError, match="--pin"):
        read_lock(tmp_path / "absent.lock")
    bad = tmp_path / "bad.lock"
    bad.write_text("{not json")
    with pytest.raises(LockError):
        read_lock(bad)
    wrong = tmp_path / "wrong.lock"
    wrong.write_text('{"schema_version": 99, "parts": {}}')
    with pytest.raises(LockError, match="schema_version"):
        read_lock(wrong)


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------


def _target(tmp_path: Path, body: str) -> str:
    (tmp_path / "m.scad").write_text("cube([30, 20, 10]);\n")
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('m.scad'))\n"
        f"{body}"
        "    return p\n"
    )
    return f"{spec}:make"


STRICT = "    p.envelope(max=(31, 21, 11))\n    p.watertight()\n"


@needs_openscad
def test_pin_then_expect_round_trips_green(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    lock = tmp_path / "claims.lock"
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--pin", str(lock), "--out", str(out)]) == 0
    assert json.loads(lock.read_text())["schema_version"] == 1

    assert main(["check", target, "--quiet", "--expect", str(lock), "--out", str(out)]) == 0
    report = report_of(out)
    assert report["expectation"] == {"claims": 2, "matched": True}
    assert list(report)[7:10] == ["counts", "attribution", "expectation"]


@needs_openscad
def test_a_deleted_check_fails_with_its_name(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    lock = tmp_path / "claims.lock"
    assert main(["check", target, "--quiet", "--pin", str(lock)]) == 0

    weakened = _target(tmp_path, "    p.watertight()\n")  # envelope deleted
    out = tmp_path / "out"
    code = main(["check", weakened, "--quiet", "--expect", str(lock), "--out", str(out)])
    assert code == 4, "a contract that shrank is error, never a verdict about the part"

    report = report_of(out)
    assert report["verdict"] == "error"
    assert "removed: envelope" in report["error"]
    assert report["expectation"]["matched"] is False
    assert any("removed: envelope" in d for d in report["expectation"]["differences"])
    assert all(c["status"] == "skipped" for c in report["checks"])
    assert "--pin" in report["hint"], "the deliberate-update path is named"


@needs_openscad
def test_a_loosened_limit_fails_showing_both_slugs(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    lock = tmp_path / "claims.lock"
    assert main(["check", target, "--quiet", "--pin", str(lock)]) == 0

    loosened = _target(tmp_path, "    p.envelope(max=(500, 500, 500))\n    p.watertight()\n")
    out = tmp_path / "out"
    assert main(["check", loosened, "--quiet", "--expect", str(lock), "--out", str(out)]) == 4
    report = report_of(out)
    assert "changed: envelope" in report["error"]
    assert "31" in report["error"] and "500" in report["error"], "both slugs shown"


@needs_openscad
def test_an_added_check_is_a_difference_too(tmp_path: Path):
    """A pin is an exact statement: an addition nobody re-pinned is still a
    contract that is not the one reviewed."""
    target = _target(tmp_path, "    p.watertight()\n")
    lock = tmp_path / "claims.lock"
    assert main(["check", target, "--quiet", "--pin", str(lock)]) == 0

    grown = _target(tmp_path, STRICT)
    assert main(["check", grown, "--quiet", "--expect", str(lock)]) == 4


@needs_openscad
def test_an_unpinned_part_does_not_pass_on_someone_elses_pin(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    lock = tmp_path / "claims.lock"
    lock.write_text('{"schema_version": 1, "parts": {"other": {"x": "watertight"}}}')
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--expect", str(lock), "--out", str(out)]) == 4
    report = report_of(out)
    assert report["expectation"]["claims"] == 0
    assert all(d.startswith("added:") for d in report["expectation"]["differences"])


@needs_openscad
def test_a_deliberate_change_repins_in_one_flag(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    lock = tmp_path / "claims.lock"
    assert main(["check", target, "--quiet", "--pin", str(lock)]) == 0

    # Deliberately the SAME byte length as STRICT, in the same second: this
    # is the rapid agent-edit shape that used to re-execute the old
    # contract's stale .pyc under the new contract_digest — the loaders now
    # compile entry files from source, and this test holds them to it.
    changed = _target(tmp_path, "    p.envelope(max=(32, 22, 12))\n    p.watertight()\n")
    assert main(["check", changed, "--quiet", "--expect", str(lock)]) == 4
    assert main(["check", changed, "--quiet", "--pin", str(lock)]) == 0
    assert main(["check", changed, "--quiet", "--expect", str(lock)]) == 0


def test_expect_without_a_lock_is_usage(tmp_path: Path, capsys):
    code = main(["check", "spec.py:make", "--quiet", "--expect", str(tmp_path / "none.lock")])
    assert code == 64
    assert "--pin" in capsys.readouterr().err


def test_pin_and_expect_together_are_refused(tmp_path: Path):
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "spec.py:make", "--pin", "a.lock", "--expect", "b.lock"])
    assert excinfo.value.code == 64


@needs_openscad
def test_a_pinned_part_dropped_from_the_invocation_is_not_green(tmp_path: Path, capsys):
    """PR #105's review, F1 — the one defeat inside the pin's own charter:
    'delete the check' at part granularity. Pin two parts, invoke --expect
    with only one target: the uncovered pin entry must fail the run."""
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    targets = []
    for d, name in ((a_dir, "part_a"), (b_dir, "part_b")):
        (d / "m.scad").write_text("cube([30, 20, 10]);\n")
        spec = d / f"{name}.py"
        spec.write_text(
            "from partspec import Part, openscad\n\n\ndef make():\n"
            f"    p = Part({name!r}, openscad('m.scad'))\n"
            "    p.watertight()\n"
            "    return p\n"
        )
        targets.append(f"{spec}:make")
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0

    code = main(["check", targets[0], "--quiet", "--expect", str(lock)])
    assert code == 4, "a deleted part is a deleted claim set"
    err = capsys.readouterr().err
    assert "part_b" in err and "no target" in err

    # Both targets present again: covered, green.
    assert main(["check", *targets, "--quiet", "--expect", str(lock)]) == 0


@needs_openscad
def test_a_report_without_expect_carries_no_expectation_key(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    assert "expectation" not in report_of(out)


@needs_openscad
def test_a_stripped_citation_is_a_named_difference(tmp_path: Path):
    """Laundering an attributed bound into an authorless one must not slip
    the pin — `source` participates in the slug the way it does in diff."""
    cited = _target(
        tmp_path,
        "    from partspec.refs import iso15\n"
        "    p.envelope(max=(iso15.bearing(608).od, 30.0, 30.0))\n",
    )
    lock = tmp_path / "claims.lock"
    assert main(["check", cited, "--quiet", "--pin", str(lock)]) in (0, 1)

    bare = _target(tmp_path, "    p.envelope(max=(22.0, 30.0, 30.0))\n")
    out = tmp_path / "out"
    assert main(["check", bare, "--quiet", "--expect", str(lock), "--out", str(out)]) == 4
    report = report_of(out)
    assert "ISO 15" in report["error"], "the vanished citation is visible in the difference"
