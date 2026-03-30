# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the move_cell MCP tool.

This module contains:
- Section A: Unit tests for the pure Python validation logic
  (no server needed, imports directly from the tool module)
- Section B: Integration tests using mcp_client_parametrized
  (tests both MCP_SERVER and JUPYTER_SERVER modes)

All tests are expected to FAIL until the move_cell tool is implemented (TDD).

Launch the tests:
```
# Unit tests only (no server needed):
$ pytest tests/test_move_cell.py::TestMoveCellValidation -v

# Integration tests (requires Jupyter + MCP servers):
$ pytest tests/test_move_cell.py -k "not Test" -v

# All tests:
$ pytest tests/test_move_cell.py -v
```
"""

import pytest

from .test_common import MCPClient, timeout_wrapper


###############################################################################
# Section A — Unit Tests (no server needed)
###############################################################################

try:
    from jupyter_mcp_server.tools.move_cell_tool import MoveCellTool
except ImportError:
    MoveCellTool = None

_skip_unit = pytest.mark.skipif(
    MoveCellTool is None,
    reason="move_cell_tool not yet implemented",
)


@_skip_unit
class TestMoveCellValidation:
    """Tests for _validate_move(): input validation before moving cells."""

    def setup_method(self):
        self.tool = MoveCellTool()

    @pytest.mark.parametrize("source, target, total", [
        (-1, 0, 5),   # negative source
        (5, 0, 5),    # source == total_cells
        (0, -1, 5),   # negative target
        (0, 5, 5),    # target == total_cells
        (0, 1, 1),    # single-cell notebook, invalid target
        (0, 0, 0),    # empty notebook
    ])
    def test_invalid_indices_raise_error(self, source, target, total):
        """Out-of-range or invalid indices must be rejected."""
        with pytest.raises((ValueError, IndexError)):
            self.tool._validate_move(source_index=source, target_index=target, total_cells=total)

    @pytest.mark.parametrize("source, target, total", [
        (2, 2, 5),    # same position (no-op)
        (0, 3, 5),    # forward move
        (3, 0, 5),    # backward move
        (4, 0, 5),    # last valid index backward
        (0, 4, 5),    # first index to last valid position
        (0, 0, 1),    # single-cell notebook, same index
    ])
    def test_valid_indices_pass(self, source, target, total):
        """Valid indices should not raise."""
        self.tool._validate_move(source_index=source, target_index=target, total_cells=total)


@_skip_unit
class TestMoveCellApply:
    """Tests for _apply_move(): the actual cell reordering logic."""

    def setup_method(self):
        self.tool = MoveCellTool()

    @pytest.mark.parametrize("source, target, expected", [
        # forward moves
        (0, 3, ["B", "C", "D", "A", "E"]),
        (0, 4, ["B", "C", "D", "E", "A"]),
        (1, 3, ["A", "C", "D", "B", "E"]),
        # backward moves
        (3, 0, ["D", "A", "B", "C", "E"]),
        (4, 0, ["E", "A", "B", "C", "D"]),
        (3, 1, ["A", "D", "B", "C", "E"]),
        # adjacent swaps
        (1, 2, ["A", "C", "B", "D", "E"]),
        (2, 1, ["A", "C", "B", "D", "E"]),
        # no-op
        (2, 2, ["A", "B", "C", "D", "E"]),
    ])
    def test_reorder(self, source, target, expected):
        """Verify the resulting order after a move."""
        cells = ["A", "B", "C", "D", "E"]
        result = self.tool._apply_move(cells, source, target)
        assert result == expected

    def test_single_cell_noop(self):
        """Single-element list: move 0→0 returns the same list."""
        assert self.tool._apply_move(["X"], 0, 0) == ["X"]

    def test_two_cells_swap(self):
        """Two-element list: move 0→1 swaps them."""
        assert self.tool._apply_move(["A", "B"], 0, 1) == ["B", "A"]

    def test_does_not_mutate_input(self):
        """_apply_move should not modify the input list."""
        cells = ["A", "B", "C"]
        self.tool._apply_move(cells, 0, 2)
        assert cells == ["A", "B", "C"]


###############################################################################
# Section B — Integration Tests (MCP_SERVER and JUPYTER_SERVER modes)
###############################################################################


async def _setup_cells(client: MCPClient, labels: list[str], cell_type: str = "code"):
    """Insert cells with the given labels at indices 1..N."""
    for i, label in enumerate(labels):
        await client.insert_cell(i + 1, cell_type, label)


async def _read_cell_header(client: MCPClient, index: int) -> tuple[str, str]:
    """Read a cell and parse its type and source from the structured header.

    Returns:
        (cell_type, source) extracted from the read_cell response.
        cell_type is one of "code", "markdown", "raw".
    """
    cell = await client.read_cell(index)
    parts = cell["result"]
    # Header format: "=====Cell N | type: <type> | execution count: ...====="
    header = str(parts[0])
    cell_type = header.split("type: ")[1].split(" |")[0].strip()
    source = str(parts[1]) if len(parts) > 1 else ""
    return cell_type, source


async def _assert_cell_order(client: MCPClient, expected: list[str]):
    """Verify that cells at indices 1..N have exactly the expected sources in order."""
    for i, label in enumerate(expected):
        _, source = await _read_cell_header(client, i + 1)
        assert source == label, f"Expected '{label}' at index {i + 1}, got: '{source}'"


async def _cleanup_cells(client: MCPClient, count: int):
    """Delete cells at indices count..1 (reverse order)."""
    await client.delete_cell(list(range(count, 0, -1)))


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_basic_forward(mcp_client_parametrized: MCPClient):
    """Move a cell forward (from index 1 to index 3) and verify order."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["A", "B", "C", "D"])

        result = await c.move_cell(1, 3)
        assert result is not None
        assert "move" in result["result"].lower()

        await _assert_cell_order(c, ["B", "C", "A", "D"])
        await _cleanup_cells(c, 4)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_basic_backward(mcp_client_parametrized: MCPClient):
    """Move a cell backward (from index 3 to index 1) and verify order."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["A", "B", "C", "D"])

        result = await c.move_cell(3, 1)
        assert result is not None

        await _assert_cell_order(c, ["C", "A", "B", "D"])
        await _cleanup_cells(c, 4)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_same_position_noop(mcp_client_parametrized: MCPClient):
    """Move a cell to its own position — should be a no-op."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["stay_put", "also_stay"])

        result = await c.move_cell(1, 1)
        assert result is not None

        await _assert_cell_order(c, ["stay_put", "also_stay"])
        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_first_to_last(mcp_client_parametrized: MCPClient):
    """Move the first cell to the last position."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["first", "second", "third"])

        await c.move_cell(1, 3)

        await _assert_cell_order(c, ["second", "third", "first"])
        await _cleanup_cells(c, 3)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_last_to_first(mcp_client_parametrized: MCPClient):
    """Move the last cell to the first position."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["first", "second", "third"])

        await c.move_cell(3, 1)

        await _assert_cell_order(c, ["third", "first", "second"])
        await _cleanup_cells(c, 3)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_preserves_cell_type(mcp_client_parametrized: MCPClient):
    """Moving a markdown cell should preserve its type; code cell stays code."""
    async with mcp_client_parametrized as c:
        await c.insert_cell(1, "markdown", "# Header")
        await c.insert_cell(2, "code", "x = 1")

        await c.move_cell(1, 2)

        cell_type_1, source_1 = await _read_cell_header(c, 1)
        cell_type_2, source_2 = await _read_cell_header(c, 2)

        assert cell_type_1 == "code"
        assert source_1 == "x = 1"
        assert cell_type_2 == "markdown"
        assert source_2 == "# Header"

        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_preserves_source_content(mcp_client_parametrized: MCPClient):
    """Moving a cell should preserve its full multiline source content."""
    async with mcp_client_parametrized as c:
        source = "import numpy as np\n\nx = np.array([1, 2, 3])\nprint(x.sum())"
        await c.insert_cell(1, "code", source)
        await c.insert_cell(2, "code", "placeholder")

        await c.move_cell(1, 2)

        _, moved_source = await _read_cell_header(c, 2)
        assert moved_source == source

        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
@pytest.mark.parametrize("src, tgt", [(1, 2), (2, 1)], ids=["forward", "backward"])
async def test_move_cell_adjacent(mcp_client_parametrized: MCPClient, src, tgt):
    """Move a cell one position (adjacent swap) in either direction."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["cell_A", "cell_B"])

        result = await c.move_cell(src, tgt)
        assert result is not None

        await _assert_cell_order(c, ["cell_B", "cell_A"])
        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
@pytest.mark.parametrize("bad_src, bad_tgt", [(9999, 0), (0, 9999)],
                         ids=["source_oob", "target_oob"])
async def test_move_cell_error_out_of_range(mcp_client_parametrized: MCPClient, bad_src, bad_tgt):
    """Out-of-range source or target index should return None (error)."""
    async with mcp_client_parametrized as c:
        await c.insert_cell(1, "code", "only_cell")

        result = await c.move_cell(bad_src, bad_tgt)
        assert result is None

        await _cleanup_cells(c, 1)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_preserves_outputs(mcp_client_parametrized: MCPClient):
    """Moving a cell that has been executed should preserve its outputs."""
    async with mcp_client_parametrized as c:
        await c.insert_cell(1, "code", "print('hello')")
        await c.insert_cell(2, "code", "placeholder")

        # Execute cell 1 so it has outputs
        exec_result = await c.execute_cell(1)
        assert exec_result is not None

        # Move the executed cell from index 1 to index 2
        await c.move_cell(1, 2)

        # Read cell at new position with outputs
        cell = await c.read_cell(2, include_outputs=True)
        cell_text = " ".join(str(item) for item in cell["result"]).strip()
        assert "hello" in cell_text

        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_then_execute(mcp_client_parametrized: MCPClient):
    """Move a code cell, then execute it at its new position."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["print(42)", "placeholder"])

        await c.move_cell(1, 2)

        exec_result = await c.execute_cell(2)
        assert exec_result is not None
        output_text = " ".join(str(item) for item in exec_result["result"]).strip()
        assert output_text == "42"

        await _cleanup_cells(c, 2)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_move_cell_multiple_sequential_moves(mcp_client_parametrized: MCPClient):
    """Perform multiple sequential moves and verify final order."""
    async with mcp_client_parametrized as c:
        await _setup_cells(c, ["A", "B", "C"])

        # A, B, C → move A to 3 → B, C, A → move C (idx 2) to 1 → C, B, A
        await c.move_cell(1, 3)
        await c.move_cell(2, 1)

        await _assert_cell_order(c, ["C", "B", "A"])
        await _cleanup_cells(c, 3)
