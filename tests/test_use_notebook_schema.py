# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the use_notebook input schema."""

import asyncio

from jsonschema import validate

from jupyter_mcp_server.server import mcp


def test_use_notebook_schema_accepts_an_explicit_null_kernel_id() -> None:
    """Clients may send the advertised default instead of omitting the field."""
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["use_notebook"].input_schema

    validate(
        {
            "notebook_name": "repro",
            "notebook_path": "repro.ipynb",
            "kernel_id": None,
        },
        schema,
    )
