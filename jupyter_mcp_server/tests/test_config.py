#!/usr/bin/env python3
# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Simple test script to verify the configuration system works correctly.
"""

from jupyter_mcp_server.config import get_config, set_config, reset_config

def test_config():
    """Test the configuration singleton."""
    print("Testing Jupyter MCP Configuration System")
    print("=" * 50)
    
    # Test default configuration
    config = get_config()
    print(f"Default runtime_url: {config.runtime_url}")
    print(f"Default document_id: {config.document_id}")
    print(f"Default provider: {config.provider}")
    
    # Test setting configuration
    new_config = set_config(
        runtime_url="http://localhost:9999",
        document_id="test_notebook.ipynb",
        provider="datalayer",
        runtime_token="test_token"
    )
    
    print(f"\nUpdated runtime_url: {new_config.runtime_url}")
    print(f"Updated document_id: {new_config.document_id}")
    print(f"Updated provider: {new_config.provider}")
    print(f"Updated runtime_token: {'***' if new_config.runtime_token else 'None'}")
    
    # Test that singleton works - getting config again should return same values
    config2 = get_config()
    print(f"\nSingleton test - runtime_url: {config2.runtime_url}")
    print(f"Singleton test - document_id: {config2.document_id}")
    
    # Test reset
    reset_config()
    config3 = get_config()
    print(f"\nAfter reset - runtime_url: {config3.runtime_url}")
    print(f"After reset - document_id: {config3.document_id}")
    print(f"After reset - provider: {config3.provider}")
    
    print("\n✅ Configuration system test completed successfully!")

if __name__ == "__main__":
    test_config()
