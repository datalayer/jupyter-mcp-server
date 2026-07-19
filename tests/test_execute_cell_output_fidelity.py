# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for the output types execute_cell persists in JUPYTER_SERVER file mode.

The kernel reports each output's nbformat type. These tests pin that the type
survives the write-back to the .ipynb, instead of being re-derived from the
formatted string form.
"""

import nbformat
import pytest

from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool


STREAM_OUTPUT = {
    "output_type": "stream",
    "name": "stdout",
    "text": "hello\n",
}

ERROR_OUTPUT = {
    "output_type": "error",
    "ename": "ZeroDivisionError",
    "evalue": "division by zero",
    "traceback": [
        "Traceback (most recent call last):",
        "ZeroDivisionError: division by zero",
    ],
}

EXECUTE_RESULT_OUTPUT = {
    "output_type": "execute_result",
    "data": {"text/plain": "2"},
    "metadata": {},
    "execution_count": 1,
}

DISPLAY_DATA_OUTPUT = {
    "output_type": "display_data",
    "data": {"image/png": "aGVsbG8="},
    "metadata": {},
}


def _write_notebook(tmp_path, source="print('hello')"):
    notebook = nbformat.v4.new_notebook()
    notebook.cells.append(nbformat.v4.new_code_cell(source=source))
    path = tmp_path / "notebook.ipynb"
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(notebook, f)
    return str(path)


def _read_notebook(path):
    with open(path, "r", encoding="utf-8") as f:
        return nbformat.read(f, as_version=4)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_output,expected_type",
    [
        (STREAM_OUTPUT, "stream"),
        (ERROR_OUTPUT, "error"),
        (EXECUTE_RESULT_OUTPUT, "execute_result"),
        (DISPLAY_DATA_OUTPUT, "display_data"),
    ],
    ids=["stream", "error", "execute_result", "display_data"],
)
async def test_output_type_round_trips(tmp_path, raw_output, expected_type):
    """Every output the kernel reports keeps its type on disk."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(path, 0, [], raw_outputs=[raw_output])

    notebook = _read_notebook(path)
    assert notebook.cells[0].outputs[0]["output_type"] == expected_type
    nbformat.validate(notebook)


@pytest.mark.asyncio
async def test_error_output_keeps_its_fields(tmp_path):
    """An error keeps ename, evalue and traceback, so error scrapers can read it."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(path, 0, [], raw_outputs=[ERROR_OUTPUT])

    output = _read_notebook(path).cells[0].outputs[0]
    assert output["output_type"] == "error"
    assert output["ename"] == "ZeroDivisionError"
    assert output["evalue"] == "division by zero"
    assert output["traceback"] == ERROR_OUTPUT["traceback"]


@pytest.mark.asyncio
async def test_stream_output_keeps_name_and_text(tmp_path):
    """stderr stays distinguishable from stdout."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()
    stderr_output = {"output_type": "stream", "name": "stderr", "text": "oops\n"}

    await tool._write_outputs_to_cell(path, 0, [], raw_outputs=[stderr_output])

    output = _read_notebook(path).cells[0].outputs[0]
    assert output["output_type"] == "stream"
    assert output["name"] == "stderr"
    assert output["text"] == "oops\n"


@pytest.mark.asyncio
async def test_execute_result_execution_count_matches_cell(tmp_path):
    """The execute_result reports the same execution count as the cell."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(path, 0, [], raw_outputs=[EXECUTE_RESULT_OUTPUT])

    cell = _read_notebook(path).cells[0]
    assert cell.execution_count == 1
    assert cell.outputs[0]["execution_count"] == cell.execution_count


@pytest.mark.asyncio
async def test_multiple_outputs_keep_their_order_and_types(tmp_path):
    """A cell that prints, then raises, keeps both outputs distinct."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(
        path, 0, [], raw_outputs=[STREAM_OUTPUT, ERROR_OUTPUT]
    )

    outputs = _read_notebook(path).cells[0].outputs
    assert [o["output_type"] for o in outputs] == ["stream", "error"]


@pytest.mark.asyncio
async def test_transient_field_is_stripped(tmp_path):
    """'transient' is kernel protocol, not nbformat, so it must not be persisted."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()
    with_transient = dict(DISPLAY_DATA_OUTPUT, transient={"display_id": "abc"})

    await tool._write_outputs_to_cell(path, 0, [], raw_outputs=[with_transient])

    notebook = _read_notebook(path)
    assert "transient" not in notebook.cells[0].outputs[0]
    nbformat.validate(notebook)


@pytest.mark.asyncio
async def test_falls_back_to_formatted_strings_without_raw_outputs(tmp_path):
    """Callers with only formatted strings (the timeout path) still write outputs."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(
        path, 0, ["[TIMEOUT ERROR: Execution exceeded 1 seconds]"]
    )

    notebook = _read_notebook(path)
    outputs = notebook.cells[0].outputs
    assert len(outputs) == 1
    assert outputs[0]["output_type"] == "stream"
    nbformat.validate(notebook)


@pytest.mark.asyncio
async def test_error_string_still_persisted_without_raw_outputs(tmp_path):
    """An [ERROR: ...] fallback string keeps being written as a stream output."""
    path = _write_notebook(tmp_path)
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(path, 0, ["[ERROR: RuntimeError: boom]"])

    notebook = _read_notebook(path)
    outputs = notebook.cells[0].outputs
    assert len(outputs) == 1
    assert outputs[0]["output_type"] == "stream"
    assert outputs[0]["text"] == "[ERROR: RuntimeError: boom]"
    nbformat.validate(notebook)


@pytest.mark.asyncio
async def test_no_output_sentinel_is_not_persisted(tmp_path):
    """A cell that produced nothing must persist no output.

    In JUPYTER_SERVER file mode an output-less cell (``x = 1``, an import, a
    def) makes execute_via_execution_stack return the ``[No output generated]``
    sentinel with raw_outputs empty. That sentinel is meant only for the tool
    response, so it must not be written back as a fabricated execute_result.
    """
    path = _write_notebook(tmp_path, source="x = 1")
    tool = ExecuteCellTool()

    await tool._write_outputs_to_cell(
        path, 0, ["[No output generated]"], raw_outputs=[]
    )

    cell = _read_notebook(path).cells[0]
    assert cell.outputs == []
    # The cell was executed, so it still carries an execution count.
    assert cell.execution_count == 1
    nbformat.validate(_read_notebook(path))
