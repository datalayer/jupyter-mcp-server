#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the Size column of list_files in JUPYTER_SERVER mode.

The Jupyter contents API types a ``.ipynb`` as ``"notebook"`` rather than
``"file"`` and reports a byte size for it, exactly as it does for a regular
file. ``_list_files_local`` used to read the size only when the type was
``"file"``, so every notebook came back with an empty Size while MCP_SERVER
mode, which reads any size the model carries, reported the real one. The two
transport modes have to answer the same question the same way.

These tests drive the real ``LargeFileManager`` against a temporary root, not a
stand-in, so the type/size pairing is the server's own rather than a fixture's
assumption.
"""

import pytest
from jupyter_server.services.contents.largefilemanager import LargeFileManager

from jupyter_mcp_server.tools.list_files_tool import _list_files_local, format_size

_NOTEBOOK = b'{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
_CSV = b"a,b\n" + b"1,2\n" * 64


@pytest.fixture
def content_root(tmp_path):
    (tmp_path / "analysis.ipynb").write_bytes(_NOTEBOOK)
    (tmp_path / "data.csv").write_bytes(_CSV)
    (tmp_path / "sub").mkdir()
    return tmp_path


@pytest.mark.asyncio
async def test_list_files_local_reports_notebook_size(content_root):
    """A notebook reports its size, the same as any other file."""
    files = {
        f["path"]: f
        for f in await _list_files_local(LargeFileManager(root_dir=str(content_root)), path="", max_depth=0)
    }

    assert files["analysis.ipynb"]["type"] == "notebook"
    assert files["analysis.ipynb"]["size"] == format_size(len(_NOTEBOOK))


@pytest.mark.asyncio
async def test_list_files_local_still_reports_plain_file_size(content_root):
    """A regular file is unaffected by the change."""
    files = {
        f["path"]: f
        for f in await _list_files_local(LargeFileManager(root_dir=str(content_root)), path="", max_depth=0)
    }

    assert files["data.csv"]["type"] == "file"
    assert files["data.csv"]["size"] == format_size(len(_CSV))


@pytest.mark.asyncio
async def test_list_files_local_leaves_directory_size_blank(content_root):
    """A directory carries no size in the contents model and must stay blank."""
    files = {
        f["path"]: f
        for f in await _list_files_local(LargeFileManager(root_dir=str(content_root)), path="", max_depth=0)
    }

    assert files["sub"]["type"] == "directory"
    assert files["sub"]["size"] == ""
