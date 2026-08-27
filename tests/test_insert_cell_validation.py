# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

import nbformat
import pytest

from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool


def test_insert_cell_rejects_invalid_cell_type_before_insertion():
    tool = InsertCellTool()

    with pytest.raises(ValueError, match="expected 'code', 'markdown', or 'raw'"):
        tool._validate_cell_insertion_params(0, 0, "unsupported")


@pytest.mark.parametrize("cell_type", ["code", "markdown", "raw"])
def test_insert_cell_accepts_supported_cell_types(cell_type):
    tool = InsertCellTool()

    assert tool._validate_cell_insertion_params(0, 0, cell_type) == 0


@pytest.mark.asyncio
async def test_insert_cell_file_supports_raw_cell(tmp_path):
    notebook_path = tmp_path / "test.ipynb"
    notebook = nbformat.v4.new_notebook()
    nbformat.write(notebook, notebook_path)

    result, index, total = await InsertCellTool()._insert_cell_file(
        str(notebook_path), -1, "raw", "raw text"
    )

    assert (index, total) == (0, 1)
    assert result.cells[0].cell_type == "raw"
    assert result.cells[0].source == "raw text"
