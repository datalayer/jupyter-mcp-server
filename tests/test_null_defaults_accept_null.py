#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""A parameter whose advertised default is null must accept null.

Some clients send every optional field, filling in the default the schema
advertises. When a parameter is typed `str` but defaults to `None`, the schema
says `{"type": "string", "default": null}`, and sending that default back
explicitly fails validation (`Input should be a valid string`) even though
omitting it works. See #484 (`use_notebook.kernel_id`).

Launch the tests:
```
$ pytest tests/test_null_defaults_accept_null.py -v
```
"""

import asyncio

import pytest

from jupyter_mcp_server.server import mcp


@pytest.fixture(scope="module")
def tools():
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def _schema(tool):
    return tool.input_schema


def _accepts_null(prop):
    types = prop.get("type")
    if types == "null" or (isinstance(types, list) and "null" in types):
        return True
    return any(_accepts_null(option) for option in prop.get("anyOf", []))


def test_every_null_default_accepts_null(tools):
    rejecting = [
        f"{name}.{param}"
        for name, tool in tools.items()
        for param, prop in _schema(tool).get("properties", {}).items()
        if "default" in prop and prop["default"] is None and not _accepts_null(prop)
    ]
    assert not rejecting, f"default is null but null is rejected: {rejecting}"


def test_use_notebook_kernel_id_accepts_null(tools):
    prop = _schema(tools["use_notebook"])["properties"]["kernel_id"]
    assert prop.get("default") is None
    assert _accepts_null(prop)
