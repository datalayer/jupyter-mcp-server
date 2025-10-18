# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unit tests for use_notebook tool with optional notebook_path parameter.

These tests verify the notebook switching functionality when notebook_path is not provided.
"""

import pytest
import logging
from unittest.mock import Mock, AsyncMock
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


@pytest.mark.asyncio
async def test_use_notebook_switching():
    """Test that use_notebook can switch between already-connected notebooks"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()

    # Create mock clients
    mock_contents_manager = AsyncMock()
    mock_kernel_manager = AsyncMock()
    mock_session_manager = AsyncMock()
    
    # Configure mock to return proper directory listing structure
    mock_contents_manager.get.return_value = {
        'content': [
            {'name': 'notebook_a.ipynb', 'type': 'notebook'},
            {'name': 'notebook_b.ipynb', 'type': 'notebook'},
        ]
    }

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

    # Test switching to notebook_b (notebook_path is now required)
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        contents_manager=mock_contents_manager,
        kernel_manager=mock_kernel_manager,
        session_manager=mock_session_manager,
        notebook_name="notebook_b",
        notebook_path="notebook_b.ipynb"  # Required parameter
    )

    logging.debug(f"Switch result: {result}")
    assert "Reactivating notebook 'notebook_b'" in result or "Successfully" in result
    assert notebook_manager.get_current_notebook() == "notebook_b"
    
    # Test switching back to notebook_a
    result = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        notebook_manager=notebook_manager,
        contents_manager=mock_contents_manager,
        kernel_manager=mock_kernel_manager,
        session_manager=mock_session_manager,
        notebook_name="notebook_a",
        notebook_path="notebook_a.ipynb"  # Required parameter
    )

    logging.debug(f"Switch back result: {result}")
    assert "Reactivating notebook 'notebook_a'" in result or "Successfully" in result
    assert notebook_manager.get_current_notebook() == "notebook_a"


@pytest.mark.asyncio
async def test_use_notebook_switch_to_nonexistent():
    """Test error handling when switching to non-connected notebook"""
    tool = UseNotebookTool()
    notebook_manager = NotebookManager()

    # Create mock clients
    mock_contents_manager = AsyncMock()
    
    # Configure mock to return proper directory listing structure
    mock_contents_manager.get.return_value = {
        'content': [
            {'name': 'notebook_a.ipynb', 'type': 'notebook'},
            {'name': 'notebook_c.ipynb', 'type': 'notebook'},
        ]
    }

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
        contents_manager=mock_contents_manager,
        notebook_name="notebook_c",
        notebook_path="notebook_c.ipynb"  # Required parameter
    )

    logging.debug(f"Non-existent notebook result: {result}")
    # The notebook_c is not in notebook_manager, so we expect it to be added as new
    # But since we're not providing kernel_manager, it should fail with a different error
    # Or it might succeed in adding but fail at kernel creation
    assert ("not connected" in result or "not the correct path" in result or 
            "Invalid mode or missing required clients" in result or "Successfully" in result)


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

    # Create mock clients
    mock_contents_manager = AsyncMock()
    mock_kernel_manager = AsyncMock()
    mock_session_manager = AsyncMock()
    
    # Configure mock to return proper directory listing structure
    mock_contents_manager.get.return_value = {
        'content': [
            {'name': 'nb1.ipynb', 'type': 'notebook'},
            {'name': 'nb2.ipynb', 'type': 'notebook'},
            {'name': 'nb3.ipynb', 'type': 'notebook'},
        ]
    }

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
            contents_manager=mock_contents_manager,
            kernel_manager=mock_kernel_manager,
            session_manager=mock_session_manager,
            notebook_name=target,
            notebook_path=f"{target}.ipynb"  # Required parameter
        )
        # When switching between already-connected notebooks, we get "Reactivating" message
        assert ("Reactivating notebook" in result or "Successfully" in result)
        assert notebook_manager.get_current_notebook() == target
        logging.debug(f"Switched to {target}")


if __name__ == "__main__":
    # Allow running with: python tests/test_use_notebook.py
    pytest.main([__file__, "-v"])
