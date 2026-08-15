# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`execute_cell` runs on the selected sandbox, like `execute_code`.

Selecting a sandbox reroutes `execute_code`. Before this, it did not reroute
`execute_cell`, which went on waiting for a notebook-bound Jupyter kernel — and
since a kernel is only attached on first execution, that was a kernel waiting
on the very call waiting on it. The tool never returned and nothing said why.

The second test here is the one that matters most: the sandbox must receive the
cell's *source*. An earlier attempt passed the output of `read_cell`, which is
lines formatted for a person — headers, outputs, truncation — so the sandbox
would have executed prose, or, when the shape did not match, an empty string:
silently running nothing and reporting success.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_the_sandbox_is_offered_the_call():
    from jupyter_mcp_server import server

    with (
        patch.object(server, "_cell_source_for_sandbox", AsyncMock(return_value="1 + 1")),
        patch.object(
            server.extension_manager,
            "intercept_execute_code",
            AsyncMock(return_value=["2"]),
        ) as intercept,
    ):
        fn = getattr(server.execute_cell, "fn", server.execute_cell)
        result = await fn(cell_index=0)

    assert result == ["2"]
    intercept.assert_awaited_once()


@pytest.mark.asyncio
async def test_it_is_the_cell_source_that_is_sent():
    """Not a rendering of the cell — the code itself."""
    from jupyter_mcp_server import server

    with (
        patch.object(
            server, "_cell_source_for_sandbox", AsyncMock(return_value="print('hi')")
        ),
        patch.object(
            server.extension_manager,
            "intercept_execute_code",
            AsyncMock(return_value=["hi"]),
        ) as intercept,
    ):
        fn = getattr(server.execute_cell, "fn", server.execute_cell)
        await fn(cell_index=0)

    sent = intercept.await_args.args[0]
    assert sent == "print('hi')"
    # The formatted forms that must never reach a sandbox.
    assert "=====Cell" not in sent
    assert sent != ""


@pytest.mark.asyncio
async def test_without_a_sandbox_the_kernel_path_is_untouched():
    """`intercept_execute_code` answers None when none is selected.

    The ordinary path must then run exactly as before — this is what keeps a
    plain Jupyter deployment working.
    """
    from jupyter_mcp_server import server

    with (
        patch.object(server, "_cell_source_for_sandbox", AsyncMock(return_value="1 + 1")),
        patch.object(
            server.extension_manager,
            "intercept_execute_code",
            AsyncMock(return_value=None),
        ),
        patch.object(
            server, "safe_notebook_operation", AsyncMock(return_value=["kernel ran it"])
        ) as ordinary,
    ):
        fn = getattr(server.execute_cell, "fn", server.execute_cell)
        result = await fn(cell_index=0)

    assert result == ["kernel ran it"]
    ordinary.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unreadable_cell_falls_through_rather_than_sending_nothing():
    """A cell that cannot be read must not become an empty execution.

    Returning "" would be truthy enough to reach the sandbox and would run
    nothing at all, reporting success — worse than the hang this replaced.
    """
    from jupyter_mcp_server import server

    with (
        patch.object(server, "_cell_source_for_sandbox", AsyncMock(return_value=None)),
        patch.object(
            server.extension_manager, "intercept_execute_code", AsyncMock()
        ) as intercept,
        patch.object(
            server, "safe_notebook_operation", AsyncMock(return_value=["kernel ran it"])
        ),
    ):
        fn = getattr(server.execute_cell, "fn", server.execute_cell)
        await fn(cell_index=0)

    intercept.assert_not_awaited()
