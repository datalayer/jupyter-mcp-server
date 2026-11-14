# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`read_notebook` can narrow its listing with `search` and `cell_type` (#169).

The filters keep each cell's index in the notebook, so what an agent finds can
be handed straight to the cell tools, and pagination counts matching cells.
"""

import contextlib
import uuid
from pathlib import Path
from typing import Any, cast

import nbformat
import pytest

from jupyter_mcp_server.models import Cell, Notebook
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.read_notebook_tool import ReadNotebookTool
from tests.test_common import MCPClient, timeout_wrapper

CELLS = [
    {"cell_type": "markdown", "source": "# Load the data"},
    {"cell_type": "code", "source": "import pandas as pd\ndf = pd.read_csv('data.csv')"},
    {"cell_type": "markdown", "source": "## Plot the DATA"},
    {"cell_type": "code", "source": "df.plot()"},
    {"cell_type": "raw", "source": "raw data"},
    {"cell_type": "code", "source": "print('done')"},
]


def _cell(cell_type: str, source: str | list[str]) -> Cell:
    return Cell.model_validate({"cell_type": cell_type, "source": source})


def _notebook() -> Notebook:
    return Notebook.model_validate({"cells": CELLS})


def _indices(brief_table: str) -> list[int]:
    """The Index column of a brief listing."""
    rows = brief_table.strip().splitlines()[1:]
    return [int(row.split("\t")[0]) for row in rows]


class TestCellMatches:
    def test_no_filter_matches_every_cell(self):
        assert all(cell.matches() for cell in _notebook().cells)
        assert all(cell.matches(search="") for cell in _notebook().cells)

    def test_cell_type(self):
        assert _cell("code", "x").matches(cell_type="code")
        assert not _cell("markdown", "x").matches(cell_type="code")

    def test_search_ignores_case(self):
        assert _cell("code", "df.Plot()").matches(search="pLoT")
        assert not _cell("code", "df.plot()").matches(search="hist")

    def test_search_reads_a_source_stored_as_lines(self):
        cell = _cell("code", ["import os\n", "os.getcwd()"])
        assert cell.matches(search="getcwd")
        assert cell.matches(search="os\nos")

    def test_both_filters_must_hold(self):
        cell = _cell("markdown", "plot")
        assert cell.matches(search="plot", cell_type="markdown")
        assert not cell.matches(search="plot", cell_type="code")


class TestFormatOutput:
    def test_unfiltered_listing_is_unchanged(self):
        assert _indices(_notebook().format_output(start_index=1, limit=3)) == [1, 2, 3]

    def test_cell_type_keeps_notebook_indices(self):
        output = _notebook().format_output(cell_type="code")
        assert _indices(output) == [1, 3, 5]

    def test_search_keeps_notebook_indices(self):
        assert _indices(_notebook().format_output(search="data")) == [0, 1, 2, 4]

    def test_filters_combine(self):
        output = _notebook().format_output(search="data", cell_type="markdown")
        assert _indices(output) == [0, 2]

    def test_limit_counts_matching_cells(self):
        assert _indices(_notebook().format_output(cell_type="code", limit=2)) == [1, 3]

    def test_start_index_is_where_the_scan_starts(self):
        output = _notebook().format_output(cell_type="code", start_index=2, limit=1)
        assert _indices(output) == [3]

    def test_detailed_format_shows_the_matching_sources(self):
        output = _notebook().format_output(response_format="detailed", search="plot")
        assert "=====Cell 2 | type: markdown" in output
        assert "=====Cell 3 | type: code" in output
        assert "df.plot()" in output
        assert "print('done')" not in output

    def test_no_match(self):
        output = _notebook().format_output(search="no such text")
        assert output == "No matching cells in the specified range"


class _Manager:
    def __init__(self, cells):
        self._cells = cells

    def __contains__(self, name):
        return name == "nb"

    def list_all_notebooks(self):
        return {"nb": {}}

    @contextlib.asynccontextmanager
    async def get_notebook_connection(self, name):
        assert name == "nb"
        cells = self._cells

        class _Document:
            def as_dict(self):
                return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

        yield _Document()


async def _read(**kwargs: Any) -> str:
    return await ReadNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=cast(Any, _Manager(CELLS)),
        notebook_name="nb",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_header_counts_every_match_not_just_the_page():
    result = await _read(cell_type="code", limit=1)

    assert result.startswith(
        "Notebook nb has 6 cells. Cells matching the filters (cell_type='code'): 3.\n"
    )
    assert _indices(result.split("\n", 2)[2]) == [1]


@pytest.mark.asyncio
async def test_header_names_both_filters():
    result = await _read(search="data", cell_type="markdown")

    assert "Cells matching the filters (search='data', cell_type='markdown'): 2." in result


@pytest.mark.asyncio
async def test_empty_search_is_no_filter():
    result = await _read(search="")

    assert result.startswith("Notebook nb has 6 cells.\n")
    assert "matching the filters" not in result
    assert _indices(result.split("\n", 2)[2]) == [0, 1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_no_match_reports_zero():
    result = await _read(search="no such text")

    assert "Cells matching the filters (search='no such text'): 0." in result
    assert "No matching cells in the specified range" in result


@pytest.mark.asyncio
async def test_start_index_past_the_end_is_still_out_of_range():
    result = await _read(search="data", start_index=6)

    assert result == "Start index 6 is out of range. Notebook has 6 cells."


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_read_notebook_filters_over_mcp(mcp_server_url):
    filename = f"filters-{uuid.uuid4().hex}.ipynb"
    path = Path("dev/content") / filename
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell("# Load the data"),
        nbformat.v4.new_code_cell("import pandas as pd"),
        nbformat.v4.new_markdown_cell("## Plot the data"),
        nbformat.v4.new_code_cell("df.plot()"),
    ]
    nbformat.write(notebook, path)
    try:
        client = MCPClient(mcp_server_url, token="MY_TOKEN")
        async with client:
            await client.use_notebook("filters", filename)
            by_type = await client.read_notebook("filters", cell_type="code")
            by_text = await client.read_notebook("filters", search="PLOT")
            unfiltered = await client.read_notebook("filters")

        assert "Cells matching the filters (cell_type='code'): 2." in by_type
        assert _indices(by_type.split("\n", 2)[2]) == [1, 3]
        assert "Cells matching the filters (search='PLOT'): 2." in by_text
        assert _indices(by_text.split("\n", 2)[2]) == [2, 3]
        assert "matching the filters" not in unfiltered
        assert _indices(unfiltered.split("\n", 2)[2]) == [0, 1, 2, 3]
    finally:
        path.unlink(missing_ok=True)
