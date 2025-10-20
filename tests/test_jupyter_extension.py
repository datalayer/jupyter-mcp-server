# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Integration tests for Jupyter MCP Server in JUPYTER_SERVER mode (extension).

This test file validates the server when running as a Jupyter Server extension
with direct access to serverapp resources (contents_manager, kernel_manager).

Key differences from MCP_SERVER mode:
- Uses YDoc collaborative editing when notebooks are open
- Local file operations without HTTP roundtrip

The tests connect to the extension's HTTP endpoints (not the standalone MCP server).

Launch the tests:
```
$ pytest tests/test_jupyter_extension.py -v
```
"""

import logging
from http import HTTPStatus

import pytest
import requests

from .conftest import JUPYTER_TOKEN


###############################################################################
# Unit Tests - Extension Components
###############################################################################

def test_import():
    """Test that all extension imports work."""
    from jupyter_mcp_server.jupyter_extension import extension
    from jupyter_mcp_server.jupyter_extension import handlers
    from jupyter_mcp_server.jupyter_extension import context
    logging.info("✅ All imports successful")
    assert True


def test_extension_points():
    """Test extension discovery."""
    from jupyter_mcp_server import _jupyter_server_extension_points
    points = _jupyter_server_extension_points()
    logging.info(f"Extension points: {points}")
    assert len(points) > 0
    assert "jupyter_mcp_server" in points[0]["module"]


def test_handler_creation():
    """Test that handlers can be instantiated."""
    from jupyter_mcp_server.jupyter_extension.handlers import (
        MCPSSEHandler, 
        MCPHealthHandler, 
        MCPToolsListHandler
    )
    logging.info("✅ Handlers available")
    assert MCPSSEHandler is not None
    assert MCPHealthHandler is not None
    assert MCPToolsListHandler is not None


###############################################################################
# Integration Tests - Extension Running in Jupyter
###############################################################################

def test_extension_health(jupyter_server_with_extension):
    """Test that Jupyter server with MCP extension is healthy"""
    logging.info(f"Testing Jupyter+MCP extension health ({jupyter_server_with_extension})")
    
    # Test Jupyter API is accessible
    response = requests.get(
        f"{jupyter_server_with_extension}/api/status",
        headers={"Authorization": f"token {JUPYTER_TOKEN}"},
    )
    assert response.status_code == HTTPStatus.OK
    logging.info("✅ Jupyter API is accessible")


def test_mode_comparison_documentation(jupyter_server_with_extension, jupyter_server):
    """
    Document the differences between the two server modes for future reference.
    
    This test serves as living documentation of the architecture.
    """
    logging.info("\n" + "="*80)
    logging.info("SERVER MODE COMPARISON")
    logging.info("="*80)
    
    logging.info("\nMCP_SERVER Mode (Standalone):")
    logging.info(f"  - URL: {jupyter_server}")
    logging.info("  - Started via: python -m jupyter_mcp_server --transport streamable-http")
    logging.info("  - Tools use: JupyterServerClient + KernelClient (HTTP)")
    logging.info("  - File operations: HTTP API (contents API)")
    logging.info("  - Cell operations: WebSocket messages")
    logging.info("  - Execute IPython: WebSocket to kernel")
    logging.info("  - Tests: test_mcp_server.py")
    
    logging.info("\nJUPYTER_SERVER Mode (Extension):")
    logging.info(f"  - URL: {jupyter_server_with_extension}")
    logging.info("  - Started via: jupyter lab --ServerApp.jpserver_extensions")
    logging.info("  - Tools use: Direct Python APIs (contents_manager, kernel_manager)")
    logging.info("  - File operations: Direct nbformat + YDoc collaborative")
    logging.info("  - Cell operations: YDoc when available, nbformat fallback")
    logging.info("  - Execute IPython: Direct kernel_manager.get_kernel() + ZMQ")
    logging.info("  - Tests: test_jupyter_extension.py (this file)")
    
    logging.info("\nKey Benefits of JUPYTER_SERVER Mode:")
    logging.info("  ✓ Real-time collaborative editing via YDoc")
    logging.info("  ✓ Zero-latency local operations")
    logging.info("  ✓ Direct ZMQ access to kernels")
    logging.info("  ✓ Automatic sync with JupyterLab UI")
    
    logging.info("\nKey Benefits of MCP_SERVER Mode:")
    logging.info("  ✓ Works with remote Jupyter servers")
    logging.info("  ✓ No Jupyter extension installation required")
    logging.info("  ✓ Can proxy to multiple Jupyter instances")
    logging.info("  ✓ Standard MCP protocol compatibility")
    
    logging.info("="*80 + "\n")
    
    # Both servers should be running
    assert jupyter_server is not None
    assert jupyter_server_with_extension is not None
    assert jupyter_server != jupyter_server_with_extension  # Different ports
