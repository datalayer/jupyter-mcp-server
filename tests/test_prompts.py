# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Test for MCP Prompts Feature
"""

import os

import pytest

from .test_common import MCPClient, timeout_wrapper

# Now, prompt feature is only available in MCP_SERVER mode.
pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_MCP_SERVER", "false").lower() == "true",
    reason="Prompt feature is only available in MCP_SERVER mode now.",
)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_jupyter_cite(mcp_client: MCPClient):
    """Test jupyter cite prompt feature"""
    async with mcp_client:
        await mcp_client.use_notebook("new", "new.ipynb")
        await mcp_client.use_notebook("notebook", "notebook.ipynb")
        # Test prompt injection
        response = await mcp_client.jupyter_cite(prompt="test prompt", cell_indices="0")
        assert "# Matplotlib Examples" in response[0], "Cell 0 should contain Matplotlib Examples"
        assert "test prompt" in response[0], "Prompt should be injected"
        # Test mixed cell_indices
        response = await mcp_client.jupyter_cite(prompt="", cell_indices="0-2,4")
        assert "USER Cite cells [0, 1, 2, 4]" in response[0], "Cell indices should be [0, 1, 2, 4]"
        assert "=====Cell 0" in response[0], "Cell 0 should be cited"
        assert "=====Cell 1" in response[0], "Cell 1 should be cited"
        assert "=====Cell 2" in response[0], "Cell 2 should be cited"
        assert "=====Cell 4" in response[0], "Cell 4 should be cited"
        assert "=====Cell 3" not in response[0], "Cell 3 should not be cited"
        assert "=====End of Cited Cells=====" in response[0], "Cited block should be terminated"
        # Test cite other notebook
        response = await mcp_client.jupyter_cite(prompt="", cell_indices="0", notebook_name="new")
        assert "from notebook new" in response[0], "should cite new notebook"
        assert (
            "# A New Notebook" in response[0]
        ), "Cell 0 of new notebook should contain A New Notebook"
