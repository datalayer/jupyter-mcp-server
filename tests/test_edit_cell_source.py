# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the edit_cell_source MCP tool.

This module contains:
- Section A: Unit tests for the pure Python validation/apply logic
  (no server needed, imports directly from the tool module)
- Section B: Integration tests using mcp_client_parametrized
  (tests both MCP_SERVER and JUPYTER_SERVER modes)

All tests are expected to FAIL until the edit_cell_source tool is implemented (TDD).

Launch the tests:
```
# Unit tests only (no server needed):
$ pytest tests/test_edit_cell_source.py::TestEditCellSourceValidation -v
$ pytest tests/test_edit_cell_source.py::TestEditCellSourceApply -v

# Integration tests (requires Jupyter + MCP servers):
$ pytest tests/test_edit_cell_source.py -k "not Test" -v

# All tests:
$ pytest tests/test_edit_cell_source.py -v
```
"""

import logging

import pytest

from .test_common import MCPClient, timeout_wrapper


###############################################################################
# Section A — Unit Tests (no server needed)
###############################################################################

try:
    from jupyter_mcp_server.tools.edit_cell_source_tool import EditCellSourceTool
except ImportError:
    EditCellSourceTool = None

_skip_unit = pytest.mark.skipif(
    EditCellSourceTool is None,
    reason="edit_cell_source_tool not yet implemented",
)


@_skip_unit
class TestEditCellSourceValidation:
    """Tests for _validate_edit(): input validation before applying edits."""

    def setup_method(self):
        self.tool = EditCellSourceTool()

    def test_empty_old_string_raises_error(self):
        """Empty old_string must be rejected."""
        with pytest.raises(ValueError, match="must not be empty"):
            self.tool._validate_edit("some source", "", "replacement", False)

    def test_old_string_not_found_raises_error(self):
        """old_string that doesn't exist in source must be rejected."""
        with pytest.raises(ValueError, match="not found"):
            self.tool._validate_edit("hello world", "xyz", "abc", False)

    def test_old_string_ambiguous_without_replace_all(self):
        """Multiple matches without replace_all=True must be rejected."""
        with pytest.raises(ValueError, match="not unique"):
            self.tool._validate_edit("aaa", "a", "b", False)

    def test_old_string_ambiguous_with_replace_all_passes(self):
        """Multiple matches with replace_all=True should pass validation."""
        # Should not raise
        self.tool._validate_edit("aaa", "a", "b", True)

    def test_old_string_unique_without_replace_all_passes(self):
        """Exactly one match without replace_all should pass validation."""
        # Should not raise
        self.tool._validate_edit("hello world", "hello", "hi", False)


@_skip_unit
class TestEditCellSourceApply:
    """Tests for _apply_edit(): the actual string replacement logic."""

    def setup_method(self):
        self.tool = EditCellSourceTool()

    # --- Basic replacement ---

    def test_single_replacement_happy_path(self):
        """Single unique match is replaced correctly."""
        result = self.tool._apply_edit("hello world", "hello", "hi", False)
        assert result == "hi world"

    def test_replace_all_with_multiple_occurrences(self):
        """replace_all=True replaces every occurrence."""
        result = self.tool._apply_edit("aXbXc", "X", "Y", True)
        assert result == "aYbYc"

    def test_replace_all_with_single_occurrence(self):
        """replace_all=True with only one occurrence still works."""
        result = self.tool._apply_edit("hello world", "hello", "hi", True)
        assert result == "hi world"

    def test_old_string_equals_new_string_noop(self):
        """old_string == new_string produces identical output (no-op)."""
        source = "unchanged content"
        result = self.tool._apply_edit(source, "unchanged", "unchanged", False)
        assert result == source

    def test_replace_with_empty_string_deletion(self):
        """Replacing with empty string deletes the match."""
        result = self.tool._apply_edit("hello world", " world", "", False)
        assert result == "hello"

    # --- Multiline ---

    def test_multiline_old_string(self):
        """old_string spanning multiple lines is matched and replaced."""
        source = "line1\nline2\nline3"
        result = self.tool._apply_edit(source, "line1\nline2", "replaced", False)
        assert result == "replaced\nline3"

    def test_multiline_new_string_expansion(self):
        """Replacing single line with multiline expands correctly."""
        source = "before\noriginal\nafter"
        result = self.tool._apply_edit(source, "original", "new1\nnew2\nnew3", False)
        assert result == "before\nnew1\nnew2\nnew3\nafter"

    # --- Special characters ---

    def test_special_characters_quotes_backslashes(self):
        """Quotes and backslashes are treated as literal characters."""
        source = 'path = "C:\\\\Users\\\\test"'
        old = '"C:\\\\Users\\\\test"'
        new = '"D:\\\\Data\\\\output"'
        result = self.tool._apply_edit(source, old, new, False)
        assert result == 'path = "D:\\\\Data\\\\output"'

    def test_regex_metacharacters_literal_match(self):
        """Regex metacharacters (.*+?[]{}|^$) are matched literally, not as regex."""
        source = "value = data[0] + (x * y)"
        old = "[0] + (x * y)"
        new = "[1] + (a * b)"
        result = self.tool._apply_edit(source, old, new, False)
        assert result == "value = data[1] + (a * b)"

    # --- Unicode ---

    def test_unicode_content(self):
        """Unicode strings (accents, emoji, etc.) are handled correctly."""
        source = "café résumé naïve"
        result = self.tool._apply_edit(source, "résumé", "resume", False)
        assert result == "café resume naïve"

    def test_cjk_characters(self):
        """CJK characters are matched and replaced correctly."""
        source = "日本語テスト"
        result = self.tool._apply_edit(source, "テスト", "試験", False)
        assert result == "日本語試験"

    # --- Whitespace sensitivity ---

    def test_tab_sensitive_matching(self):
        """Tabs are distinct from spaces — tab-based old_string must match exactly."""
        source = "\tindented line"
        result = self.tool._apply_edit(source, "\tindented", "\t\tdouble_indented", False)
        assert result == "\t\tdouble_indented line"

    def test_trailing_space_sensitivity(self):
        """Trailing spaces are significant and must match exactly."""
        source = "word   "  # three trailing spaces
        result = self.tool._apply_edit(source, "word   ", "word", False)
        assert result == "word"

    def test_indentation_sensitivity_wrong_indent_not_found(self):
        """Wrong indentation should not match — spaces matter."""
        source = "    four_spaces"
        with pytest.raises(ValueError, match="not found"):
            self.tool._validate_edit(source, "  two_spaces", "x", False)

    # --- Boundary positions ---

    def test_old_string_at_beginning_of_source(self):
        """Match at the very start of the source string."""
        result = self.tool._apply_edit("START rest of text", "START", "BEGIN", False)
        assert result == "BEGIN rest of text"

    def test_old_string_at_end_of_source(self):
        """Match at the very end of the source string."""
        result = self.tool._apply_edit("rest of text END", "END", "FINISH", False)
        assert result == "rest of text FINISH"

    def test_old_string_is_entire_source(self):
        """old_string matches the entire source — full replacement."""
        result = self.tool._apply_edit("entire content", "entire content", "new content", False)
        assert result == "new content"

    # --- Edge cases ---

    def test_very_long_source(self):
        """Handles large sources (10K+ lines) without issues."""
        lines = [f"line {i}: some content here" for i in range(10_001)]
        source = "\n".join(lines)
        # Replace a line in the middle
        old = "line 5000: some content here"
        new = "line 5000: MODIFIED content here"
        result = self.tool._apply_edit(source, old, new, False)
        assert "MODIFIED" in result
        # Verify surrounding lines are untouched
        assert "line 4999: some content here" in result
        assert "line 5001: some content here" in result

    def test_overlapping_patterns_with_replace_all(self):
        """replace_all with patterns that could overlap uses non-overlapping replacement."""
        # Python str.replace is non-overlapping left-to-right, so "aaa" with "a"->"ab"
        # gives "ababab", not infinite
        result = self.tool._apply_edit("aaa", "a", "ab", True)
        assert result == "ababab"


###############################################################################
# Section B — Integration Tests (MCP_SERVER and JUPYTER_SERVER modes)
###############################################################################


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_basic_code_cell(mcp_client_parametrized: MCPClient):
    """Edit a code cell and verify diff is returned."""
    async with mcp_client_parametrized:
        # Insert a code cell
        await mcp_client_parametrized.insert_cell(1, "code", "x = 1\ny = 2\nprint(x + y)")

        # Edit: change x = 1 to x = 10
        result = await mcp_client_parametrized.edit_cell_source(1, "x = 1", "x = 10")
        assert result is not None, "edit_cell_source should return a result"
        assert "diff" in result["result"].lower() or "-" in result["result"]

        # Cleanup
        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_basic_markdown_cell(mcp_client_parametrized: MCPClient):
    """Edit a markdown cell and verify diff is returned."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "markdown", "# Title\nSome **bold** text")

        result = await mcp_client_parametrized.edit_cell_source(1, "# Title", "# New Title")
        assert result is not None, "edit_cell_source should return a result"
        assert "diff" in result["result"].lower() or "-" in result["result"]

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_then_read_verifies_change(mcp_client_parametrized: MCPClient):
    """Edit a cell, then read it back to confirm the change persisted."""
    async with mcp_client_parametrized:
        original = "alpha = 1\nbeta = 2"
        await mcp_client_parametrized.insert_cell(1, "code", original)

        await mcp_client_parametrized.edit_cell_source(1, "alpha = 1", "alpha = 99")

        cell_info = await mcp_client_parametrized.read_cell(1)
        assert cell_info is not None
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "alpha = 99" in cell_text
        assert "beta = 2" in cell_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_then_execute(mcp_client_parametrized: MCPClient):
    """Edit a code cell, execute it, and verify the output reflects the change."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "print('before')")

        await mcp_client_parametrized.edit_cell_source(1, "before", "after")

        exec_result = await mcp_client_parametrized.execute_cell(1)
        assert exec_result is not None
        output_text = " ".join(str(item) for item in exec_result["result"])
        assert "after" in output_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_replace_all(mcp_client_parametrized: MCPClient):
    """replace_all=True replaces all occurrences in the cell."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "a = 1\na = 2\na = 3")

        result = await mcp_client_parametrized.edit_cell_source(1, "a = ", "b = ", replace_all=True)
        assert result is not None

        cell_info = await mcp_client_parametrized.read_cell(1)
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "b = 1" in cell_text
        assert "b = 2" in cell_text
        assert "b = 3" in cell_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_error_cell_index_out_of_range(mcp_client_parametrized: MCPClient):
    """Out-of-range cell_index should return None (error)."""
    async with mcp_client_parametrized:
        result = await mcp_client_parametrized.edit_cell_source(9999, "x", "y")
        assert result is None


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_error_old_string_not_found(mcp_client_parametrized: MCPClient):
    """old_string not present in cell source should return None (error)."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "x = 1")

        result = await mcp_client_parametrized.edit_cell_source(1, "nonexistent_string", "replacement")
        assert result is None

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_error_ambiguous_match(mcp_client_parametrized: MCPClient):
    """Ambiguous match (multiple occurrences without replace_all) should return None (error)."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "x = 1\nx = 2\nx = 3")

        result = await mcp_client_parametrized.edit_cell_source(1, "x = ", "y = ")
        assert result is None

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_preserves_cell_type_and_metadata(mcp_client_parametrized: MCPClient):
    """Editing a cell should not change its type."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "markdown", "# Hello World")

        await mcp_client_parametrized.edit_cell_source(1, "Hello", "Goodbye")

        cell_info = await mcp_client_parametrized.read_cell(1)
        assert cell_info is not None
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "markdown" in cell_text
        assert "Goodbye World" in cell_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_sequential_edits_on_same_cell(mcp_client_parametrized: MCPClient):
    """Three sequential edits on the same cell — verify final state."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "step = 0")

        await mcp_client_parametrized.edit_cell_source(1, "step = 0", "step = 1")
        await mcp_client_parametrized.edit_cell_source(1, "step = 1", "step = 2")
        await mcp_client_parametrized.edit_cell_source(1, "step = 2", "step = 3")

        cell_info = await mcp_client_parametrized.read_cell(1)
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "step = 3" in cell_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_after_insert_workflow(mcp_client_parametrized: MCPClient):
    """Insert a cell, then edit it — standard workflow."""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.insert_cell(1, "code", "placeholder = True")

        result = await mcp_client_parametrized.edit_cell_source(1, "placeholder = True", "real_code = 42")
        assert result is not None

        cell_info = await mcp_client_parametrized.read_cell(1)
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "real_code = 42" in cell_text

        await mcp_client_parametrized.delete_cell([1])


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_edit_cell_source_noop_same_old_and_new(mcp_client_parametrized: MCPClient):
    """old_string == new_string is a no-op — cell should remain unchanged."""
    async with mcp_client_parametrized:
        source = "unchanged = True"
        await mcp_client_parametrized.insert_cell(1, "code", source)

        result = await mcp_client_parametrized.edit_cell_source(1, "unchanged = True", "unchanged = True")
        assert result is not None

        cell_info = await mcp_client_parametrized.read_cell(1)
        cell_text = " ".join(str(item) for item in cell_info["result"])
        assert "unchanged = True" in cell_text

        await mcp_client_parametrized.delete_cell([1])
