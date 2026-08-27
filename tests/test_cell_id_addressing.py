#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Addressing a cell by id, against a real notebook.

`test_cell_ids.py` proves the resolver. This proves what the resolver is for,
end to end: an agent reads a cell, somebody inserts a cell above it, and the
agent's edit still lands on the cell it read.

By index that edit hits the wrong cell — silently, because an index stays
valid, it just stops meaning the same cell. That is the accident this
prevents, and it is the test that would fail if the feature were reverted.

Cell ids arrived in nbformat 4.5. A notebook written before that has none, and
the server correctly reports none rather than inventing one — an id generated
on read differs on the next read, so it would name a cell only until somebody
looked again. These tests skip in that case and say so, rather than passing
quietly and proving nothing.

```
$ pytest tests/test_cell_id_addressing.py -v
```
"""

import pytest

from .test_common import MCPClient

CELL_ID_META = "io.jupyter-mcp/cell_id"


async def _read(client: MCPClient, index: int):
    """A `read_cell` call, with the whole result rather than just its text."""
    return await client._session.call_tool("read_cell", arguments={"cell_index": index})


def _reported_id(result) -> str:
    return (result.meta or {}).get(CELL_ID_META, "")


def _text_of(result) -> str:
    return "\n".join(
        block.text for block in (result.content or []) if getattr(block, "text", None)
    )


async def _id_or_skip(client: MCPClient, index: int) -> str:
    cell_id = _reported_id(await _read(client, index))
    if not cell_id:
        pytest.skip(
            "this notebook predates nbformat 4.5, so its cells have no ids to address"
        )
    return cell_id


@pytest.mark.asyncio
async def test_reading_a_cell_says_which_cell_it_was(mcp_client_parametrized: MCPClient):
    """An agent can only address a cell by id if it has been given one, so
    handing the id back is what makes the whole feature reachable."""
    async with mcp_client_parametrized as client:
        await _id_or_skip(client, 0)


@pytest.mark.asyncio
async def test_two_cells_report_two_different_ids(mcp_client_parametrized: MCPClient):
    """An id that were the same for every cell would address nothing."""
    async with mcp_client_parametrized as client:
        first = await _id_or_skip(client, 0)
        second = _reported_id(await _read(client, 1))
        assert second and second != first


@pytest.mark.asyncio
async def test_an_edit_by_id_survives_an_insert_above_it(
    mcp_client_parametrized: MCPClient,
):
    """The accident, and the fix.

    Put a cell at the top, learn its id, then push it down by inserting above
    it. Addressed by the index the agent first saw, the edit would land on
    the newcomer; addressed by id, it lands on the cell the agent read.
    """
    async with mcp_client_parametrized as client:
        await client.insert_cell(0, "markdown", "TARGET")
        assert "TARGET" in _text_of(await _read(client, 0))
        target_id = await _id_or_skip(client, 0)

        # Somebody else adds a cell above it: every index below has moved.
        await client.insert_cell(0, "markdown", "INTERLOPER")
        assert "INTERLOPER" in _text_of(await _read(client, 0))

        result = await client._session.call_tool(
            "overwrite_cell_source",
            arguments={"cell_id": target_id, "cell_source": "EDITED"},
        )
        assert _reported_id(result) == target_id

        assert "EDITED" in _text_of(await _read(client, 1))
        assert "INTERLOPER" in _text_of(await _read(client, 0))

        await client.delete_cell([0, 1])


@pytest.mark.asyncio
async def test_an_id_that_is_gone_is_refused_rather_than_guessed(
    mcp_client_parametrized: MCPClient,
):
    """Falling back to the index that came with it would edit an arbitrary
    cell in the name of being forgiving."""
    async with mcp_client_parametrized as client:
        before = _text_of(await _read(client, 0))
        answer = await client._call_tool_safe(
            "overwrite_cell_source",
            {"cell_index": 0, "cell_id": "no-such-cell-id", "cell_source": "SHOULD NOT LAND"},
        )
        assert answer is None, "an unknown cell id was not refused"
        assert _text_of(await _read(client, 0)) == before
