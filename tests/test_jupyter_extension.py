#!/usr/bin/env python
# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Quick test to verify the extension loads and handlers are registered.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_import():
    """Test that all imports work."""
    try:
        from jupyter_mcp_server.jupyter_extension import extension
        from jupyter_mcp_server.jupyter_extension import handlers
        from jupyter_mcp_server.jupyter_extension import context
        logger.info("✅ All imports successful")
        return True
    except Exception as e:
        logger.error(f"❌ Import failed: {e}", exc_info=True)
        return False

def test_extension_points():
    """Test extension discovery."""
    try:
        from jupyter_mcp_server import _jupyter_server_extension_points
        points = _jupyter_server_extension_points()
        logger.info(f"✅ Extension points: {points}")
        return len(points) > 0
    except Exception as e:
        logger.error(f"❌ Extension points failed: {e}", exc_info=True)
        return False

def test_handler_creation():
    """Test that handlers can be instantiated."""
    try:
        from jupyter_mcp_server.jupyter_extension.handlers import MCPSSEHandler, MCPHealthHandler, MCPToolsListHandler
        logger.info(f"✅ Handlers available: MCPSSEHandler, MCPHealthHandler, MCPToolsListHandler")
        return True
    except Exception as e:
        logger.error(f"❌ Handler creation failed: {e}", exc_info=True)
        return False

def test_dynamic_tool_list():
    """Test that tool list is returned dynamically from registry."""
    try:
        import asyncio
        from jupyter_mcp_server.server import get_registered_tools
        
        tools = asyncio.run(get_registered_tools())
        logger.info(f"✅ Found {len(tools)} tools dynamically")
        
        # Verify we have the expected tools
        tool_names = [t['name'] for t in tools]
        expected_tools = ['use_notebook', 'list_notebook', 'read_all_cells', 'execute_cell_simple_timeout']
        
        for expected in expected_tools:
            if expected not in tool_names:
                logger.error(f"❌ Expected tool '{expected}' not found in: {tool_names}")
                return False
        
        # Verify each tool has required fields
        for tool in tools:
            if not all(key in tool for key in ['name', 'description', 'parameters']):
                logger.error(f"❌ Tool missing required fields: {tool.get('name', 'unknown')}")
                return False
        
        logger.info(f"✅ All tools have required metadata")
        return True
    except Exception as e:
        logger.error(f"❌ Dynamic tool list failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    tests = [
        ("Imports", test_import),
        ("Extension Points", test_extension_points),
        ("Handler Creation", test_handler_creation),
        ("Dynamic Tool List", test_dynamic_tool_list),
    ]
    
    results = []
    for name, test_func in tests:
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing: {name}")
        logger.info(f"{'='*60}")
        result = test_func()
        results.append((name, result))
    
    logger.info(f"\n{'='*60}")
    logger.info("Test Summary")
    logger.info(f"{'='*60}")
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")
    
    all_passed = all(result for _, result in results)
    sys.exit(0 if all_passed else 1)
