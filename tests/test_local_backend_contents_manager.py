#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for LocalBackend ContentsManager support.

``LocalBackend`` (JUPYTER_SERVER mode) reaches the notebook file system through
``serverapp.contents_manager``. jupyter-server ships both synchronous and
asynchronous ContentsManager implementations, and the default
(``AsyncLargeFileManager``) is asynchronous, so ``get``/``new``/``save`` are
coroutine functions. The backend must therefore await the return value with
``ensure_async``, which awaits awaitables and passes plain values through, so
that both flavours work. This mirrors the tool-side fix in #281.
"""

import copy

import pytest

from jupyter_mcp_server.jupyter_extension.backends.local_backend import LocalBackend

_CELLS = [{"cell_type": "code", "source": ["print(1)"], "metadata": {}, "outputs": []}]

_NOTEBOOK_MODEL = {
    "name": "notebook.ipynb",
    "path": "notebook.ipynb",
    "type": "notebook",
    "content": {"cells": list(_CELLS), "metadata": {}, "nbformat": 4, "nbformat_minor": 5},
}

_ROOT_MODEL = {
    "name": "",
    "path": "",
    "type": "directory",
    "content": [
        {"name": "notebook.ipynb", "path": "notebook.ipynb", "type": "notebook"},
        {"name": "other.ipynb", "path": "other.ipynb", "type": "notebook"},
    ],
}


class SyncContentsManager:
    """Minimal synchronous ContentsManager: methods return plain values."""

    def __init__(self):
        self.saved = []

    def get(self, path, content=True, type=None, format=None):
        if type == "directory" or path in ("", "."):
            return copy.deepcopy(_ROOT_MODEL)
        if path not in ("notebook.ipynb", "other.ipynb"):
            raise FileNotFoundError(path)
        model = copy.deepcopy(_NOTEBOOK_MODEL)
        if not content:
            del model["content"]
        return model

    def new(self, model=None, path=""):
        created = copy.deepcopy(_NOTEBOOK_MODEL)
        created["path"] = path
        return created

    def save(self, model, path):
        self.saved.append((path, model))
        return copy.deepcopy(_NOTEBOOK_MODEL)


class AsyncContentsManager(SyncContentsManager):
    """Minimal asynchronous ContentsManager: methods are coroutine functions."""

    async def get(self, path, content=True, type=None, format=None):
        return SyncContentsManager.get(self, path, content=content, type=type)

    async def new(self, model=None, path=""):
        return SyncContentsManager.new(self, model=model, path=path)

    async def save(self, model, path):
        return SyncContentsManager.save(self, model, path)


class _FakeServerApp:
    def __init__(self, contents_manager):
        self.contents_manager = contents_manager
        self.kernel_manager = None
        self.kernel_spec_manager = None


MANAGERS = [
    pytest.param(SyncContentsManager, id="sync"),
    pytest.param(AsyncContentsManager, id="async"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_get_notebook_content_supports_sync_and_async_managers(manager_cls):
    """get_notebook_content must return the model content with either flavour."""
    backend = LocalBackend(_FakeServerApp(manager_cls()))
    content = await backend.get_notebook_content("notebook.ipynb")
    assert content["cells"] == _CELLS


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_list_notebooks_supports_sync_and_async_managers(manager_cls):
    """list_notebooks must enumerate the directory with either flavour."""
    backend = LocalBackend(_FakeServerApp(manager_cls()))
    notebooks = await backend.list_notebooks()
    assert notebooks == ["notebook.ipynb", "other.ipynb"]


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_notebook_exists_supports_sync_and_async_managers(manager_cls):
    """notebook_exists must report both existence and absence with either flavour."""
    backend = LocalBackend(_FakeServerApp(manager_cls()))
    assert await backend.notebook_exists("notebook.ipynb") is True
    assert await backend.notebook_exists("missing.ipynb") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_create_notebook_supports_sync_and_async_managers(manager_cls):
    """create_notebook must return the created model content with either flavour."""
    backend = LocalBackend(_FakeServerApp(manager_cls()))
    content = await backend.create_notebook("new.ipynb")
    assert content["cells"] == _CELLS


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls", MANAGERS)
async def test_append_cell_saves_with_sync_and_async_managers(manager_cls):
    """append_cell exercises the get+save round trip with either flavour."""
    cm = manager_cls()
    backend = LocalBackend(_FakeServerApp(cm))
    index = await backend.append_cell("notebook.ipynb", "code", "print(2)")
    assert index == len(_CELLS)
    assert cm.saved and cm.saved[-1][0] == "notebook.ipynb"
