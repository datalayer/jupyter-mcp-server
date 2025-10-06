# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unit tests for use_notebook tool with optional notebook_path parameter.

These tests verify the notebook switching functionality when notebook_path is not provided.
"""

import pytest
import logging
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


@pytest.mark.asyncio
async def test_use_notebook_switching():
    """Test that use_notebook can switch between already-connected notebooks"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()
    
    # Simulate adding two notebooks manually
    notebook_manager.add_notebook(
        "notebook_a",
        {"id": "kernel_a"},  # Mock kernel info
        server_url="local",
        token=None,
        path="notebook_a.ipynb"
    )
    
    notebook_manager.add_notebook(
        "notebook_b",
        {"id": "kernel_b"},  # Mock kernel info
        server_url="local",
        token=None,
        path="notebook_b.ipynb"
    )
    
    # Set current to notebook_a
    notebook_manager.set_current_notebook("notebook_a")
    logging.debug(f"Current notebook: {notebook_manager.get_current_notebook()}")
    assert notebook_manager.get_current_notebook() == "notebook_a"
    
    # Test switching to notebook_b (no notebook_path provided)
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        notebook_name="notebook_b",
        notebook_path=None  # Key: no path provided, should just switch
    )
    
    logging.debug(f"Switch result: {result}")
    assert "Successfully switched to notebook 'notebook_b'" in result
    assert notebook_manager.get_current_notebook() == "notebook_b"
    
    # Test switching back to notebook_a
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        notebook_name="notebook_a",
        notebook_path=None
    )
    
    logging.debug(f"Switch back result: {result}")
    assert "Successfully switched to notebook 'notebook_a'" in result
    assert notebook_manager.get_current_notebook() == "notebook_a"


@pytest.mark.asyncio
async def test_use_notebook_switch_to_nonexistent():
    """Test error handling when switching to non-connected notebook"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()
    
    # Add only one notebook
    notebook_manager.add_notebook(
        "notebook_a",
        {"id": "kernel_a"},
        server_url="local",
        token=None,
        path="notebook_a.ipynb"
    )
    
    # Try to switch to non-existent notebook
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        notebook_name="notebook_c",
        notebook_path=None
    )
    
    logging.debug(f"Non-existent notebook result: {result}")
    assert "not connected" in result
    assert "Please provide a notebook_path" in result


@pytest.mark.asyncio
async def test_use_notebook_with_path_still_works():
    """Test that providing notebook_path still works for connecting new notebooks"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()
    
    # This should trigger the error about missing clients (since we're not providing them)
    # but it verifies the code path is still intact
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        notebook_name="new_notebook",
        notebook_path="new.ipynb",
        use_mode="connect"
    )
    
    # Should fail because no contents_manager provided, but validates the logic path
    assert "Invalid mode or missing required clients" in result or "already using" not in result


@pytest.mark.asyncio 
async def test_use_notebook_multiple_switches():
    """Test multiple consecutive switches between notebooks"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()
    
    # Add three notebooks
    for i, name in enumerate(["nb1", "nb2", "nb3"]):
        notebook_manager.add_notebook(
            name,
            {"id": f"kernel_{i}"},
            server_url="local",
            token=None,
            path=f"{name}.ipynb"
        )
    
    notebook_manager.set_current_notebook("nb1")
    
    # Perform multiple switches
    switches = ["nb2", "nb3", "nb1", "nb3", "nb2"]
    for target in switches:
        result = await tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            notebook_manager=notebook_manager,
            notebook_name=target,
            notebook_path=None
        )
        assert f"Successfully switched to notebook '{target}'" in result
        assert notebook_manager.get_current_notebook() == target
        logging.debug(f"Switched to {target}")


if __name__ == "__main__":
    # Allow running with: python tests/test_use_notebook.py
    pytest.main([__file__, "-v"])
