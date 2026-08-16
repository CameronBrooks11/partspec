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
from support import needs_openscad, needs_scad_tier, report_of

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


@needs_scad_tier
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


@needs_scad_tier
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


@needs_scad_tier
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


@needs_scad_tier
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


@needs_scad_tier
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


@needs_scad_tier
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


@needs_scad_tier
def test_a_pinned_target_that_crashed_is_not_reported_as_a_deletion(tmp_path: Path, capsys):
    """#201: the guard's own advice performed the drop it exists to prevent.

    A pinned target SUPPLIED on the command line but failing to resolve never
    reaches `covered_ids.add(part.id)` — `_resolve_or_report` returns an int
    and bails first — so the coverage comparison reported it as dropped and
    advised `re-pin with --pin`. Following that writes a lock without the
    part, **permanently deleting its claim set**, turning a typo or a
    half-saved file into a silently deleted check. That is the failure class
    PR #105's review added this guard for, performed by the guard.

    The run still fails (exit 4) and the pin is still reported as uncovered:
    a target that crashed proved nothing, and green would be worse. What
    changes is that the message declines to call it a deletion and refuses to
    advise the destructive remedy.

    Which pinned part the failed target WOULD have produced is not knowable —
    the id comes from running the contract — so the message names the failure
    and stops, rather than guessing an attribution.
    """
    (tmp_path / "m.scad").write_text("cube([30, 20, 10]);\n")
    spec = tmp_path / "s.py"
    body = (
        "from partspec import Part, openscad\n\n\n"
        "def good():\n"
        "{crash}"
        "    return Part('good-part', openscad('m.scad')).watertight()\n\n\n"
        "def other():\n"
        "    return Part('other-part', openscad('m.scad')).watertight()\n"
    )
    spec.write_text(body.format(crash=""))
    targets = [f"{spec}:good", f"{spec}:other"]
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0

    spec.write_text(body.format(crash="    raise RuntimeError('boom')\n"))
    code = main(["check", *targets, "--quiet", "--expect", str(lock)])
    err = capsys.readouterr().err

    assert code == 4, "a target that crashed proved nothing; green would be worse"
    assert "'good-part'" in err, "the uncovered pin is still named"
    assert f"{spec}:good" in err, "and so is the target that did not resolve"
    assert "may be that failure rather than a deletion" in err
    assert "partspec refuses that while a target is unresolved" in err
    assert "deleted part is a deleted claim set" not in err, (
        "it was not deleted, it crashed, and the line above says so"
    )
    assert "re-pin with --pin if the removal is deliberate" not in err, (
        "the remedy that destroys the claim set must not be offered here"
    )


@needs_scad_tier
def test_a_real_deletion_still_gets_the_deletion_message(tmp_path: Path, capsys):
    """The other side of #201's split, so the fix cannot be "stop saying it".

    Nothing failed to resolve here: the target is simply absent, which IS a
    deletion, and the advice to re-pin is correct because the removal really
    might be deliberate.
    """
    (tmp_path / "m.scad").write_text("cube([30, 20, 10]);\n")
    spec = tmp_path / "s.py"
    spec.write_text(
        "from partspec import Part, openscad\n\n\n"
        "def good():\n"
        "    return Part('good-part', openscad('m.scad')).watertight()\n\n\n"
        "def other():\n"
        "    return Part('other-part', openscad('m.scad')).watertight()\n"
    )
    lock = tmp_path / "claims.lock"
    assert main(["check", f"{spec}:good", f"{spec}:other", "--quiet", "--pin", str(lock)]) == 0

    code = main(["check", f"{spec}:other", "--quiet", "--expect", str(lock)])
    err = capsys.readouterr().err

    assert code == 4
    assert "a deleted part is a deleted claim set" in err
    assert "re-pin with --pin if the removal is deliberate" in err
    assert "did not resolve" not in err, "nothing failed to resolve here"


@needs_scad_tier
def test_a_report_without_expect_carries_no_expectation_key(tmp_path: Path):
    target = _target(tmp_path, STRICT)
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 0
    assert "expectation" not in report_of(out)


@needs_scad_tier
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


def _crashable(tmp_path: Path) -> list[str]:
    """A three-part contract whose first factory crashes on demand."""
    (tmp_path / "m.scad").write_text("cube([30, 20, 10]);\n")
    spec = tmp_path / "s.py"
    spec.write_text(
        "import os\n\nfrom partspec import Part, openscad\n\n\n"
        "def a():\n"
        "    if os.environ.get('CRASH_A'):\n"
        "        raise RuntimeError('boom-a')\n"
        "    return Part('a-part', openscad('m.scad')).watertight()\n\n\n"
        "def b():\n    return Part('b-part', openscad('m.scad')).watertight()\n\n\n"
        "def c():\n    return Part('c-part', openscad('m.scad')).watertight()\n"
    )
    return [f"{spec}:a", f"{spec}:b", f"{spec}:c"]


@needs_scad_tier
def test_a_deletion_the_crash_cannot_explain_is_still_reported_as_one(
    tmp_path: Path, capsys, monkeypatch
):
    """The mirror of #201, which the first fix installed.

    A target resolves to at most one part, so N failures account for at most N
    uncovered ids — everything beyond that is PROVABLY deleted, whatever
    crashed. Blanket-declining there is a guard refusing a conclusion it has
    earned, and it withholds the correct remedy for parts the failure cannot
    explain (adversarial review of #243).
    """
    targets = _crashable(tmp_path)
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0

    # `a` crashes and `c` is genuinely dropped: two uncovered, one failure.
    monkeypatch.setenv("CRASH_A", "1")
    code = main(["check", targets[0], targets[1], "--quiet", "--expect", str(lock)])
    err = capsys.readouterr().err

    assert code == 4
    assert "can account for at most 1 of them, so at least 1 was deleted" in err, err
    assert "may be that failure rather than a deletion" not in err, (
        "one crash cannot explain two missing parts"
    )


@needs_scad_tier
def test_re_pinning_refuses_to_shrink_a_lock_because_a_target_crashed(
    tmp_path: Path, capsys, monkeypatch
):
    """#201's actual harm, which removing the ADVICE did not touch.

    `--pin` overwrites, so a crashed target dropped a part from an existing
    lock with only `pinned 2 part(s)` on stdout — the silent weakening
    `expectation.py` says the tool's job is to make impossible to do silently.
    The first fix deleted the sentence recommending it and left the act one
    flag away (adversarial review of #243).

    Refused rather than warned: by the time a warning is read the claim set is
    already gone.
    """
    targets = _crashable(tmp_path)
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0
    before = lock.read_bytes()

    monkeypatch.setenv("CRASH_A", "1")
    code = main(["check", *targets, "--quiet", "--pin", str(lock)])
    err = capsys.readouterr().err

    assert code == 4
    assert "refusing to re-pin" in err and "'a-part'" in err, err
    assert lock.read_bytes() == before, "the lock must be untouched, not merely complained about"


@needs_scad_tier
def test_the_crash_hint_names_the_parts_it_is_protecting(tmp_path: Path, capsys, monkeypatch):
    """`REFUSED_OUT_HINT`'s docstring, forty lines from the code this touches:
    pinning one spelling of advice pins the spelling, not the advice.

    The first fix asserted only the substring `Do NOT re-pin`, so the hint
    could name the wrong parts, drop the failed target, or invert its plurals
    with the suite green — four such mutants survived (adversarial review of
    #243). The content is asserted now.
    """
    targets = _crashable(tmp_path)
    lock = tmp_path / "claims.lock"
    assert main(["check", targets[0], "--quiet", "--pin", str(lock)]) == 0

    monkeypatch.setenv("CRASH_A", "1")
    assert main(["check", targets[0], "--quiet", "--expect", str(lock)]) == 4
    hint = next(line for line in capsys.readouterr().err.splitlines() if line.startswith("  hint:"))

    assert "'a-part'" in hint, "the parts at risk are named"
    assert "partspec refuses that" in hint, (
        "the hint must describe the guard that exists, not threaten a write that "
        "the same commit made impossible"
    )
    assert "that claim set" in hint, "one part, singular"
    assert "those claim sets" not in hint


@needs_scad_tier
def test_a_lock_partspec_cannot_read_is_not_treated_as_empty(tmp_path: Path, capsys, monkeypatch):
    """The guard must not fail OPEN on the locks it can least verify.

    Inside `is_file()` a `LockError` means unreadable, malformed, or a schema
    this build does not know — never "no lock yet". The first version turned it
    into `{}`, which says "nothing can be lost", and then overwrote the file:
    measured, a two-part lock was rewritten as a one-part one because a target
    crashed, with `pinned 1 part(s)` as the only output (round-3 review of
    #243).
    """
    targets = _crashable(tmp_path)
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0
    lock.write_text('{"schema_version": 99, "parts": {"a-part": {}, "b-part": {}}}\n')
    before = lock.read_bytes()

    monkeypatch.setenv("CRASH_A", "1")
    code = main(["check", *targets, "--quiet", "--pin", str(lock)])
    err = capsys.readouterr().err

    assert code == 4
    assert "refusing to re-pin" in err and "cannot tell" in err, err
    assert lock.read_bytes() == before, "an unreadable lock must not be overwritten"


@needs_scad_tier
def test_a_deliberate_shrink_with_nothing_unresolved_still_writes(tmp_path: Path, capsys):
    """The paired test the destructive guard was missing.

    Turning `--pin` into "never shrink a lock" would break every deliberate
    retirement, and dropping the `unresolved` conjunct passed the whole suite
    (round-3 review of #243). Nothing crashes here, so the shrink is the
    author's decision and must go through.
    """
    targets = _crashable(tmp_path)
    lock = tmp_path / "claims.lock"
    assert main(["check", *targets, "--quiet", "--pin", str(lock)]) == 0
    capsys.readouterr()

    assert main(["check", targets[1], "--quiet", "--pin", str(lock)]) == 0
    assert "refusing" not in capsys.readouterr().err
    from partspec.expectation import read_lock

    assert sorted(read_lock(lock)) == ["b-part"], "the deliberate retirement went through"


@needs_scad_tier
def test_the_count_does_not_dedupe_the_targets_it_counts(tmp_path: Path, capsys, monkeypatch):
    """`certain = len(uncovered) - len(unresolved)`, not `len(set(...))`.

    The bound is "one target accounts for at most one part", so deduping the
    target STRINGS breaks it: the same spec twice is two targets and two
    possible parts. Deduping made a run claim a deletion that had not happened
    (round-3 review of #243).

    The counter lives in a FILE, not a module global: `invalidate_model_modules`
    evicts the contract between targets, so module state resets and the same
    spec twice would otherwise produce one id — which is why this needed a
    second look to reproduce at all.
    """
    (tmp_path / "m.scad").write_text("cube([30, 20, 10]);\n")
    counter = tmp_path / "n"
    spec = tmp_path / "v.py"
    spec.write_text(
        "import os\nfrom pathlib import Path\n\nfrom partspec import Part, openscad\n\n\n"
        "def v():\n"
        "    if os.environ.get('CRASH_V'):\n"
        "        raise RuntimeError('boom')\n"
        f"    c = Path({str(counter)!r})\n"
        "    n = int(c.read_text()) if c.is_file() else 0\n"
        "    c.write_text(str(n + 1))\n"
        "    return Part(f'v-part-{n}', openscad('m.scad')).watertight()\n"
    )
    lock = tmp_path / "claims.lock"
    assert main(["check", f"{spec}:v", f"{spec}:v", "--quiet", "--pin", str(lock)]) == 0
    from partspec.expectation import read_lock

    assert sorted(read_lock(lock)) == ["v-part-0", "v-part-1"], "premise: two ids, one spec"

    monkeypatch.setenv("CRASH_V", "1")
    assert main(["check", f"{spec}:v", f"{spec}:v", "--quiet", "--expect", str(lock)]) == 4
    err = capsys.readouterr().err

    assert "was deleted" not in err and "were deleted" not in err, err
    assert "rather than a deletion" in err, (
        "two crashed targets can account for two uncovered ids; nothing is provable"
    )
