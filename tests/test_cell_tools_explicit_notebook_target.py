# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the optional notebook_name parameter on cell-level tools (#256).

Two MCP clients sharing one server race NotebookManager's process-wide
_current_notebook pointer: use_notebook(A) / cell-op / use_notebook(B) / cell-op
can interleave and silently land on the wrong notebook, because every
cell-level tool only ever resolved the implicit "current" notebook. These
tests build a fake NotebookManager with two independently-addressable
notebooks and confirm each cell-level tool's MCP_SERVER-mode path honors an
explicit notebook_name instead of always following whichever notebook is
"current".
"""

import contextlib
from typing import Any

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.clear_cell_output_tool import ClearCellOutputTool
from jupyter_mcp_server.tools.delete_cell_tool import DeleteCellTool
from jupyter_mcp_server.tools.edit_cell_source_tool import EditCellSourceTool
from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
from jupyter_mcp_server.tools.move_cell_tool import MoveCellTool
from jupyter_mcp_server.tools.overwrite_cell_source_tool import OverwriteCellSourceTool
from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool


def _notebook_model(cell_sources):
    """Build a NotebookModel-backed fake notebook with one code cell per source."""
    from jupyter_nbmodel_client import NotebookModel
    from jupyter_ydoc import YNotebook

    nb = NotebookModel()
    nb._doc = YNotebook()
    nb._doc.set({
        "cells": [
            {"cell_type": "code", "source": src, "metadata": {},
             "outputs": [], "execution_count": None}
            for src in cell_sources
        ],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })
    return nb


class _FakeNotebookManager:
    """Two independently-addressable notebooks; "A" is always the current one."""

    def __init__(self, notebooks):
        self._notebooks = notebooks
        self._current = "A"

    def __contains__(self, name):
        return name in self._notebooks

    def get_current_notebook(self):
        return self._current

    @contextlib.asynccontextmanager
    async def get_current_connection(self):
        yield self._notebooks[self._current]

    @contextlib.asynccontextmanager
    async def get_notebook_connection(self, name):
        if name not in self._notebooks:
            raise ValueError(f"Notebook '{name}' does not exist in manager")
        yield self._notebooks[name]


@pytest.fixture
def two_notebooks():
    """Notebook "A" (current) and "B" (not current), each with one cell."""
    return _FakeNotebookManager({
        "A": _notebook_model(["a_original"]),
        "B": _notebook_model(["b_original"]),
    })


@pytest.mark.asyncio
async def test_insert_cell_targets_explicit_notebook(two_notebooks):
    """insert_cell(notebook_name="B") must land in B, never in the current notebook A."""
    await InsertCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=-1,
        cell_type="code",
        cell_source="into_b",
        notebook_name="B",
    )

    assert len(two_notebooks._notebooks["A"]) == 1, "notebook A must be untouched"
    assert len(two_notebooks._notebooks["B"]) == 2
    assert two_notebooks._notebooks["B"].get_cell_source(1) == "into_b"


@pytest.mark.asyncio
async def test_insert_cell_default_still_targets_current(two_notebooks):
    """Omitting notebook_name preserves today's behavior: lands in the current notebook."""
    await InsertCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=-1,
        cell_type="code",
        cell_source="into_current",
    )

    assert len(two_notebooks._notebooks["A"]) == 2
    assert len(two_notebooks._notebooks["B"]) == 1


@pytest.mark.asyncio
async def test_read_cell_targets_explicit_notebook(two_notebooks):
    result = await ReadCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=0,
        notebook_name="B",
    )
    assert "b_original" in "\n".join(str(part) for part in result)


@pytest.mark.asyncio
async def test_delete_cell_targets_explicit_notebook(two_notebooks):
    await DeleteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_indices=[0],
        notebook_name="B",
    )
    assert len(two_notebooks._notebooks["A"]) == 1, "notebook A must be untouched"
    assert len(two_notebooks._notebooks["B"]) == 0


@pytest.mark.asyncio
async def test_overwrite_cell_source_targets_explicit_notebook(two_notebooks):
    await OverwriteCellSourceTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=0,
        cell_source="b_overwritten",
        notebook_name="B",
    )
    assert two_notebooks._notebooks["A"].get_cell_source(0) == "a_original"
    assert two_notebooks._notebooks["B"].get_cell_source(0) == "b_overwritten"


@pytest.mark.asyncio
async def test_edit_cell_source_targets_explicit_notebook(two_notebooks):
    await EditCellSourceTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=0,
        old_string="b_original",
        new_string="b_edited",
        notebook_name="B",
    )
    assert two_notebooks._notebooks["A"].get_cell_source(0) == "a_original"
    assert two_notebooks._notebooks["B"].get_cell_source(0) == "b_edited"


@pytest.mark.asyncio
async def test_clear_cell_output_targets_explicit_notebook(two_notebooks):
    b = two_notebooks._notebooks["B"]
    cell = b[0]
    cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": "hi\n"}]
    cell["execution_count"] = 3
    b[0] = cell

    a_cell_before = dict(two_notebooks._notebooks["A"][0])

    await ClearCellOutputTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=0,
        notebook_name="B",
    )

    assert b[0]["outputs"] == []
    assert b[0]["execution_count"] is None
    assert dict(two_notebooks._notebooks["A"][0]) == a_cell_before, "notebook A must be untouched"


@pytest.mark.asyncio
async def test_move_cell_targets_explicit_notebook(two_notebooks):
    b = two_notebooks._notebooks["B"]
    b.insert_cell(1, "second", "code")

    await MoveCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        source_index=0,
        target_index=1,
        notebook_name="B",
    )

    assert two_notebooks._notebooks["A"].get_cell_source(0) == "a_original"
    assert b.get_cell_source(1) == "b_original"


@pytest.mark.asyncio
async def test_unknown_notebook_name_raises(two_notebooks):
    """An explicit target that isn't connected must fail loudly, never fall back to current."""
    with pytest.raises(ValueError, match="not connected"):
        await InsertCellTool().execute(
            mode=ServerMode.MCP_SERVER,
            notebook_manager=two_notebooks,
            cell_index=-1,
            cell_type="code",
            cell_source="x",
            notebook_name="does-not-exist",
        )


@pytest.mark.asyncio
async def test_execute_cell_targets_explicit_notebook(two_notebooks):
    """execute_cell(notebook_name='B') must execute against notebook B and its kernel, not A (#446)."""
    from types import SimpleNamespace
    from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool

    executed_on: list[tuple[str, int, Any]] = []

    for label in ("A", "B"):
        nb = two_notebooks._notebooks[label]

        def _make_exec(lbl, notebook_obj):
            def _exec(idx, runner, timeout=None):
                executed_on.append((lbl, idx, runner))
                cell = notebook_obj[idx]
                cell["outputs"] = [
                    {"output_type": "stream", "name": "stdout", "text": f"ran_{lbl}\n"}
                ]
                notebook_obj[idx] = cell
                return {"status": "ok", "execution_count": 1}

            return _exec

        nb.execute_cell = _make_exec(label, nb)

    kernels = {
        "A": SimpleNamespace(id="kernel-a"),
        "B": SimpleNamespace(id="kernel-b"),
    }
    two_notebooks.get_code_sandbox = lambda name: kernels.get(name)
    two_notebooks.get_code_sandbox_id = lambda name: kernels[name].id if name in kernels else None

    result = await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=two_notebooks,
        cell_index=0,
        stream=False,
        ensure_code_sandbox_alive_fn=lambda name=None: kernels[name or "A"],
        notebook_name="B",
    )

    assert len(executed_on) == 1
    assert executed_on[0][0] == "B"
    assert executed_on[0][2] is kernels["B"]
    assert "ran_B" in "\n".join(str(part) for part in result)


@pytest.mark.asyncio
async def test_execute_cell_unknown_notebook_name_raises(two_notebooks):
    from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool

    with pytest.raises(ValueError, match="not connected"):
        await ExecuteCellTool().execute(
            mode=ServerMode.MCP_SERVER,
            notebook_manager=two_notebooks,
            cell_index=0,
            ensure_code_sandbox_alive_fn=lambda: None,
            notebook_name="does-not-exist",
        )


def test_instructions_and_execution_schemas_include_notebook_name():
    """INSTRUCTIONS and execution tool schemas expose notebook_name for multi-agent safety (#446)."""
    import asyncio
    from jupyter_mcp_server.server import INSTRUCTIONS, mcp

    assert "ALWAYS MCP" in INSTRUCTIONS
    assert "notebook_name" in INSTRUCTIONS
    assert "execute_cell" in INSTRUCTIONS

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert "notebook_name" in tools["execute_cell"].input_schema.get("properties", {})
    assert "notebook_name" in tools["insert_execute_code_cell"].input_schema.get("properties", {})
