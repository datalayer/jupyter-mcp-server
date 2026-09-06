# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""An overlapping second match is still ambiguous for a single-cell edit."""

import json
import uuid
from pathlib import Path

import nbformat
import pytest
from mcp.shared.exceptions import MCPError

from jupyter_mcp_server.tools.edit_cell_source_tool import EditCellSourceTool


@pytest.mark.parametrize(
    "source, old_string",
    [
        ("ababa", "aba"),
        ("aaaaa", "aaa"),
        ("# step\n# step\n# step\n", "# step\n# step\n"),
        ("日本日本日", "日本日"),
    ],
)
@pytest.mark.asyncio
async def test_overlapping_edit_leaves_file_untouched(tmp_path, source, old_string):
    path = tmp_path / "overlap.ipynb"
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)])
    nbformat.write(notebook, path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="not unique"):
        await EditCellSourceTool()._edit_cell_file(str(path), 0, old_string, "X", False)

    assert path.read_bytes() == before


@pytest.mark.parametrize("replace_all, expected", [(False, "X"), (True, "Xba")])
def test_unique_match_and_explicit_replace_all_keep_working(replace_all, expected):
    source = "ababa" if replace_all else "aba"
    edited, _ = EditCellSourceTool()._edit_source(source, "aba", "X", replace_all)
    assert edited == expected


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_overlapping_edit_is_refused_in_both_modes(mcp_client_parametrized):
    name = f"overlap_{uuid.uuid4().hex}"
    path = Path("dev/content") / f"{name}.ipynb"
    source = "# step\n# step\n# step\n"
    old_string = "# step\n# step\n"
    nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)]), path)
    try:
        async with mcp_client_parametrized as client:
            await client.use_notebook(name, path.name)

            async def read_source():
                result = await client._session.read_resource(f"notebook://{name}")
                notebook = json.loads("".join(block.text for block in result.contents))
                return notebook["cells"][0]["source"]

            try:
                assert await read_source() == source
                try:
                    result = await client._session.call_tool(
                        "edit_cell_source",
                        arguments={
                            "cell_index": 0,
                            "notebook_name": name,
                            "old_string": old_string,
                            "new_string": "# replacement\n",
                        },
                    )
                except MCPError as error:
                    # The extension reports tool failures as protocol errors.
                    text = str(error)
                else:
                    assert result.is_error
                    text = "\n".join(
                        block.text for block in result.content if hasattr(block, "text")
                    )
                assert "not unique" in text, text
                assert await read_source() == source

                result = await client._session.call_tool(
                    "edit_cell_source",
                    arguments={
                        "cell_index": 0,
                        "notebook_name": name,
                        "old_string": old_string,
                        "new_string": "# replacement\n",
                        "replace_all": True,
                    },
                )
                assert not result.is_error
                assert await read_source() == "# replacement\n# step\n"
            finally:
                await client.unuse_notebook(name)
    finally:
        path.unlink(missing_ok=True)
