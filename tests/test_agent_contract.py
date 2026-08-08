"""AGENT-CONTRACT.md makes executable claims; this holds them to the code.

The document tells an agent what each exit code means, quotes the tool's own
message fragments, and names flags and fields. A contract document that
drifts from the tool teaches the agent wrong behaviour with full confidence —
the same defect class as a spec drifting from its own example, guarded the
same way.
"""

from __future__ import annotations

import re
from pathlib import Path

from partspec.status import EXIT_USAGE, Verdict, exit_code

DOC = (Path(__file__).resolve().parents[1] / "docs" / "AGENT-CONTRACT.md").read_text()
DOC_FLAT = re.sub(r"\s+", " ", DOC)
"""Prose wraps at the margin; claims are checked against flattened text."""
SRC = Path(__file__).resolve().parents[1] / "src" / "partspec"


def test_the_exit_table_matches_the_status_module():
    rows = {
        code: word.strip().strip("`") for code, word in re.findall(r"\| `(\d+)` \| ([^|]+) \|", DOC)
    }
    for verdict in Verdict:
        assert rows.get(str(exit_code(verdict))) == str(verdict), (
            f"the doc's row for exit {exit_code(verdict)} disagrees with {verdict!r}"
        )
    assert rows.get(str(EXIT_USAGE)) == "—", "the usage exit is part of the action map"
    assert rows.get("130") == "—", "the interrupt exit is part of the action map"


def test_quoted_tool_fragments_exist_in_the_code():
    """Every message fragment the doc teaches an agent to look for must be a
    string the tool actually emits."""
    fragments = {
        "run did not complete": SRC / "report.py",
        "the contract is wrong, not the part": SRC / "runner.py",
        "not evaluated:": SRC / "runner.py",
    }
    for fragment, path in fragments.items():
        assert fragment in DOC_FLAT, f"doc no longer teaches {fragment!r}"
        assert fragment in path.read_text(), f"{path.name} no longer emits {fragment!r}"


def test_named_flags_and_fields_exist():
    cli = (SRC / "cli.py").read_text()
    for flag in ("--expect", "--pin", "--timeout", "--quiet"):
        assert flag in DOC and flag in cli
    report = (SRC / "report.py").read_text()
    for field in ("expectation", "attribution", "build_origin", "source_closure"):
        assert field in DOC and field in report


def test_the_escalation_format_is_stated_exactly_and_greppable():
    """Acceptance (#28): the format is specified exactly. The doc must carry
    the literal template AND a conforming example the template's own regex
    accepts — a format whose example doesn't match teaches two formats."""
    assert (
        "HUMAN_REVIEW: <why in one clause> — last failure: <check id>: <detail or error text>"
        in DOC
    )
    pattern = re.compile(r"^HUMAN_REVIEW: .+ — last failure: .+: .+$", re.M)
    examples = [
        m
        for m in pattern.findall(DOC)
        if "<why" not in m  # skip the template itself
    ]
    assert examples, "the doc must show at least one conforming escalation example"


def test_the_attempt_bound_is_stated_exactly():
    assert "At most 5 attempts per part" in DOC


def test_weakening_is_forbidden_and_the_guard_is_named():
    """Acceptance (#28): forbids weakening and names the guard detecting it."""
    assert "Never weaken the contract" in DOC
    assert "claims pin" in DOC and "--expect" in DOC
    assert "diff" in DOC and "attribution" in DOC


def test_incomplete_and_fail_prescribe_different_actions():
    """Acceptance (#28): exit 1 says edit the model; exit 2 says don't —
    anchored to their own table rows, so swapping the two actions between
    rows fails rather than passing on mere presence (PR #106 review, F9a)."""
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(\d+)` \|.*$", DOC, re.M)}
    assert "edit the **model**" in rows["1"]
    assert "Do not edit geometry" in rows["2"]


def test_the_requires_tier_token_matches_the_runner():
    """The doc teaches `requires: \"occt\"` as the routing token; hold it to
    the string the runner actually emits (PR #106 review, F9b)."""
    assert "`requires` names the tier" in DOC
    assert '"occt"' in DOC
    assert 'requires="occt"' in (SRC / "runner.py").read_text()
