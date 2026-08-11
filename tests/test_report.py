"""The report artifact, including a conformance test against the spec's own example.

That example is not decorative — SPEC-report.md 1 says the report *is* the
contract, so the document's canonical sample should be executable. Testing it
catches the specific defect where a spec drifts from its own illustration and an
implementer builds a conformance suite from a broken fixture.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from support import needs_mesh, report_of

from partspec.report import SCHEMA_VERSION, CheckResult, Report, write_placeholder
from partspec.status import Limit, Measurement, Status, Verdict

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _report(**kw) -> Report:
    return Report(part_id="p", contract="parts/p.py:main", tool_version="0.1.0", **kw)


def _check(status: Status, **kw) -> CheckResult:
    kw.setdefault("id", f"c-{status.value}")
    kw.setdefault("kind", "envelope")
    kw.setdefault("phase", "geometry")
    return CheckResult(status=status, **kw)


# --------------------------------------------------------------------------
# shape
# --------------------------------------------------------------------------


def test_field_order_is_fixed():
    """Ordering is a correctness property: reports get compared across runs."""
    doc = _report().to_json()
    assert list(doc) == [
        "schema_version",
        "tool",
        "part",
        "engine",
        "params",
        "geometry",
        "verdict",
        "counts",
        "attribution",
        "checks",
        "error",
        "hint",
        "build_origin",
        "build_stderr",
        "environment",
        "invocation",
    ]


def test_the_spec_example_carries_the_same_fields_in_the_same_order():
    """§8 rule 1 says keys MUST be emitted in the order §7 gives — so §7's
    example has to be able to answer what that order IS.

    It could not: `attribution` and `build_origin` were emitted by every report
    since v0.4.0 and appeared nowhere in the canonical block, so a consumer
    building against the document would have found two unexpected keys and no
    stated position for them. Found by the v0.7.0 pre-tag audit.

    Compared as a SUBSEQUENCE rather than for equality: the example is a `check`
    report, and `renders`/`render_tessellation` belong to the render payloads
    §7 also documents. Every key the example shows must appear in the emitted
    order, and none may be missing from the example.
    """
    import re

    spec = (Path(__file__).resolve().parent.parent / "docs" / "SPEC-report.md").read_text()
    start = spec.index("```jsonc", spec.index("## 7."))
    block = spec[start : spec.index("```", start + 8)]
    example = re.findall(r'^  "(\w+)"', block, re.M)

    emitted = list(_report().to_json())
    render_only = {"renders", "render_tessellation"}
    documented = [k for k in example if k not in render_only]

    assert set(documented) == set(emitted), (
        f"documented but never emitted: {sorted(set(documented) - set(emitted))}; "
        f"emitted but undocumented: {sorted(set(emitted) - set(documented))}"
    )
    assert documented == [k for k in emitted if k in set(documented)], (
        f"§7's example orders keys {documented}, the writer emits {emitted}"
    )


def test_counts_are_the_per_status_tally_not_merely_a_sum():
    """The deslop audit's V1: this asserted only that the tally summed, so
    `tally[c.status.value] += 1` -> `tally["pass"] += 1` survived the whole
    725-test suite. The mutant produces a report whose counts block says
    every check passed while the verdict says fail — a false tally inside the
    artifact that IS the product contract, and `diff` reads only
    `counts.total` (which stays honest), so the comparator misses it too.
    The exact dict over EVERY status, or this test proves nothing. Three of
    five left `approximate` and `skipped` pinned only at zero, and a mutant
    tallying `skipped` as `approximate` still survived all 742 tests — which
    is the same false tally in a subtler spelling, since `skipped` means not
    measured and `approximate` means measured with tolerance.
    """
    r = _report(
        checks=[
            _check(Status.PASS),
            _check(Status.FAIL),
            _check(Status.APPROXIMATE),
            _check(Status.UNSUPPORTED),
            _check(Status.SKIPPED),
        ]
    )
    assert r.counts() == {
        "total": 5,
        "pass": 1,
        "fail": 1,
        "approximate": 1,
        "unsupported": 1,
        "skipped": 1,
    }


def test_deleted_fields_stay_deleted():
    """Speculative fields removed after review; regression guard."""
    doc = _report().to_json()
    assert "units" not in doc["part"]
    assert "tier" not in doc["engine"]
    assert "allow_incomplete" not in doc["invocation"]


def test_measurement_serialises_exactness_not_a_bare_float():
    r = _report(
        checks=[
            _check(
                Status.PASS,
                measurement=Measurement((15.8, 15.8, 8.0), "mm", axes=("x", "y", "z")),
                limit=Limit(max=(40, 40, 15)),
            )
        ]
    )
    m = r.to_json()["checks"][0]["measurement"]
    assert m["exactness"] == "exact"
    assert m["axes"] == ["x", "y", "z"]
    assert "bounds" not in m


def test_approximate_measurement_carries_bounds():
    r = _report(
        checks=[
            _check(
                Status.APPROXIMATE,
                measurement=Measurement(2.01, "mm", exact=False, bounds=(1.96, 2.06)),
                limit=Limit(min=2.0),
            )
        ]
    )
    m = r.to_json()["checks"][0]["measurement"]
    assert m["exactness"] == "approximate"
    assert m["bounds"] == [1.96, 2.06]


def test_predicate_check_has_no_measurement_or_limit():
    """Q7: parameter predicates are not measurements (SPEC-contract.md 5).

    Recording operands means a failure reports the inputs that produced it,
    rather than a bare `false` the reader has to re-derive.
    """
    r = _report(
        checks=[
            CheckResult(
                id="pin_fits_shell",
                kind="requires",
                phase="parameter",
                status=Status.FAIL,
                expr="pin_radius + allowance/2 <= shell_thickness",
                operands={"pin_radius": 1.0, "allowance": 0.2, "shell_thickness": 1.0},
                detail="1.1 <= 1.0 is false",
            )
        ]
    )
    c = r.to_json()["checks"][0]
    assert c["measurement"] is None and c["limit"] is None
    assert c["operands"]["shell_thickness"] == 1.0


def test_unsupported_names_the_tier_that_would_answer():
    r = _report(
        checks=[
            _check(
                Status.UNSUPPORTED,
                kind="hole_diameter",
                measurement=None,
                limit=Limit(min=10.0),
                requires="occt",
            )
        ]
    )
    assert r.to_json()["checks"][0]["requires"] == "occt"


# --------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------


def test_unsupported_does_not_read_as_green():
    """The property the whole tool exists to preserve."""
    r = _report(checks=[_check(Status.PASS), _check(Status.UNSUPPORTED)])
    assert r.verdict is Verdict.INCOMPLETE
    assert r.exit_code != 0


def test_no_checks_is_empty_not_pass():
    r = _report(checks=[])
    assert r.verdict is Verdict.EMPTY
    assert r.exit_code != 0


# --------------------------------------------------------------------------
# write semantics
# --------------------------------------------------------------------------


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path):
    _report(checks=[_check(Status.PASS)]).write(tmp_path)
    assert report_of(tmp_path)["verdict"] == "pass"
    assert not list(tmp_path.glob(".partspec-*"))


def test_a_failed_serialisation_leaves_no_temp_file_behind(tmp_path: Path, monkeypatch):
    """The cleanup that only runs when writing FAILS, which is the only case
    where a temp file can exist. The existing atomic-write test asserts the
    absence on the success path, where nothing could have been left — so
    deleting `Path(tmp).unlink(missing_ok=True)` from the failure handler
    passed the whole suite.
    """
    import json as json_module

    def explode(*args, **kwargs):
        raise RuntimeError("serialisation failed mid-write")

    monkeypatch.setattr(json_module, "dump", explode)
    with pytest.raises(RuntimeError, match="mid-write"):
        _report(checks=[_check(Status.PASS)]).write(tmp_path)

    assert not list(tmp_path.glob(".partspec-*")), "a failed write must not leave its scratch"
    assert not (tmp_path / "report.json").exists(), "and must not leave a half report either"


def test_write_overwrites_rather_than_accumulating(tmp_path: Path):
    _report(checks=[_check(Status.FAIL)]).write(tmp_path)
    _report(checks=[_check(Status.PASS)]).write(tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert report_of(tmp_path)["verdict"] == "pass"


def test_placeholder_is_written_before_the_engine_runs(tmp_path: Path):
    """A try/finally cannot survive an OCP segfault. Writing the placeholder
    first means the worst case is a report saying the run died, never one
    saying the part was fine."""
    write_placeholder(tmp_path, part_id="p", contract="parts/p.py:main", argv=["check", "p"])
    doc = report_of(tmp_path)
    assert doc["verdict"] == "error"
    assert doc["error"]


def test_placeholder_is_replaced_by_the_real_report(tmp_path: Path):
    write_placeholder(tmp_path, part_id="p", contract="parts/p.py:main", argv=[])
    _report(checks=[_check(Status.PASS)]).write(tmp_path)
    assert report_of(tmp_path)["verdict"] == "pass"


@needs_mesh
def test_packages_are_not_quarantined_from_comparison():
    """environment.packages distinguishes 'a dependency upgrade moved this
    number' from 'the design changed' — so it must be present and comparable.

    Presence alone was the whole assertion, and an empty dict satisfied it
    while defeating the purpose: `_installed_versions()` -> `{}` passed the
    suite. The content is the claim.

    `needs_mesh`, not `needs_scad_tier`: this drives no OpenSCAD part and does
    not want the binary. What it needs is for at least one of the packages
    `_installed_versions()` enumerates to BE installed, since a base install
    yields `{}` and fails the assertion above. Marking it on the binary too
    would silence it in every `partspec[mesh]` install without OpenSCAD, where
    it passes — over-skipping being the same sin as the under-skipping this
    change is about (PR #163 review).
    """
    from importlib.metadata import PackageNotFoundError, version

    packages = _report().to_json()["environment"]["packages"]
    assert packages, "an empty map explains nothing about a moved number"

    # Against the installed metadata, not merely well-shaped: a fabricated map
    # of str -> str satisfied the first repair while recording nothing real.
    for name, recorded in packages.items():
        assert version(name) == recorded, f"{name} recorded as {recorded}"

    # And every installed engine must appear. Requiring "at least one" let the
    # field silently stop recording a whole tier — exactly the case the block
    # exists for. The list is duplicated on purpose: which packages explain a
    # moved number is a product decision, like DEFAULT_TIMEOUT_S's value.
    for name in ("build123d", "cadquery", "cadquery-ocp", "trimesh", "manifold3d"):
        try:
            installed = version(name)
        except PackageNotFoundError:
            continue
        assert packages.get(name) == installed, (
            f"{name} is installed at {installed}; the report says {packages.get(name)!r}"
        )


# --------------------------------------------------------------------------
# conformance: the spec's own example
# --------------------------------------------------------------------------


def _spec_example() -> dict:
    text = (DOCS / "SPEC-report.md").read_text()
    match = re.search(r"```jsonc\n(\{\n  \"schema_version\".*?)\n```", text, re.S)
    assert match, "the normative schema block is missing from SPEC-report.md"
    stripped = re.sub(r"//.*", "", match.group(1)).replace("...", "")
    return json.loads(stripped)


def test_spec_example_is_valid_json():
    assert _spec_example()["schema_version"] == SCHEMA_VERSION


def test_spec_example_satisfies_its_own_counts_rule():
    doc = _spec_example()
    counts = doc["counts"]
    assert counts["total"] == len(doc["checks"])
    assert sum(v for k, v in counts.items() if k != "total") == counts["total"]


def test_spec_example_attribution_is_what_its_own_checks_compute():
    """The example says it is conformant, so its `attribution` must be the
    value `Report.attribution()` would produce for those checks.

    Added with the field itself and got it wrong on the first pass: I wrote
    `attributed: 1` when no check in the example carries a `source` citation at
    all — the only `"source"` in the block is `part.source`, the file path. The
    honest value is 0, which makes the example an instance of `dimensional > 0
    && attributed == 0`: exactly the circular-contract shape §6's warning
    exists to flag. Depicting that as clean, in the document that defines the
    warning, is worse than omitting the field (PR #160 review).

    Derived here rather than asserted, so the next edit to the example's checks
    cannot leave the summary behind.
    """
    from partspec.contract import DIMENSIONAL_KINDS

    doc = _spec_example()
    dimensional = [c for c in doc["checks"] if c["kind"] in DIMENSIONAL_KINDS]
    attributed = [c for c in dimensional if c.get("source")]
    assert doc["attribution"] == {
        "dimensional": len(dimensional),
        "attributed": len(attributed),
    }, "the example's summary must match the example's checks"


def test_spec_example_statuses_match_its_counts():
    doc = _spec_example()
    tally: dict[str, int] = {}
    for c in doc["checks"]:
        tally[c["status"]] = tally.get(c["status"], 0) + 1
    for status, n in tally.items():
        assert doc["counts"][status] == n, f"counts disagree with checks for {status!r}"


def test_spec_example_verdict_follows_from_its_statuses():
    doc = _spec_example()
    from partspec.status import verdict_of

    statuses = [Status(c["status"]) for c in doc["checks"]]
    assert str(verdict_of(statuses)) == doc["verdict"]


def test_spec_example_uses_no_deleted_fields():
    doc = _spec_example()
    assert "units" not in doc["part"]
    assert "tier" not in doc["engine"]
    assert "allow_incomplete" not in doc["invocation"]


@pytest.mark.parametrize("check", _spec_example()["checks"])
def test_spec_example_checks_are_well_formed(check):
    assert Status(check["status"])
    assert check["phase"] in {"parameter", "geometry"}
    if check["status"] == "unsupported":
        assert check["measurement"] is None
        assert check.get("requires"), "unsupported must name the tier that would answer"
    if "components" in check:
        # Attribution must agree with the verdict it attributes: every value a
        # real status, and the worst of them exactly the check's own.
        from partspec.status import worst

        statuses = [Status(v) for v in check["components"].values()]
        assert worst(statuses) == Status(check["status"])


def test_components_serialise_between_limit_and_detail_as_strings():
    r = _report(
        checks=[
            _check(
                Status.FAIL,
                measurement=Measurement((45.0, 20.0, 10.0), "mm", axes=("x", "y", "z")),
                limit=Limit(max=(40, 40, 15)),
                components={"x": Status.FAIL, "y": Status.PASS, "z": Status.PASS},
            )
        ]
    )
    check = r.to_json()["checks"][0]
    assert check["components"] == {"x": "fail", "y": "pass", "z": "pass"}
    assert list(check) == [
        "id",
        "kind",
        "phase",
        "status",
        "measurement",
        "limit",
        "components",
        "detail",
    ]


def test_hole_serialises_after_region_position():
    r = _report(
        checks=[
            _check(
                Status.FAIL,
                kind="hole_diameter",
                hole={"d": 8.0, "count": 2},
                detail="found 0 bore(s)",
            )
        ]
    )
    check = r.to_json()["checks"][0]
    assert check["hole"] == {"d": 8.0, "count": 2}
    assert list(check) == [
        "id",
        "kind",
        "phase",
        "status",
        "measurement",
        "limit",
        "hole",
        "detail",
    ]


def test_the_version_fallback_is_distinguishable_from_a_real_release():
    """Not the literal — the property. `tool.version` reaches the artifact,
    and a consumer must be able to tell "run from a source tree" from "ran
    release 0.0.0". A PEP 440 local-version segment says so and survives any
    rewording; pinning the string itself would pin an implementation detail.
    """
    from partspec.report import TOOL_VERSION_FALLBACK

    assert "+" in TOOL_VERSION_FALLBACK


def test_a_failed_write_leaves_the_previous_report_intact(tmp_path: Path):
    """`_write_json` writes to a temp file and renames, and nothing held it to
    that (#153, recorded there as "also unpinned").

    Measured: replacing the tempfile/`os.replace` dance with a direct
    `os.open(path, O_WRONLY|O_CREAT|O_TRUNC)` left the whole suite green apart
    from an unused-import lint. So the docstring's claim — "a partially written
    report that happens to parse is worse than none" — was prose only.

    The trigger is the writer's own `allow_nan=False`, not a monkeypatch:
    `json.dump` streams, so it emits the opening bytes and then raises on the
    non-finite value. A truncating writer has destroyed the previous report by
    that point; this one has not touched it.

    Two properties, and the second is the one that actually says "atomic".
    Failure-leaves-the-old-file-alone is satisfied by a writer that encodes to
    a temp file and then *copies* it over the destination — under which a
    concurrent reader can still observe a half-written report, which is the
    property the temp-file dance exists for. So the successful path is checked
    too, by inode: `os.replace` swaps a new file into the name, while any
    open-and-write keeps the original inode. A copy-into-place writer passes
    the first assertion and fails the second.

    NOT held here: the `fsync`. That is crash durability rather than
    atomicity, and no in-process test can observe it — removing the `fsync`
    leaves both assertions below green, deliberately.
    """
    from partspec.report import _write_json

    path = tmp_path / "report.json"
    _write_json(path, {"verdict": "pass", "checks": []})
    before = path.read_text()

    with pytest.raises(ValueError, match="Out of range float"):
        _write_json(path, {"verdict": "fail", "measurement": float("nan")})

    assert path.read_text() == before, (
        "the previous report was modified by a write that failed; a reader "
        "arriving now sees a truncated or half-written artifact"
    )
    assert json.loads(path.read_text())["verdict"] == "pass"
    litter = [p.name for p in tmp_path.iterdir() if p.name.startswith(".partspec-")]
    assert not litter, f"the failed write left its temp file behind: {litter}"

    inode_before = path.stat().st_ino
    _write_json(path, {"verdict": "fail", "checks": []})
    assert json.loads(path.read_text())["verdict"] == "fail", "the good write still lands"
    assert path.stat().st_ino != inode_before, (
        "the report was written in place rather than renamed over; a reader "
        "holding the path can observe a partially written artifact"
    )
