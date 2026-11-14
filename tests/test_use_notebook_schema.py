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


def test_use_notebook_schema_allows_omitting_optional_notebook_name() -> None:
    """use_notebook requires notebook_path and treats notebook_name as optional."""
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["use_notebook"].input_schema

    assert "notebook_path" in schema.get("required", [])
    assert "notebook_name" not in schema.get("required", [])
    validate({"notebook_path": "repro.ipynb"}, schema)


def test_use_notebook_by_name_schema_requires_notebook_name() -> None:
    """use_notebook_by_name requires notebook_name and does not ask for notebook_path."""
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["use_notebook_by_name"].input_schema

    assert schema.get("required") == ["notebook_name"]
    assert "notebook_path" not in schema.get("properties", {})
    validate({"notebook_name": "repro"}, schema)
