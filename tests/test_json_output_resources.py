# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""JSON output values must survive resource reads without becoming text fragments."""

import json
import uuid
from pathlib import Path

import nbformat
import pytest

from jupyter_mcp_server import resources

from .test_common import MCPClient, timeout_wrapper
from .test_resources_both_modes import _read

CONTENT_DIR = Path("dev/content")


@pytest.mark.parametrize("mimetype", ["application/json", "application/vnd.example+json"])
@pytest.mark.parametrize(
    "value", [{"ok": True, "missing": None}, [1, 2], ["a", "b"], "hello", True, None, 42]
)
def test_json_data_roundtrips_as_json(mimetype, value):
    output = {
        "output_type": "display_data",
        "data": {"text/plain": "fallback", mimetype: value},
    }

    assert resources.output_mime(output) == mimetype
    assert json.loads(resources.output_text(output)) == value


def test_multiline_rich_text_is_still_joined():
    output = {"output_type": "display_data", "data": {"text/markdown": ["# Title\n", "body"]}}

    assert resources.output_text(output) == "# Title\nbody"


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_json_output_resources_preserve_their_values(mcp_client_parametrized: MCPClient):
    notebook_file = f"json_resources_{uuid.uuid4().hex[:8]}.ipynb"
    on_disk = CONTENT_DIR / notebook_file
    values = [{"ok": True, "missing": None}, [1, 2]]
    mimetypes = ["application/json", "application/vnd.example+json"]
    cell = nbformat.v4.new_code_cell(
        outputs=[
            nbformat.v4.new_output("display_data", data={"text/plain": "fallback", mimetype: value})
            for mimetype, value in zip(mimetypes, values, strict=True)
        ]
    )
    notebook = nbformat.v4.new_notebook(cells=[cell])
    try:
        nbformat.write(notebook, on_disk)
        async with mcp_client_parametrized as client:
            await client.use_notebook("json_resources", notebook_file)
            document = json.loads(await _read(client, f"notebook://json_resources/cells/{cell.id}"))
            assert [output["mimeType"] for output in document["outputs"]] == mimetypes
            for output, value in zip(document["outputs"], values, strict=True):
                assert json.loads(await _read(client, output["uri"])) == value
    finally:
        on_disk.unlink(missing_ok=True)
