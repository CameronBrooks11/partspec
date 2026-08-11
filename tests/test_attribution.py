"""Per-component attribution (#84): which axis failed, and on what evidence.

Collected here because #158 left the subject split across two files — four
end-to-end tests in the regions file, whose fixture they had borrowed, and two
unit tests in `test_runner.py`. Neither location was wrong so much as partial:
a reader asking "what does the tool say about WHICH component failed?" had to
know both.

The four e2e ones run a real contract and read `components` out of the report;
the two unit ones call `_components_of` and `_failing_axes` on hand-built
measurements, which is where the epsilon and interval behaviour can be pinned
without an engine. `test_region_clauses_appear_as_components` stays with the
region checks — its subject is the region clause, not the attribution.
"""

from __future__ import annotations

from pathlib import Path

from support import needs_build123d, needs_openscad, needs_scad_tier

from partspec import Measurement, Part, Status, openscad, run

FIXTURES = Path(__file__).parent / "fixtures"
BLOCK = FIXTURES / "block_with_hole.scad"


@needs_scad_tier
def test_a_failing_envelope_names_the_failing_axis(tmp_path: Path):
    """The block is 30x20x10. Only z breaks its bound, and the report must say
    so as data — an agent acting on 'envelope failed' has to bisect; one acting
    on 'z=10 outside max=5' edits once."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 5))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.FAIL
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.FAIL}
    assert check.detail == "z=10 outside max=5"


@needs_scad_tier
def test_components_are_recorded_on_pass_too(tmp_path: Path):
    """The 7.2 principle applied to attribution: drift analysis needs the
    passing shape as much as the failing one."""
    p = Part("block", openscad(BLOCK)).envelope(max=(30, 20, 10))
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "envelope")
    assert check.status is Status.PASS
    assert check.components == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}
    assert check.detail is None


@needs_openscad
def test_a_scalar_check_carries_no_components(tmp_path: Path):
    p = Part("block", openscad(BLOCK)).volume(min=1.0)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "volume")
    assert check.components is None
    assert "components" not in check.to_json()


@needs_build123d
def test_an_unconstrained_topology_axis_is_absent_from_components(tmp_path: Path):
    """faces= alone claims nothing about edges or vertices, so those axes must
    not appear — a status on an unmade claim would be an answer to a question
    nobody asked."""
    from partspec import build123d

    model = tmp_path / "m.py"
    model.write_text("from build123d import Box\n\n\ndef make_part():\n    return Box(1, 1, 1)\n")
    p = Part("cube", build123d(model)).topology(faces=6)
    report = run(p, out_dir=tmp_path)
    check = next(c for c in report.checks if c.id == "topology")
    assert check.status is Status.PASS
    assert check.components == {"faces": Status.PASS}


def test_components_respect_the_same_epsilon_the_status_does():
    """The headline invariant, tested at the boundary where it can break: the
    binary-STL float32 round-trip that `epsilon()` exists for. A recompute of
    components with a naive comparison would fail x here while the folded
    status passes — a report contradicting its own attribution."""
    from partspec import Limit, adjudicate
    from partspec.runner import _components_of

    m = Measurement((120.30000305, 80.69999695, 40.09999847), "mm", axes=("x", "y", "z"))
    limit = Limit(max=(120.3, 80.7, 40.1))
    assert adjudicate(m, limit) is Status.PASS
    assert _components_of(m, limit) == {"x": Status.PASS, "y": Status.PASS, "z": Status.PASS}


def test_an_approximate_axis_is_never_claimed_outside_its_bound():
    """'outside' is a conclusive claim. An axis whose error band straddles the
    limit is APPROXIMATE — the tool does not know — and the detail must stay
    silent about it rather than rounding indeterminate into violated. No
    backend emits vector bounds today; this pins the path before one does."""
    from partspec import Limit
    from partspec.runner import _components_of, _failing_axes

    m = Measurement(
        (5.0, 2.01),
        "mm",
        exact=False,
        bounds=((4.9, 5.1), (1.96, 2.06)),
        axes=("a", "b"),
    )
    limit = Limit(min=(6.0, 2.0))
    components = _components_of(m, limit)
    assert components == {"a": Status.FAIL, "b": Status.APPROXIMATE}
    assert components is not None
    assert _failing_axes(m, limit, components) == "a=5 outside min=6.0"
