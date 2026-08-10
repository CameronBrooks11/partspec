"""#78: a missing package at model import is the machine's fault, not the part's.

Found live: a `uv sync` dropped an ad-hoc `cqkit` install and the dogfood batch
reported the CadQuery model as an unexpected *failure* — a design "disproven"
by a missing wheel. The split is genuinely ambiguous (a model importing its own
nonexistent helper IS a model fault), so the rule is evidence-based: if the
missing module's top-level name has nothing beside the model, only an installed
package could ever have satisfied it — environment. If something by that name
sits beside the model, the failure lives in local code — model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partspec.backend import BuildError
from partspec.cli import main
from partspec.engines.pycad import _missing_module_error

# --------------------------------------------------------------------------
# the classifier, engine-free
# --------------------------------------------------------------------------


def _mnfe(name: str) -> ModuleNotFoundError:
    return ModuleNotFoundError(f"No module named '{name}'", name=name)


def test_a_name_absent_beside_the_model_is_environment(tmp_path: Path):
    err = _missing_module_error(_mnfe("cqkit"), tmp_path, "model raised on import")
    assert isinstance(err, BuildError)
    assert err.origin == "environment"
    assert "cqkit" in err.message and "beside the model" in err.message
    assert err.hint is not None and "install" in err.hint


def test_the_hint_disclosed_the_ambiguity_it_cannot_adjudicate(tmp_path: Path):
    err = _missing_module_error(_mnfe("helper_uils"), tmp_path, "model raised on import")
    assert err is not None and err.hint is not None
    assert "meant to be a helper" in err.hint


def test_a_missing_submodule_of_a_local_package_stays_model(tmp_path: Path):
    (tmp_path / "helpers").mkdir()
    (tmp_path / "helpers" / "__init__.py").write_text("")
    assert _missing_module_error(_mnfe("helpers.gears"), tmp_path, "x") is None


def test_a_local_module_file_that_is_not_a_package_stays_model(tmp_path: Path):
    (tmp_path / "helpers.py").write_text("")
    assert _missing_module_error(_mnfe("helpers.gears"), tmp_path, "x") is None


def test_a_nameless_error_stays_model(tmp_path: Path):
    assert _missing_module_error(ModuleNotFoundError("odd"), tmp_path, "x") is None


# --------------------------------------------------------------------------
# end to end: the report a CI run would read
# --------------------------------------------------------------------------


def _target(tmp_path: Path, model_body: str) -> str:
    (tmp_path / "model.py").write_text(model_body)
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from partspec import Part, build123d\n\n\ndef make():\n"
        "    p = Part('subject', build123d('model.py'))\n"
        "    p.volume(min=1.0)\n"
        "    return p\n"
    )
    return f"{spec}:make"


def test_a_missing_wheel_at_import_is_error_not_a_failing_part(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    out = tmp_path / "out"
    target = _target(
        tmp_path, "import definitely_not_installed_xyz\n\n\ndef make_part():\n    pass\n"
    )
    code = main(["check", target, "--quiet", "--out", str(out)])
    assert code == 4, "a missing wheel must not read as a disproven design"

    report = json.loads((out / "report.json").read_text())
    assert report["verdict"] == "error"
    assert report["build_origin"] == "environment"
    assert "definitely_not_installed_xyz" in report["error"]
    statuses = {c["kind"]: c["status"] for c in report["checks"]}
    assert statuses.get("builds") != "fail"
    assert statuses["volume"] == "skipped"


def test_a_lazy_missing_wheel_in_the_factory_is_the_same_statement(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    out = tmp_path / "out"
    target = _target(tmp_path, "def make_part():\n    import definitely_not_installed_xyz\n")
    code = main(["check", target, "--quiet", "--out", str(out)])
    assert code == 4
    report = json.loads((out / "report.json").read_text())
    assert report["build_origin"] == "environment"
    assert "definitely_not_installed_xyz" in report["error"]


def test_a_lazy_local_import_names_the_harness_asymmetry(tmp_path: Path):
    """A helper beside the model imports fine at module top level but not from
    inside the factory — the model's directory leaves sys.path after `_load`.
    That stays a build failure, but the hint must say why (PR #101 review):
    a model that runs under plain `python model.py` reading as a disproven
    design with no explanation sends the repair loop at the wrong file."""
    pytest.importorskip("build123d", reason="occt extra not installed")
    # A name unique to this test: `sys.modules` caches a previously-built
    # model's helpers top-level (the review's finding 3, owned by #29), and a
    # shared name here would import a stale module instead of failing.
    (tmp_path / "lazyhelper_78.py").write_text("VALUE = 1\n")
    out = tmp_path / "out"
    target = _target(tmp_path, "def make_part():\n    import lazyhelper_78\n")
    code = main(["check", target, "--quiet", "--out", str(out)])
    assert code == 1

    report = json.loads((out / "report.json").read_text())
    assert "import time only" in report["hint"]
    assert "sys.path" in report["hint"]


def test_a_broken_local_import_chain_is_still_the_parts_fault(tmp_path: Path):
    pytest.importorskip("build123d", reason="occt extra not installed")
    (tmp_path / "helpers").mkdir()
    (tmp_path / "helpers" / "__init__.py").write_text("")
    out = tmp_path / "out"
    target = _target(tmp_path, "import helpers.gears\n\n\ndef make_part():\n    pass\n")
    code = main(["check", target, "--quiet", "--out", str(out)])
    assert code == 1, "a fault inside local model code is a failing part"

    report = json.loads((out / "report.json").read_text())
    assert report["verdict"] == "fail"
    statuses = {c["kind"]: c["status"] for c in report["checks"]}
    assert statuses["builds"] == "fail"


def test_a_stranded_ocp_proxy_is_named_not_circular(monkeypatch):
    """#109: cadquery-ocp-proxy installed but no OCP delivered (the uv pip
    case) — the old hint said pip install partspec[occt], which a uv user
    re-runs through uv, forever."""
    import importlib.metadata as md

    from partspec.engines.pycad import _engine_import_error

    real = md.distribution

    class _Proxy:
        version = "7.9.3.1.1"

    def fake(name):
        if name == "cadquery-ocp-proxy":
            return _Proxy()
        raise md.PackageNotFoundError(name)

    monkeypatch.setattr(md, "distribution", fake)
    try:
        err = _engine_import_error("build123d", ImportError("No module named 'OCP'"))
    finally:
        monkeypatch.setattr(md, "distribution", real)
    assert err.origin == "environment"
    assert "cadquery-ocp-proxy" in err.message and "delivered no OCP" in err.message
    assert err.hint is not None and "plain pip" in err.hint and "#109" in err.hint


def test_the_registry_never_records_partspec_itself():
    """PR #147's review, minor 10: the registry was described as preventing
    the over-eviction a directory sweep once caused — "it evicted the
    editable-installed partspec itself" — and it did not.

    An editable install's source is not under `site-packages`, so the
    existing filter misses it, and a contract sitting at the repo root makes
    every `partspec.*` module relative to the model root. Recording them
    means a later eviction re-imports the package, and classes built by the
    second import fail `isinstance` against objects held from the first —
    the duplicate-class break, reproduced live during that review. The
    protection is real now, and this is what holds it.
    """
    import sys

    from partspec.engines.pycad import _LOADED_MODEL_MODULES, record_model_modules

    repo_root = Path(__file__).resolve().parents[1]
    contract_at_root = repo_root / "contract.py"
    assert "partspec.diff" in sys.modules, "the fixture needs partspec already imported"

    before = set(sys.modules) - {"partspec", "partspec.diff"}
    try:
        record_model_modules(contract_at_root, before)
        recorded = _LOADED_MODEL_MODULES.get(str(repo_root), set())
        assert not {n for n in recorded if n == "partspec" or n.startswith("partspec.")}, (
            "the registry must never make partspec's own modules evictable"
        )
    finally:
        _LOADED_MODEL_MODULES.pop(str(repo_root), None)
