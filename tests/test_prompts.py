"""
Test for MCP Prompts Feature
"""

import os

import pytest

from .test_common import MCPClient, timeout_wrapper

# Now, prompt feature is only available in MCP_SERVER mode.
pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_MCP_SERVER", "false").lower() == "true",
    reason="Prompt feature is only available in MCP_SERVER mode now."
)


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_jupyter_cite(mcp_client_parametrized: MCPClient):
    """Test jupyter cite prompt feature"""
    async with mcp_client_parametrized:
        await mcp_client_parametrized.use_notebook("new", "new.ipynb")
        await mcp_client_parametrized.use_notebook("notebook", "notebook.ipynb")
        # Test prompt injection
        response = await mcp_client_parametrized.jupyter_cite(prompt="test prompt", cell_indices="0")
        assert "# Matplotlib Examples" in response[0], "Cell 0 should contain Matplotlib Examples"
        assert "test prompt" in response[0], "Prompt should be injected"
        # Test mixed cell_indices
        response = await mcp_client_parametrized.jupyter_cite(prompt="", cell_indices="0-2,4")
        assert "USER Cite cells [0, 1, 2, 4]" in response[0], "Cell indices should be [0, 1, 2, 4]"
        assert "## 1. Import Required Libraries" in response[0], "Cell 1 should contain Import Required Libraries"
        assert "%matplotlib inline" in response[0], "Cell 2 should contain %matplotlib inline"
        assert "## 2. Basic Line Plot" not in response[0], "Cell 3 should not be cited"
        assert "y = np.sin(x)" in response[0], "Cell 4 should contain y = np.sin(x)"
        # Test cite other notebook
        response = await mcp_client_parametrized.jupyter_cite(prompt="", cell_indices="0", notebook_name="new")
        assert "from notebook new" in response[0], "should cite new notebook"
        assert "# A New Notebook" in response[0], "Cell 0 of new notebook should contain A New Notebook"
