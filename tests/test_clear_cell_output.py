# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the clear_cell_output MCP tool.

File-based tests exercising _clear_cell_output_file end-to-end on a real
notebook file written to a tmp_path (no server needed), plus unit tests for
_clear_notebook_model_cell against a NotebookModel-shaped fake (covers the
YDoc/WebSocket code path without a live collaborative session).

Launch the tests:
```
$ pytest tests/test_clear_cell_output.py -v
```
"""

import nbformat
import pytest

from jupyter_mcp_server.tools.clear_cell_output_tool import ClearCellOutputTool


def _write_notebook(path, cell_specs):
    """Write a notebook to *path* from a list of (cell_type, source, outputs, execution_count)."""
    nb = nbformat.v4.new_notebook()
    for cell_type, source, outputs, execution_count in cell_specs:
        if cell_type == "code":
            cell = nbformat.v4.new_code_cell(source=source)
            cell.outputs = outputs
            cell.execution_count = execution_count
        else:
            cell = nbformat.v4.new_markdown_cell(source=source)
        nb.cells.append(cell)
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)


def _read_notebook(path):
    with open(path, "r", encoding="utf-8") as f:
        return nbformat.read(f, as_version=4)


###############################################################################
# Section A — File-based behaviour (no server needed)
###############################################################################


class TestClearCellOutputFile:
    def setup_method(self):
        self.tool = ClearCellOutputTool()

    @pytest.mark.asyncio
    async def test_clears_outputs_and_execution_count(self, tmp_path):
        """A code cell with real output loses both outputs and execution_count."""
        path = str(tmp_path / "nb.ipynb")
        stream_output = nbformat.v4.new_output(output_type="stream", name="stdout", text="hi\n")
        _write_notebook(path, [("code", "print('hi')", [stream_output], 3)])

        cleared_count = await self.tool._clear_cell_output_file(path, 0)

        assert cleared_count == 1
        notebook = _read_notebook(path)
        assert notebook.cells[0].outputs == []
        assert notebook.cells[0].execution_count is None

    @pytest.mark.asyncio
    async def test_no_output_cell_returns_zero(self, tmp_path):
        """Clearing a cell that already has no output reports 0, and stays a no-op."""
        path = str(tmp_path / "nb.ipynb")
        _write_notebook(path, [("code", "1 + 1", [], None)])

        cleared_count = await self.tool._clear_cell_output_file(path, 0)

        assert cleared_count == 0
        notebook = _read_notebook(path)
        assert notebook.cells[0].outputs == []
        assert notebook.cells[0].execution_count is None

    @pytest.mark.asyncio
    async def test_only_targeted_cell_is_touched(self, tmp_path):
        """Clearing cell 1 must not disturb cell 0's output/execution_count."""
        path = str(tmp_path / "nb.ipynb")
        out0 = nbformat.v4.new_output(output_type="stream", name="stdout", text="a\n")
        out1 = nbformat.v4.new_output(output_type="stream", name="stdout", text="b\n")
        _write_notebook(path, [
            ("code", "print('a')", [out0], 1),
            ("code", "print('b')", [out1], 2),
        ])

        cleared_count = await self.tool._clear_cell_output_file(path, 1)

        assert cleared_count == 1
        notebook = _read_notebook(path)
        assert len(notebook.cells[0].outputs) == 1
        assert notebook.cells[0].execution_count == 1
        assert notebook.cells[1].outputs == []
        assert notebook.cells[1].execution_count is None

    @pytest.mark.asyncio
    async def test_markdown_cell_rejected(self, tmp_path):
        """Clearing a non-code cell raises rather than silently no-op'ing."""
        path = str(tmp_path / "nb.ipynb")
        _write_notebook(path, [("markdown", "# title", None, None)])

        with pytest.raises(ValueError, match="not a code cell"):
            await self.tool._clear_cell_output_file(path, 0)

    @pytest.mark.asyncio
    async def test_out_of_range_index_raises(self, tmp_path):
        path = str(tmp_path / "nb.ipynb")
        _write_notebook(path, [("code", "1", [], None)])

        with pytest.raises(ValueError, match="out of range"):
            await self.tool._clear_cell_output_file(path, 5)

    @pytest.mark.asyncio
    async def test_negative_index_raises(self, tmp_path):
        """Same class of bug as delete_cell's negative-index guard: reject
        rather than silently resolving via Python's negative indexing."""
        path = str(tmp_path / "nb.ipynb")
        _write_notebook(path, [("code", "1", [], None)])

        with pytest.raises(ValueError, match="out of range"):
            await self.tool._clear_cell_output_file(path, -1)


###############################################################################
# Section B — NotebookModel-shaped fake (covers the YDoc/WebSocket branch)
###############################################################################


class _FakeNotebookModel:
    """Minimal stand-in for jupyter_nbmodel_client.NotebookModel's sequence
    protocol (__len__/__getitem__/__setitem__), which is all
    _clear_notebook_model_cell relies on."""

    def __init__(self, cells):
        self._cells = cells

    def __len__(self):
        return len(self._cells)

    def __getitem__(self, index):
        return dict(self._cells[index])

    def __setitem__(self, index, value):
        self._cells[index] = value


class TestClearCellOutputNotebookModel:
    def setup_method(self):
        self.tool = ClearCellOutputTool()

    def test_clears_outputs_and_execution_count(self):
        nb = _FakeNotebookModel([
            {
                "cell_type": "code",
                "source": "print(1)",
                "outputs": [{"output_type": "stream"}],
                "execution_count": 2,
            },
        ])

        cleared_count = self.tool._clear_notebook_model_cell(nb, 0)

        assert cleared_count == 1
        assert nb._cells[0]["outputs"] == []
        assert nb._cells[0]["execution_count"] is None
        # Untouched fields survive the read-modify-write round trip.
        assert nb._cells[0]["source"] == "print(1)"

    def test_markdown_cell_rejected(self):
        nb = _FakeNotebookModel([{"cell_type": "markdown", "source": "# hi"}])

        with pytest.raises(ValueError, match="not a code cell"):
            self.tool._clear_notebook_model_cell(nb, 0)

    def test_out_of_range_index_raises(self):
        nb = _FakeNotebookModel([
            {"cell_type": "code", "source": "1", "outputs": [], "execution_count": None},
        ])

        with pytest.raises(ValueError, match="out of range"):
            self.tool._clear_notebook_model_cell(nb, 5)
