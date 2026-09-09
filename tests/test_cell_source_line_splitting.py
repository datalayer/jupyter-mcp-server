# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""A cell's source is line-broken by ``\\n`` and by nothing else.

``normalize_cell_source`` used ``str.splitlines``, which also breaks on ``\\v``,
``\\f``, ``\\x1c``, ``\\x1d``, ``\\x1e``, ``\\x85``, ``\\u2028`` and ``\\u2029``.
None of those ends a line in nbformat, so a cell holding one read back with a
line break the notebook does not contain: ``read_cell`` and ``read_notebook``
join the pieces with ``\\n`` on the way out, and ``get_overview`` counted the
pieces and reported hidden lines for a one-line cell.

Launch the tests:
```
$ pytest tests/test_cell_source_line_splitting.py -v
```
"""

from __future__ import annotations

import pytest

from jupyter_mcp_server.models import Cell
from jupyter_mcp_server.utils import normalize_cell_source

NOT_LINE_BREAKS = [
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
]


@pytest.mark.parametrize("character", NOT_LINE_BREAKS)
def test_a_cell_holding_one_stays_one_line(character):
    source = f"text = 'a{character}b'"
    assert normalize_cell_source(source) == [source]
    cell = Cell(index=0, cell_type="code", source=source, id="c1")
    assert cell.get_source("readable") == source
    assert cell.get_overview() == source


@pytest.mark.parametrize("character", NOT_LINE_BREAKS)
def test_it_still_splits_on_the_newlines_around_it(character):
    cell = Cell(index=0, cell_type="code", source=f"x{character}y\nz", id="c1")
    assert cell.get_source("raw") == [f"x{character}y\n", "z"]
    assert cell.get_overview() == f"x{character}y...(1 lines hidden)"


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        ("", []),
        ("one", ["one"]),
        ("one\ntwo", ["one\n", "two"]),
        ("one\ntwo\n", ["one\n", "two"]),
        ("one\n\ntwo", ["one\n", "\n", "two"]),
        ("\n", [""]),
        (["one\n", "two"], ["one\n", "two"]),
    ],
)
def test_newline_splitting_is_unchanged(source, lines):
    assert normalize_cell_source(source) == lines
