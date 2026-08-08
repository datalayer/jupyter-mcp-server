# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for cell.execution_count after a kernel restart in JUPYTER_SERVER
file mode.

execute_via_execution_stack polls jupyter-server-nbmodel's ExecutionStack,
whose result carries the kernel's own execution_count alongside the outputs.
_write_outputs_to_cell used to ignore it and re-derive the count by scanning
the notebook's existing cells (max + 1), which only matches the kernel's
counter when the two never diverge. A kernel restart resets the kernel's
counter without touching the file on disk, so the file-scan heuristic then
stamps a cell with a count the kernel never reported.
"""

import nbformat
import pytest

from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool


EXECUTE_RESULT_OUTPUT = {
    "output_type": "execute_result",
    "data": {"text/plain": "1"},
    "metadata": {},
    "execution_count": 1,
}


def _write_notebook_with_prior_execution_count(tmp_path, prior_count):
    """A notebook whose first cell already ran, before a kernel restart."""
    notebook = nbformat.v4.new_notebook()
    ran_cell = nbformat.v4.new_code_cell(source="x = 1")
    ran_cell.execution_count = prior_count
    notebook.cells.append(ran_cell)
    notebook.cells.append(nbformat.v4.new_code_cell(source="x + 1"))
    path = tmp_path / "notebook.ipynb"
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(notebook, f)
    return str(path)


def _read_notebook(path):
    with open(path, "r", encoding="utf-8") as f:
        return nbformat.read(f, as_version=4)


@pytest.mark.asyncio
async def test_kernel_execution_count_wins_over_file_scan_after_restart():
    """After a kernel restart, the kernel's own count is persisted, not max+1."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Cell 0 ran as execution_count=5 before the kernel restarted.
        path = _write_notebook_with_prior_execution_count(tmp_path, prior_count=5)
        tool = ExecuteCellTool()

        # The kernel restarted and its own counter is back at 1, per its reply.
        await tool._write_outputs_to_cell(
            path, 1, [], raw_outputs=[EXECUTE_RESULT_OUTPUT], kernel_execution_count=1
        )

        cell = _read_notebook(path).cells[1]
        assert cell.execution_count == 1
        assert cell.outputs[0]["execution_count"] == 1


@pytest.mark.asyncio
async def test_file_scan_fallback_unchanged_without_kernel_count():
    """Callers that cannot report a kernel execution_count keep the old heuristic."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        path = _write_notebook_with_prior_execution_count(tmp_path, prior_count=5)
        tool = ExecuteCellTool()

        await tool._write_outputs_to_cell(
            path, 1, [], raw_outputs=[EXECUTE_RESULT_OUTPUT]
        )

        cell = _read_notebook(path).cells[1]
        assert cell.execution_count == 6
