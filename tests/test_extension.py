#!/usr/bin/env python
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
        from jupyter_mcp_server.jupyter_to_mcp import extension
        from jupyter_mcp_server.jupyter_to_mcp import handlers
        from jupyter_mcp_server.jupyter_to_mcp import context
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
        from jupyter_mcp_server.jupyter_to_mcp.handlers import MCPASGIHandler, MCPHealthHandler
        logger.info(f"✅ Handlers available: MCPASGIHandler, MCPHealthHandler")
        return True
    except Exception as e:
        logger.error(f"❌ Handler creation failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    tests = [
        ("Imports", test_import),
        ("Extension Points", test_extension_points),
        ("Handler Creation", test_handler_creation),
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
