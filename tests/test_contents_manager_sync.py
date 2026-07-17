#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for synchronous ContentsManager support.

jupyter-server supports both synchronous and asynchronous ContentsManager
implementations. Several widely used managers are synchronous -- notably
``jupytext.TextFileContentsManager``, which resolves to
``SyncJupytextContentsManager`` -- and their methods return plain values rather
than coroutines. Awaiting such a return value directly raises::

    TypeError: object dict can't be used in 'await' expression

The JUPYTER_SERVER-mode helpers must therefore wrap contents_manager calls in
``ensure_async``, which awaits awaitables and passes plain values through.
"""

import pytest

from jupyter_mcp_server.tools.list_files_tool import _list_files_local
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

_ROOT_MODEL = {
    "name": "",
    "path": "",
    "type": "directory",
    "content": [
        {
            "name": "notebook.ipynb",
            "path": "notebook.ipynb",
            "type": "notebook",
            "size": 1024,
            "last_modified": "2026-01-01T00:00:00Z",
        },
        {
            "name": "data",
            "path": "data",
            "type": "directory",
            "last_modified": "2026-01-01T00:00:00Z",
        },
    ],
}


class SyncContentsManager:
    """Minimal synchronous ContentsManager: ``get`` returns a dict, not a coroutine."""

    def get(self, path, content=True, type=None, format=None):
        if path in ("", "."):
            return dict(_ROOT_MODEL)
        raise FileNotFoundError(path)


class AsyncContentsManager:
    """Minimal asynchronous ContentsManager: ``get`` is a coroutine function."""

    async def get(self, path, content=True, type=None, format=None):
        return SyncContentsManager().get(path, content=content, type=type)


MANAGERS = [
    pytest.param(SyncContentsManager, id="sync"),
    pytest.param(AsyncContentsManager, id="async"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_list_files_local_supports_sync_and_async_managers(manager_cls):
    """list_files must work regardless of the ContentsManager flavour."""
    files = await _list_files_local(manager_cls(), path="", max_depth=0)
    assert [f["path"] for f in files] == ["notebook.ipynb", "data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_check_path_local_supports_sync_and_async_managers(manager_cls):
    """use_notebook must find an existing notebook with either flavour."""
    ok, error = await UseNotebookTool()._check_path_local(
        manager_cls(), "notebook.ipynb", "connect"
    )
    assert ok, error
