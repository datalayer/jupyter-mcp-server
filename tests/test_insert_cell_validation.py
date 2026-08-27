import pytest

from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool


def test_insert_cell_rejects_invalid_cell_type_before_insertion():
    tool = InsertCellTool()

    with pytest.raises(ValueError, match="expected 'code' or 'markdown'"):
        tool._validate_cell_insertion_params(0, 0, "raw")


@pytest.mark.parametrize("cell_type", ["code", "markdown"])
def test_insert_cell_accepts_supported_cell_types(cell_type):
    tool = InsertCellTool()

    assert tool._validate_cell_insertion_params(0, 0, cell_type) == 0
