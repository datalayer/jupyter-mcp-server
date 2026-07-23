# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for read_cell and read_notebook tools' YDoc-first read path.

Regression tests for #297: in JUPYTER_SERVER mode, read_cell/read_notebook
unconditionally read the notebook file from disk, so a write that already
landed in the live YDoc (via overwrite_cell_source or any other mutation
tool, which all check the YDoc first through get_notebook_model()) is
invisible to a read until the autosave debounce flushes it to disk.

Follows this repo's own pattern (see test_clear_cell_output.py) of driving
the tool's execute() directly with a NotebookModel-shaped fake, rather than
requiring a live collaborative session.

Launch the tests:
```
$ pytest tests/test_read_tools_ydoc.py -v
```
"""

import nbformat
import pytest

import jupyter_mcp_server.tools.read_cell_tool as read_cell_tool_module
import jupyter_mcp_server.tools.read_notebook_tool as read_notebook_tool_module
from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool
from jupyter_mcp_server.tools.read_notebook_tool import ReadNotebookTool


def _write_notebook(path, sources):
    nb = nbformat.v4.new_notebook()
    for source in sources:
        nb.cells.append(nbformat.v4.new_code_cell(source=source))
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)


class _FakeNotebookModel:
    """Minimal stand-in for jupyter_nbmodel_client.NotebookModel: only the
    as_dict() surface the read tools consume."""

    def __init__(self, sources):
        self._sources = sources

    def as_dict(self):
        return {
            "cells": [
                {
                    "cell_type": "code",
                    "source": source,
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                }
                for source in self._sources
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }


class _NoContentsManager:
    """contents_manager stand-in that fails the test if it is ever called,
    proving the YDoc branch short-circuits the file read entirely."""

    async def get(self, *args, **kwargs):
        raise AssertionError(
            "contents_manager.get() must not run when the live YDoc has an open room"
        )


class _FileContentsManager:
    """contents_manager stand-in that reads the real file under tmp_path,
    for the no-YDoc-room fallback path."""

    def __init__(self, root):
        self._root = root

    async def get(self, path, content=True, type="notebook"):
        with open(str(self._root / path), encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)
        return {"content": nb}


def _fake_get_notebook_model(nb_model):
    async def _fake(serverapp, notebook_path):
        return nb_model

    return _fake


class _FakeServerApp:
    def __init__(self, root_dir):
        self.root_dir = root_dir


@pytest.fixture(autouse=True)
def _reset_context():
    yield
    get_server_context().reset()


class TestReadCellToolYDocFirst:
    def setup_method(self):
        self.tool = ReadCellTool()

    @pytest.mark.asyncio
    async def test_reads_live_ydoc_over_stale_file(self, tmp_path, monkeypatch):
        """A write already in the YDoc must be visible, not the stale file."""
        _write_notebook(str(tmp_path / "nb.ipynb"), ["OLD_SOURCE"])
        get_server_context().update(
            context_type="JUPYTER_SERVER", serverapp=_FakeServerApp(str(tmp_path))
        )
        monkeypatch.setattr(
            read_cell_tool_module, "get_current_notebook_context", lambda nm: ("nb.ipynb", None)
        )
        monkeypatch.setattr(
            read_cell_tool_module,
            "get_notebook_model",
            _fake_get_notebook_model(_FakeNotebookModel(["NEW_SOURCE"])),
        )

        result = await self.tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=_NoContentsManager(),
            notebook_manager=None,
            cell_index=0,
        )

        joined = "\n".join(result)
        assert "NEW_SOURCE" in joined
        assert "OLD_SOURCE" not in joined

    @pytest.mark.asyncio
    async def test_falls_back_to_file_when_no_ydoc_room(self, tmp_path, monkeypatch):
        """No collaborative session open -> unchanged fallback to the on-disk file."""
        _write_notebook(str(tmp_path / "nb.ipynb"), ["FILE_SOURCE"])
        get_server_context().update(
            context_type="JUPYTER_SERVER", serverapp=_FakeServerApp(str(tmp_path))
        )
        monkeypatch.setattr(
            read_cell_tool_module, "get_current_notebook_context", lambda nm: ("nb.ipynb", None)
        )
        monkeypatch.setattr(
            read_cell_tool_module, "get_notebook_model", _fake_get_notebook_model(None)
        )

        result = await self.tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=_FileContentsManager(tmp_path),
            notebook_manager=None,
            cell_index=0,
        )

        assert "FILE_SOURCE" in "\n".join(result)


class _FakeNotebookManager:
    """Minimal stand-in covering only what read_notebook needs: membership
    and path lookup for one fixed notebook name."""

    def __init__(self, name, path):
        self._name = name
        self._path = path

    def __contains__(self, name):
        return name == self._name

    def get_notebook_path(self, name):
        return self._path


class TestReadNotebookToolYDocFirst:
    def setup_method(self):
        self.tool = ReadNotebookTool()

    @pytest.mark.asyncio
    async def test_reads_live_ydoc_over_stale_file(self, tmp_path, monkeypatch):
        """Same staleness regression as read_cell, for the whole-notebook read."""
        _write_notebook(str(tmp_path / "nb.ipynb"), ["OLD_SOURCE"])
        get_server_context().update(
            context_type="JUPYTER_SERVER", serverapp=_FakeServerApp(str(tmp_path))
        )
        monkeypatch.setattr(
            read_notebook_tool_module,
            "get_notebook_model",
            _fake_get_notebook_model(_FakeNotebookModel(["NEW_SOURCE"])),
        )

        result = await self.tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=_NoContentsManager(),
            notebook_manager=_FakeNotebookManager("nb", "nb.ipynb"),
            notebook_name="nb",
            limit=100,
        )

        assert "NEW_SOURCE" in result
        assert "OLD_SOURCE" not in result

    @pytest.mark.asyncio
    async def test_falls_back_to_file_when_no_ydoc_room(self, tmp_path, monkeypatch):
        """No collaborative session open -> unchanged fallback to the on-disk file."""
        _write_notebook(str(tmp_path / "nb.ipynb"), ["FILE_SOURCE"])
        get_server_context().update(
            context_type="JUPYTER_SERVER", serverapp=_FakeServerApp(str(tmp_path))
        )
        monkeypatch.setattr(
            read_notebook_tool_module, "get_notebook_model", _fake_get_notebook_model(None)
        )

        result = await self.tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=_FileContentsManager(tmp_path),
            notebook_manager=_FakeNotebookManager("nb", "nb.ipynb"),
            notebook_name="nb",
            limit=100,
        )

        assert "FILE_SOURCE" in result
