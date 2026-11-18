#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the glob pattern filter of list_files.

The filter used ``fnmatch``, which has no notion of a path separator: its
``*`` runs straight across ``/``, and ``**`` is just two of those followed by
a literal ``/`` that a file sitting in the listed directory cannot supply. So
``'**/*.ipynb'``, the tool's own documented example, returned the notebooks in
subdirectories and silently dropped the ones the caller was looking at.

These tests drive ``ListFilesTool.execute`` against the real
``LargeFileManager`` over a temporary root, so the paths being matched are the
ones the contents API really reports.
"""

import pytest
from jupyter_server.services.contents.largefilemanager import LargeFileManager

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.list_files_tool import ListFilesTool

_NOTEBOOK = b'{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'


@pytest.fixture
def content_root(tmp_path):
    (tmp_path / "Untitled.ipynb").write_bytes(_NOTEBOOK)
    (tmp_path / "top.py").write_text("x = 1\n")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "analysis.ipynb").write_bytes(_NOTEBOOK)
    (tmp_path / "work" / "helper.py").write_text("y = 2\n")
    return tmp_path


async def _matching(content_root, pattern):
    listing = await ListFilesTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LargeFileManager(root_dir=str(content_root)),
        path="",
        max_depth=1,
        limit=0,
        pattern=pattern,
    )
    return sorted(
        line.split("\t")[0]
        for line in listing.splitlines()[2:]
        if line.strip() and not line.startswith("Path")
    )


@pytest.mark.asyncio
async def test_double_star_prefix_includes_the_listed_directory(content_root):
    """'**/' covers no directories as well as some."""
    assert await _matching(content_root, "**/*.ipynb") == [
        "Untitled.ipynb",
        "work/analysis.ipynb",
    ]


@pytest.mark.asyncio
async def test_single_star_stays_in_one_directory(content_root):
    """'*' stops at a '/', so a nested match needs '**/'."""
    assert await _matching(content_root, "*.py") == ["top.py"]
    assert await _matching(content_root, "**/*.py") == ["top.py", "work/helper.py"]


@pytest.mark.asyncio
async def test_pattern_can_name_a_directory(content_root):
    """A literal directory prefix still selects what is under it."""
    assert await _matching(content_root, "work/*") == [
        "work/analysis.ipynb",
        "work/helper.py",
    ]


@pytest.mark.asyncio
async def test_an_unmatchable_pattern_reports_no_files(content_root):
    """An empty result is still the no-match message, not an empty table."""
    listing = await ListFilesTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LargeFileManager(root_dir=str(content_root)),
        path="",
        max_depth=1,
        pattern="*.rs",
    )
    assert "No files matching pattern '*.rs'" in listing


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("[^a].py", ["^.py", "a.py"]),
        ("[!].py", ["[!].py"]),
        ("[]].py", ["].py"]),
        ("[!a].py", ["].py", "^.py", "b.py"]),
        ("[a-b].py", ["a.py", "b.py"]),
    ],
)
async def test_bracket_patterns_follow_glob_semantics(tmp_path, pattern, expected):
    for name in ["^.py", "a.py", "b.py", "].py", "[!].py"]:
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")

    assert await _matching(tmp_path, pattern) == expected


@pytest.mark.asyncio
async def test_reversed_range_matches_nothing_instead_of_skipping_filter(content_root):
    listing = await ListFilesTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LargeFileManager(root_dir=str(content_root)),
        max_depth=1,
        limit=0,
        pattern="[z-a].py",
    )

    assert listing == "No files matching pattern '[z-a].py' found in path 'root'"


@pytest.mark.asyncio
async def test_negated_class_does_not_cross_directory_boundary(content_root):
    listing = await ListFilesTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LargeFileManager(root_dir=str(content_root)),
        max_depth=1,
        limit=0,
        pattern="work[!x]helper.py",
    )

    assert "No files matching pattern" in listing
