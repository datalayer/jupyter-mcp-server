# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the diff reporting of edit_cell_source and overwrite_cell_source.

Both tools build their report with _generate_diff(). The report has to agree
with what was actually written to the cell: "no changes detected" may only come
back when the two sources are equal.

Launch the tests:
```
$ pytest tests/test_cell_source_diff_reporting.py -v
```
"""

import pytest

from jupyter_mcp_server.tools.edit_cell_source_tool import EditCellSourceTool
from jupyter_mcp_server.tools.overwrite_cell_source_tool import OverwriteCellSourceTool


# Pairs that differ only in characters str.splitlines() consumes, so a
# line-based diff of them is empty even though the sources are not equal.
TERMINATOR_ONLY_CHANGES = [
    pytest.param("a = 1\r\nb = 2", "a = 1\nb = 2", id="crlf-to-lf"),
    pytest.param("a = 1\x0cb = 2", "a = 1\nb = 2", id="form-feed-to-lf"),
    pytest.param("a = 1\x0bb = 2", "a = 1\nb = 2", id="vertical-tab-to-lf"),
    pytest.param("a = 1\u2028b = 2", "a = 1\nb = 2", id="line-separator-to-lf"),
    pytest.param("a = 1\n", "a = 1", id="drop-trailing-newline"),
    pytest.param("a = 1", "a = 1\n", id="add-trailing-newline"),
]


@pytest.fixture(params=[EditCellSourceTool, OverwriteCellSourceTool], ids=["edit", "overwrite"])
def tool(request):
    """Both tools carry the same _generate_diff, so both are held to it."""
    return request.param()


@pytest.mark.parametrize("old_source,new_source", TERMINATOR_ONLY_CHANGES)
def test_terminator_only_change_is_not_reported_as_unchanged(tool, old_source, new_source):
    """A change splitlines() cannot see must not be reported as no change."""
    diff = tool._generate_diff(old_source, new_source)
    assert diff != "no changes detected"
    assert diff.strip()


@pytest.mark.parametrize("old_source,new_source", TERMINATOR_ONLY_CHANGES)
def test_terminator_only_change_shows_both_sources(tool, old_source, new_source):
    """The escaped forms are the only rendering the change is visible in."""
    diff = tool._generate_diff(old_source, new_source)
    assert repr(old_source) in diff
    assert repr(new_source) in diff


def test_equal_sources_report_no_changes(tool):
    """Equal sources are the one case that reports no change."""
    assert tool._generate_diff("a = 1\nb = 2", "a = 1\nb = 2") == "no changes detected"


def test_empty_sources_report_no_changes(tool):
    """Two empty sources are equal, so they report no change."""
    assert tool._generate_diff("", "") == "no changes detected"


def test_ordinary_edit_still_renders_a_unified_diff(tool):
    """The usual line-level rendering is unchanged."""
    diff = tool._generate_diff("a = 1\nb = 2", "a = 2\nb = 2")
    assert diff.startswith("--- ")
    assert "-a = 1" in diff
    assert "+a = 2" in diff
    assert " b = 2" in diff


def test_added_line_still_renders_a_unified_diff(tool):
    """A pure insertion keeps its line-level rendering too."""
    diff = tool._generate_diff("a = 1", "a = 1\nb = 2")
    assert "+b = 2" in diff
    assert diff != "no changes detected"
