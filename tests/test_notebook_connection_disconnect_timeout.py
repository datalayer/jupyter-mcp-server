# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for NotebookConnection.__aexit__ hanging forever (#160).

Under PYTHONDEVMODE=1, NbModelClient.__aexit__ can get stuck cancelling its
background sender task and never return. Since NotebookConnection.__aexit__
awaited it with no timeout of its own, every tool call that opens a notebook
connection (insert_execute_code_cell, execute_cell, ...) hung forever with no
response ever reaching the MCP client. These tests stand in a fake NbModelClient
whose __aexit__ never completes, so the behavior is exercised deterministically
without needing PYTHONDEVMODE or a live CRDT race.
"""

import asyncio

import pytest

from jupyter_mcp_server import notebook_manager as notebook_manager_module
from jupyter_mcp_server.notebook_manager import NotebookConnection


class HangingNotebook:
    """Stands in for an NbModelClient whose disconnect never completes."""

    def __init__(self):
        self.aexit_called = False

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.aexit_called = True
        await asyncio.Event().wait()  # never set: simulates the stuck disconnect


class FastNotebook:
    """Stands in for the normal case: disconnect completes right away."""

    def __init__(self):
        self.aexit_called = False

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.aexit_called = True


def _connection_wrapping(fake_notebook):
    conn = NotebookConnection(notebook_info={})
    conn._notebook = fake_notebook
    return conn


@pytest.mark.asyncio
async def test_aexit_does_not_hang_when_disconnect_is_stuck(monkeypatch):
    """A stuck NbModelClient.__aexit__ must not hang the connection's own
    __aexit__ forever; it should give up after DISCONNECT_TIMEOUT.

    raising=False: on unpatched code there is no DISCONNECT_TIMEOUT to patch,
    __aexit__ awaits the stuck disconnect with no bound of its own, and this
    test's own outer wait_for is what then fails with asyncio.TimeoutError,
    demonstrating the actual hang rather than an unrelated AttributeError.
    """
    monkeypatch.setattr(notebook_manager_module, "DISCONNECT_TIMEOUT", 0.05, raising=False)
    fake_notebook = HangingNotebook()
    conn = _connection_wrapping(fake_notebook)

    await asyncio.wait_for(conn.__aexit__(None, None, None), timeout=2)

    assert fake_notebook.aexit_called


@pytest.mark.asyncio
async def test_aexit_still_completes_normally_when_disconnect_is_fast(monkeypatch):
    """The timeout must not interfere with the ordinary fast-disconnect path."""
    monkeypatch.setattr(notebook_manager_module, "DISCONNECT_TIMEOUT", 0.05, raising=False)
    fake_notebook = FastNotebook()
    conn = _connection_wrapping(fake_notebook)

    await asyncio.wait_for(conn.__aexit__(None, None, None), timeout=2)

    assert fake_notebook.aexit_called


@pytest.mark.asyncio
async def test_aexit_logs_a_warning_when_disconnect_times_out(monkeypatch, caplog):
    monkeypatch.setattr(notebook_manager_module, "DISCONNECT_TIMEOUT", 0.05, raising=False)
    conn = _connection_wrapping(HangingNotebook())

    with caplog.at_level("WARNING", logger=notebook_manager_module.__name__):
        await asyncio.wait_for(conn.__aexit__(None, None, None), timeout=2)

    assert any("disconnect" in record.message.lower() for record in caplog.records)
