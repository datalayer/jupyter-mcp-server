#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Inserting a cell must not invalidate an older notebook.

Cell ids arrived in nbformat 4.5, and `nbformat.v4.new_code_cell` and its
siblings always attach one. `insert_cell` builds cells that way — which is what
#339 asked for, because the create path was writing 4.5 notebooks whose cells
had no id — and then writes the cell into whatever notebook it was given.

Reading with `as_version=4` converts the major version only, so a notebook that
declares 4.2 or 4.4 is still 4.2 or 4.4 when it is written back, now carrying a
field its own schema forbids. `nbformat.write` logs that the notebook is invalid
and writes it anyway, so the tool reports success over a file that
`nbformat.validate` rejects and that a strict reader can refuse.

Launch the tests:
```
$ pytest tests/test_insert_cell_nbformat_version.py -v
```
"""

import asyncio

import nbformat
import pytest

from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool


def _notebook(minor: int) -> nbformat.NotebookNode:
    """A one cell notebook declaring nbformat 4.`minor`."""
    notebook = nbformat.v4.new_notebook()
    notebook.nbformat_minor = minor
    notebook.cells = [nbformat.v4.new_markdown_cell(source="hello")]
    if minor < 5:
        for cell in notebook.cells:
            cell.pop("id", None)
    return notebook


@pytest.fixture
def notebook_path(tmp_path):
    def _write(minor: int) -> str:
        path = tmp_path / f"nb_4_{minor}.ipynb"
        nbformat.write(_notebook(minor), str(path))
        return str(path)

    return _write


@pytest.mark.parametrize("minor", [2, 4])
@pytest.mark.parametrize("cell_type", ["code", "markdown", "raw"])
def test_insert_leaves_a_pre_4_5_notebook_valid(notebook_path, minor, cell_type):
    path = notebook_path(minor)

    asyncio.run(InsertCellTool()._insert_cell_file(path, 1, cell_type, "print(1)"))

    written = nbformat.read(path, as_version=4)
    nbformat.validate(written)  # raises if the notebook is not valid
    assert written.nbformat_minor == minor, "the notebook's own version must not change"
    assert all("id" not in cell for cell in written.cells)


@pytest.mark.parametrize("cell_type", ["code", "markdown", "raw"])
def test_insert_still_gives_a_4_5_notebook_an_id(notebook_path, cell_type):
    path = notebook_path(5)

    asyncio.run(InsertCellTool()._insert_cell_file(path, 1, cell_type, "print(1)"))

    written = nbformat.read(path, as_version=4)
    nbformat.validate(written)
    assert written.nbformat_minor == 5
    assert all(cell.get("id") for cell in written.cells)
