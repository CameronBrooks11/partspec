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
