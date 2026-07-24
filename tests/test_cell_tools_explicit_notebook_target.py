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
