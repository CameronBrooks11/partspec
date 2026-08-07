"""The MCP adapter: stateless verbs over `check`/`measure`, returning the same
artifact the CLI writes (D18).

Everything here runs without a CAD engine except the green end-to-end case,
which is guarded like every other engine test. The `importorskip` is the local
behaviour; `conftest.py` turns the skip into a hard failure wherever `mcp` is
declared in `PARTSPEC_REQUIRE_ENGINES`.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from support import OPENSCAD, needs_openscad

from partspec.mcp import build_server

pytest.importorskip("mcp", reason="mcp extra not installed")
anyio = pytest.importorskip("anyio", reason="mcp extra not installed")

FIXTURES = Path(__file__).parent / "fixtures"

# Not `needs_openscad`: the green run needs the whole mesh tier, and the
# mcp-only environment has the binary on PATH but no trimesh — where the
# subprocess honestly reports an environment error rather than a pass.
needs_mesh_tier = pytest.mark.skipif(
    OPENSCAD is None or importlib.util.find_spec("trimesh") is None,
    reason="the end-to-end check needs the openscad binary and the mesh extra",
)


def _tool_names() -> set[str]:
    from mcp import Client

    async def go():
        async with Client(build_server()) as client:
            return await client.list_tools()

    return {tool.name for tool in anyio.run(go).tools}


def _call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    from mcp import Client

    async def go():
        async with Client(build_server()) as client:
            return await client.call_tool(tool, args)

    result = anyio.run(go)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def test_the_server_lists_the_three_verbs_and_nothing_else():
    # "Nothing else" is the claim worth guarding: a listed tool that cannot
    # work is the tool-list version of silence reading as success. `render`
    # joined only once #17 gave it something honest to return.
    assert _tool_names() == {"check", "measure", "render"}


def test_the_entry_point_serves_over_stdio():
    """The transport the acceptance names: a client spawns the server as a
    subprocess and lists its tools, which is exactly what an agent harness
    configured with `partspec-mcp` will do."""
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "partspec.mcp"])

    async def go():
        async with Client(stdio_client(params)) as client:
            return await client.list_tools()

    assert {tool.name for tool in anyio.run(go).tools} == {"check", "measure", "render"}


def test_check_on_a_missing_contract_is_usage_plus_the_error_placeholder(tmp_path: Path):
    payload = _call(
        "check",
        {"target": f"{tmp_path}/missing.py:make", "out": str(tmp_path / "out")},
    )
    assert payload["exit_code"] == 64
    # The placeholder went down before resolution was attempted (cli.py), so
    # the artifact — and therefore this payload — says error, not a stale pass.
    assert payload["report"]["verdict"] == "error"


def test_an_unwritable_out_is_an_error_with_stderr_as_the_only_evidence(tmp_path: Path):
    # `--out` pointing at an existing *file* kills `write_placeholder` before
    # anything runs — the one path with no artifact at all. The payload must
    # say error (4), not fail (1), and carry the stderr, because there is no
    # report to speak for itself.
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    payload = _call("check", {"target": f"{tmp_path}/missing.py:make", "out": str(blocker)})
    assert payload["exit_code"] == 4
    assert payload["report"] is None
    assert payload["report_path"] is None
    assert payload["stderr"]


def test_measure_on_a_missing_contract_reports_usage_and_no_numbers(tmp_path: Path):
    payload = _call("measure", {"target": f"{tmp_path}/missing.py:make"})
    assert payload["exit_code"] == 64
    assert payload["measured"] is None
    assert "missing.py" in payload["stderr"]


@needs_mesh_tier
def test_check_returns_the_same_artifact_the_cli_writes(tmp_path: Path):
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('block_with_hole.scad'))\n"
        "    p.watertight()\n"
        "    return p\n"
    )

    payload = _call("check", {"target": f"{module}:make", "out": str(tmp_path / "out")})

    assert payload["exit_code"] == 0
    assert payload["report"]["verdict"] == "pass"
    on_disk = json.loads(Path(payload["report_path"]).read_text())
    assert payload["report"] == on_disk, "the tool must return the artifact, not a paraphrase"


@needs_openscad
def test_render_tool_returns_view_paths_or_the_display_refusal(tmp_path: Path):
    # Engine-level only — no trimesh in the loop — so this runs even in the
    # mcp-only environment, where the display refusal is the honest branch.
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    return Part('subject', openscad('block_with_hole.scad'))\n"
    )
    payload = _call("render", {"target": f"{module}:make", "out": str(tmp_path / "out")})
    if payload["exit_code"] == 0:
        assert set(payload["renders"]) == {"iso", "front", "top", "right"}
        for path in payload["renders"].values():
            assert Path(path).stat().st_size > 0
    else:
        assert payload["exit_code"] == 4
        assert payload["renders"] is None
        assert "display" in payload["stderr"]


@needs_mesh_tier
def test_check_with_render_records_the_views_in_the_returned_report(tmp_path: Path):
    shutil.copy(FIXTURES / "block_with_hole.scad", tmp_path / "block_with_hole.scad")
    module = tmp_path / "spec.py"
    module.write_text(
        "from partspec import Part, openscad\n\n\ndef make():\n"
        "    p = Part('subject', openscad('block_with_hole.scad'))\n"
        "    p.watertight()\n"
        "    return p\n"
    )
    payload = _call(
        "check", {"target": f"{module}:make", "out": str(tmp_path / "out"), "render": True}
    )
    if payload["exit_code"] == 0:
        assert set(payload["report"]["renders"]) == {"iso", "front", "top", "right"}
    else:
        # No display: the run fails loudly and the artifact stays honest.
        assert payload["exit_code"] == 4
        assert "renders" not in payload["report"]
