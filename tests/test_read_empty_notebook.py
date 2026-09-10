# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

import contextlib
import uuid
from pathlib import Path

import nbformat
import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.read_notebook_tool import ReadNotebookTool
from tests.test_common import MCPClient, timeout_wrapper


class _EmptyNotebook:
    def as_dict(self):
        return {
            "cells": [],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }


class _Manager:
    def __contains__(self, name):
        return name == "empty"

    def list_all_notebooks(self):
        return {"empty": {}}

    @contextlib.asynccontextmanager
    async def get_notebook_connection(self, name):
        assert name == "empty"
        yield _EmptyNotebook()


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", ["brief", "detailed"])
async def test_read_empty_notebook_returns_an_empty_listing(response_format):
    result = await ReadNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=_Manager(),
        notebook_name="empty",
        response_format=response_format,
    )

    assert "Notebook empty has 0 cells." in result
    assert "Notebook is empty" in result
    assert "out of range" not in result


@pytest.mark.asyncio
async def test_read_empty_notebook_still_rejects_a_nonzero_start_index():
    result = await ReadNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=_Manager(),
        notebook_name="empty",
        start_index=1,
    )

    assert result == "Start index 1 is out of range. Notebook has 0 cells."


@pytest.mark.asyncio
@timeout_wrapper(60)
@pytest.mark.parametrize("mcp_server_url", ["jupyter_extension"], indirect=True)
async def test_read_empty_notebook_over_mcp(mcp_server_url):
    filename = f"empty-{uuid.uuid4().hex}.ipynb"
    path = Path("dev/content") / filename
    nbformat.write(nbformat.v4.new_notebook(), path)
    try:
        client = MCPClient(mcp_server_url, token="MY_TOKEN")
        async with client:
            await client.use_notebook("empty", filename)
            result = await client.read_notebook("empty")

        assert "Notebook empty has 0 cells." in result
        assert "Notebook is empty" in result
        assert "out of range" not in result
    finally:
        path.unlink(missing_ok=True)
