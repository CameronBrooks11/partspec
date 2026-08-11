"""step_roundtrip (#139): the part survives its own exchange format.

The degrader is executed, not assumed: an open shell forced into a solid
loses its entire volume through STEP (the reader's healing drops the
ill-formed solid). Healthy families mostly round-trip below 4e-13; the
worst healthy citizen is the thread family at ~6e-9, which is what
calibrates the 1e-6 default (PR #143 review, F1).
"""

from __future__ import annotations

import pytest

bd = pytest.importorskip("build123d", reason="occt extra not installed")

from support import (  # noqa: E402
    check_of,
    forced_open_solid,
    needs_mesh,
    needs_openscad,
    scad_target,
)

from partspec.backend import Unsupported  # noqa: E402
from partspec.backends.occt import OcctBackend  # noqa: E402
from partspec.cli import main  # noqa: E402
from partspec.contract import ContractError, Part  # noqa: E402
from partspec.runner import _run_geometry_check  # noqa: E402
from partspec.status import Status  # noqa: E402


def test_healthy_families_round_trip_clean():
    backend = OcctBackend()
    for shape in (
        bd.Box(20, 10, 6) - bd.Pos(5, 0, 0) * bd.Cylinder(2, 6),
        bd.fillet(bd.Box(20, 10, 6).edges(), 1.0),
        bd.loft([bd.Plane.XY * bd.Circle(8), bd.Plane.XY.offset(10) * bd.Rectangle(6, 6)]),
    ):
        outcome = backend.step_roundtrip(shape)
        assert not isinstance(outcome, Unsupported)
        assert outcome["volume_rel"] < 1e-12
        assert outcome["area_rel"] < 1e-12
        for name in ("solids", "faces", "edges"):
            before, after = outcome[name]
            assert before == after, f"{name} drifted on a healthy part"
        assert outcome["schema"], "the writer schema is recorded"


def test_the_forced_solid_loses_its_volume_through_step():
    outcome = OcctBackend().step_roundtrip(forced_open_solid())
    assert not isinstance(outcome, Unsupported)
    assert outcome["volume_rel"] == pytest.approx(1.0), "total volume loss"
    assert outcome["solids"] == (1, 0), "the reader healed the solid away"


def _spec(**kwargs):
    from partspec import build123d

    part = Part("subject", build123d("m.py"))
    part.step_roundtrip(**kwargs)
    return part.checks[0]


def test_topology_drift_fails_at_any_tolerance():
    """The two gates are separate: a count that changed is a different part
    at ANY tol, so even tol=1.0 must fail the forced solid."""
    spec = _spec(tol=1.0)
    result = _run_geometry_check(spec, OcctBackend(), forced_open_solid())
    assert result.status is Status.FAIL
    assert result.detail is not None and "solids 1 -> 0" in result.detail
    assert result.step is not None
    assert set(result.step) == {"schema"} and result.step["schema"]


class _StubBackend:
    """A backend whose round-trip reports a chosen volume drift with intact
    topology — the tol gate isolated from the topology gate."""

    kind = "stub"

    def __init__(self, volume_rel: float) -> None:
        self._volume_rel = volume_rel

    def capabilities(self):
        return frozenset({"step_roundtrip"})

    def step_roundtrip(self, artifact):
        return {
            "schema": "AP214IS",
            "volume_rel": self._volume_rel,
            "area_rel": 0.0,
            "faces": (6, 6),
            "edges": (12, 12),
            "solids": (1, 1),
        }


def test_the_tolerance_gate_bites_and_names_the_axis():
    spec = _spec()  # default 1e-6
    result = _run_geometry_check(spec, _StubBackend(1e-3), None)
    assert result.status is Status.FAIL
    assert result.detail is not None and "volume" in result.detail
    assert result.components == {"volume": Status.FAIL, "area": Status.PASS}

    relaxed = _spec(tol=1e-2)
    assert _run_geometry_check(relaxed, _StubBackend(1e-3), None).status is Status.PASS


def test_the_tol_is_never_epsilon_widened():
    """PR #143 review, F2: the shared adjudication epsilon (an absolute 1e-6
    floor built for mm-scale STL round-trips) silently swallowed any tighter
    tol on this unitless delta — the report recorded limit max=1e-9 while
    enforcing ~1e-6, and the reviewer's 1.87e-8 drift PASSED a 1e-9
    contract. Plain membership now: the tol IS the tolerance."""
    tight = _spec(tol=1e-9)
    result = _run_geometry_check(tight, _StubBackend(1.87e-8), None)
    assert result.status is Status.FAIL, "the reviewer's exact repro must fail a 1e-9 claim"

    at_limit = _spec(tol=1e-6)
    assert _run_geometry_check(at_limit, _StubBackend(2e-6), None).status is Status.FAIL, (
        "2e-6 over a 1e-6 tol passed under the old epsilon widening"
    )
    assert _run_geometry_check(at_limit, _StubBackend(5e-7), None).status is Status.PASS


def test_a_threaded_rod_calibrates_the_default():
    """PR #143 review, F1: the thread family is the worst healthy citizen —
    a fused helical sweep round-trips far over the old 1e-9 default and
    comfortably under the recalibrated 1e-6, which is why the default is 1e-6.

    The BAND is what is pinned, not a point value. The recorded figure was
    ~1.9e-8; on build123d 0.11.1 / cadquery-ocp 7.9.3.1.1 the same fixture
    measures 6.1e-9, and the old `> 1e-10` floor was two orders too loose to
    notice the drift (v0.7.0 pre-tag audit). A round-trip error is a property
    of the kernel's STEP writer and reader, so it moves under us; the floor is
    now tight enough that the next move is visible while still leaving the
    calibration argument intact.

    If this fails at the bottom, exchange fidelity improved and the 1e-6
    default should be re-derived rather than the floor lowered."""
    helix = bd.Helix(2, 10, 5)
    thread = bd.sweep(
        bd.Plane(origin=helix @ 0, z_dir=helix % 0) * bd.Circle(0.8), helix
    ) + bd.Cylinder(4.8, 10, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    outcome = OcctBackend().step_roundtrip(thread)
    assert not isinstance(outcome, Unsupported)
    assert outcome["volume_rel"] < 1e-6, "healthy threads must pass the default"
    assert outcome["volume_rel"] > 1e-9, (
        f"the thread family is why the default is 1e-6, not 1e-9; measured "
        f"{outcome['volume_rel']:.3g}. If exchange fidelity improved this much, "
        f"re-derive the default rather than lowering this floor"
    )


def test_every_refusal_branch_is_a_named_unsupported(monkeypatch):
    """PR #143 review, F3: all three refusal branches were unreachable in
    tests — a silent writer failure would have read as a perfect round trip.
    Each seam is forced and must refuse by name."""
    backend = OcctBackend()
    box = bd.Box(10, 10, 10)

    monkeypatch.setattr(OcctBackend, "_write_step", lambda self, a, path: None)
    outcome = backend.step_roundtrip(box)
    assert isinstance(outcome, Unsupported) and "writer" in outcome.reason
    monkeypatch.undo()

    monkeypatch.setattr(OcctBackend, "_read_step", lambda self, path: None)
    outcome = backend.step_roundtrip(box)
    assert isinstance(outcome, Unsupported) and "reader" in outcome.reason
    monkeypatch.undo()

    from partspec.backend import BuildError
    from partspec.engines import pycad

    monkeypatch.setattr(pycad, "adopt", lambda raw: BuildError("adoption refused"))
    outcome = backend.step_roundtrip(box)
    assert isinstance(outcome, Unsupported) and "adoption refused" in outcome.reason


def test_the_printers_are_restored_even_through_an_exception(monkeypatch):
    """PR #143 review, F4: a dropped restore would permanently mute OCCT
    diagnostics process-wide — invisible to CI, and this repo ships a
    long-lived MCP server."""
    from OCP.Message import Message  # pyright: ignore[reportAttributeAccessIssue]

    before = len(list(Message.DefaultMessenger_s().Printers()))
    # Self-blindness guard (the reviewer's exact mechanism): if an earlier
    # test in this process leaked the printers away, before == 0 and the
    # restore comparison below would pass vacuously — 0 == 0 hides the very
    # regression this test exists to catch.
    assert before > 0, "a previous test leaked the OCCT printers"
    OcctBackend().step_roundtrip(bd.Box(10, 10, 10))
    assert len(list(Message.DefaultMessenger_s().Printers())) == before

    def explode(self, path):
        raise RuntimeError("mid-roundtrip failure")

    monkeypatch.setattr(OcctBackend, "_read_step", explode)
    with pytest.raises(RuntimeError):
        OcctBackend().step_roundtrip(bd.Box(10, 10, 10))
    assert len(list(Message.DefaultMessenger_s().Printers())) == before


def test_the_declaration_validates_tol():
    for bad in (0, -1, 1.5, True, float("nan"), "0.1"):
        with pytest.raises(ContractError, match="tol"):
            _spec(tol=bad)


def test_the_check_through_the_cli_records_the_schema(tmp_path):
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.step_roundtrip()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 0
    check = check_of(out, "step_roundtrip")
    assert check["status"] == "pass"
    assert check["step"]["schema"].startswith("AP")
    assert check["measurement"]["axes"] == ["volume", "area"]
    assert check["measurement"]["exactness"] == "exact"


def test_the_cli_stdout_stays_clean_json(tmp_path, capsys):
    """The STEP machinery narrates transfers to stdout; the messenger
    silencing must keep the artifact channel pure — measure's JSON is the
    canary, since any OCCT chatter would break the parse."""
    (tmp_path / "m.py").write_text(
        "from build123d import Box\n\n\ndef make_part():\n    return Box(20, 10, 6)\n"
    )
    (tmp_path / "spec.py").write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('m.py'))\n"
        "    p.step_roundtrip()\n"
        "    return p\n"
    )
    out = tmp_path / "out"
    assert main(["check", f"{tmp_path / 'spec.py'}:make", "--quiet", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert "Transfer" not in captured.out and "Transfer" not in captured.err


@needs_openscad
@needs_mesh
def test_the_mesh_tier_refuses_with_the_tier_named(tmp_path):
    target = scad_target(tmp_path, source="block_with_hole.scad", claims="    p.step_roundtrip()\n")
    out = tmp_path / "out"
    assert main(["check", target, "--quiet", "--out", str(out)]) == 2
    check = check_of(out, "step_roundtrip")
    assert check["status"] == "unsupported"
    assert check["requires"] == "occt"
