# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for the delete_cell MCP tool.

This module contains:
- Section A: Unit tests for the pure Python validation logic
  (no server needed, imports directly from the tool module)
- Section B: File-based tests exercising _delete_cell_file end-to-end on a
  real notebook file written to a tmp_path (no server needed)

Launch the tests:
```
$ pytest tests/test_delete_cell.py -v
```
"""

import nbformat
import pytest

from jupyter_mcp_server.tools.delete_cell_tool import DeleteCellTool


def _write_notebook(path, n_cells):
    """Write an *n_cells*-cell notebook to *path* and return the source list."""
    nb = nbformat.v4.new_notebook()
    sources = [f"cell {i}" for i in range(n_cells)]
    for src in sources:
        nb.cells.append(nbformat.v4.new_code_cell(source=src))
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    return sources


def _read_sources(path):
    with open(path, encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    return [c.source for c in nb.cells]


###############################################################################
# Section A — Unit tests for _validate_indices (no server needed)
###############################################################################


class TestDeleteCellValidation:
    """Tests for _validate_indices(): input validation before deleting cells."""

    def setup_method(self):
        self.tool = DeleteCellTool()

    @pytest.mark.parametrize(
        "indices, total",
        [
            ([-1], 5),  # in-range negative — 0-based tool must not accept it
            ([-100], 5),  # out-of-range negative
            ([0, -1], 5),  # mixed: max()==0 slips past an upper-bound-only check
            ([5], 5),  # index == total_cells
            ([999], 5),  # far out of range
            ([0, 5], 5),  # one valid, one out of range
        ],
    )
    def test_invalid_indices_raise_error(self, indices, total):
        """Out-of-range indices (negative or too large) must be rejected."""
        with pytest.raises((ValueError, IndexError)):
            self.tool._validate_indices(indices, total)

    @pytest.mark.parametrize(
        "indices, total",
        [
            ([0], 5),
            ([4], 5),
            ([0, 2, 4], 5),
            ([0], 1),
        ],
    )
    def test_valid_indices_pass(self, indices, total):
        """In-range 0-based indices should not raise."""
        self.tool._validate_indices(indices, total)


###############################################################################
# Section B — File-based behaviour (no server needed)
###############################################################################


class TestDeleteCellFileNegativeIndices:
    """_delete_cell_file must reject negative indices instead of raising a raw
    IndexError or silently deleting the wrong cell."""

    def setup_method(self):
        self.tool = DeleteCellTool()

    @pytest.mark.asyncio
    async def test_out_of_range_negative_raises_clean_error(self, tmp_path):
        """A far-negative index must yield the clean 'out of range' ValueError,
        not a raw IndexError leaking out of the tool."""
        path = str(tmp_path / "nb.ipynb")
        original = _write_notebook(path, 5)

        with pytest.raises(ValueError, match="out of range"):
            await self.tool._delete_cell_file(path, [-100])

        assert _read_sources(path) == original  # notebook untouched

    @pytest.mark.asyncio
    async def test_in_range_negative_does_not_delete_wrong_cell(self, tmp_path):
        """delete_cell is documented as 0-based; -1 must be rejected rather than
        silently deleting the last cell."""
        path = str(tmp_path / "nb.ipynb")
        original = _write_notebook(path, 5)

        with pytest.raises(ValueError, match="out of range"):
            await self.tool._delete_cell_file(path, [-1])

        assert _read_sources(path) == original  # last cell NOT deleted

    @pytest.mark.asyncio
    async def test_mixed_positive_and_negative_rejected(self, tmp_path):
        """[0, -1] must be rejected as a whole; max()==0 previously slipped past
        the upper-bound-only check and deleted cell 0 and the last cell."""
        path = str(tmp_path / "nb.ipynb")
        original = _write_notebook(path, 5)

        with pytest.raises(ValueError, match="out of range"):
            await self.tool._delete_cell_file(path, [0, -1])

        assert _read_sources(path) == original

    @pytest.mark.asyncio
    async def test_valid_delete_still_works(self, tmp_path):
        """Regression guard: a valid 0-based delete keeps working."""
        path = str(tmp_path / "nb.ipynb")
        _write_notebook(path, 5)

        deleted = await self.tool._delete_cell_file(path, [1, 3])

        assert {d["index"] for d in deleted} == {1, 3}
        assert _read_sources(path) == ["cell 0", "cell 2", "cell 4"]
