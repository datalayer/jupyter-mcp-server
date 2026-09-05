#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The notebook resources, over the wire, in both deployment modes.

`test_notebook_resources.py` proves `resources.py` — the URI shapes, the MIME
types, what a cell document contains. This proves a client can actually reach
any of it, which is a different question and was answered differently by the
two transports: the standalone server served all three templates while the
JupyterLab extension served none, having advertised `resources` in its
handshake all the same.

Nothing here is mode-specific. Every assertion is about what the protocol
says, so both parametrizations run the same code and a mode that stops
serving a resource fails rather than quietly returning an empty list.

```
$ pytest tests/test_resources_both_modes.py -v
```
"""

import json
import uuid
from pathlib import Path

import pytest
from mcp.shared.exceptions import MCPError

from jupyter_mcp_server import resources

from .test_common import MCPClient, timeout_wrapper

CAPABILITIES_URI = "capabilities://"

#: Where both fixtures root their Jupyter server, per `tests/conftest.py`.
CONTENT_DIR = Path("dev/content")


async def _templates(client: MCPClient) -> dict:
    result = await client._session.list_resource_templates()
    return {template.uri_template: template for template in result.resource_templates}


async def _read(client: MCPClient, uri: str) -> str:
    result = await client._session.read_resource(uri)
    return "".join(block.text for block in result.contents if getattr(block, "text", None))


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_the_three_notebook_templates_are_offered(mcp_client_parametrized: MCPClient):
    """The notebook resources are *templates*: they carry `{name}`, so they
    never appear in `resources/list`. A deployment that answered only
    `resources/list` would look like it served resources and offer none of
    the ones that matter."""
    async with mcp_client_parametrized as client:
        offered = await _templates(client)
        for uri in (
            resources.NOTEBOOK_RESOURCE,
            resources.CELL_RESOURCE,
            resources.OUTPUT_RESOURCE,
        ):
            assert uri in offered, f"{uri} is not offered; got {sorted(offered)}"


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_a_concrete_resource_is_listed(mcp_client_parametrized: MCPClient):
    """`resources/list` is the other half, and it is not empty either."""
    async with mcp_client_parametrized as client:
        listed = await client._session.list_resources()
        assert CAPABILITIES_URI in {str(resource.uri) for resource in listed.resources}


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_a_notebook_reads_back_as_nbformat_json(mcp_client_parametrized: MCPClient):
    """The point of the whole resource: an agent that wants the document asks
    for the document, rather than paying for a tool result that pushes it."""
    async with mcp_client_parametrized as client:
        await client.use_notebook("notebook", "notebook.ipynb")
        document = json.loads(await _read(client, "notebook://notebook"))
        assert document["cells"], "the notebook came back with no cells"
        assert "# Matplotlib Examples" in json.dumps(document["cells"][0]["source"])


@pytest.mark.asyncio
@timeout_wrapper(90)
async def test_a_cell_lists_its_outputs_by_uri_rather_than_inlining_them(
    mcp_client_parametrized: MCPClient,
):
    """A cell that printed a megabyte would otherwise spend a megabyte of the
    client's context every time anybody read the cell.

    On a notebook of its own, because the ones that ship with the repo
    predate nbformat 4.5 and have no cell ids to address.
    """
    notebook_file = f"resources_{uuid.uuid4().hex[:8]}.ipynb"
    on_disk = CONTENT_DIR / notebook_file
    try:
        async with mcp_client_parametrized as client:
            await client.use_notebook("resources", notebook_file, mode="create")
            await client.insert_execute_code_cell(0, "print('an output to read')")

            document = json.loads(await _read(client, "notebook://resources"))
            cell = next((c for c in document["cells"] if c.get("id") and c.get("outputs")), None)
            assert cell is not None, "the created notebook has no cell with an id and an output"

            read_back = json.loads(await _read(client, f"notebook://resources/cells/{cell['id']}"))
            assert read_back["id"] == cell["id"]
            for output in read_back["outputs"]:
                assert output["uri"].startswith(
                    f"notebook://resources/cells/{cell['id']}/outputs/"
                )
                assert "text" not in output and "data" not in output

            assert "an output to read" in await _read(client, read_back["outputs"][0]["uri"])
    finally:
        on_disk.unlink(missing_ok=True)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_a_notebook_nobody_opened_is_refused_rather_than_answered(
    mcp_client_parametrized: MCPClient,
):
    """A protocol error rather than an empty document, which a client cannot
    tell from a notebook that really has no cells."""
    async with mcp_client_parametrized as client:
        await client.use_notebook("notebook", "notebook.ipynb")
        with pytest.raises(MCPError) as refused:
            await _read(client, "notebook://nothing-is-open-under-this-name")
        assert "nothing-is-open-under-this-name" in str(refused.value)
