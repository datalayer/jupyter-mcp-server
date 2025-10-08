# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for list_kernels tool in both MCP_SERVER and JUPYTER_SERVER modes.
"""

import logging
import pytest

# Explicitly set pytest-asyncio mode for this module
pytestmark = pytest.mark.asyncio

from .test_common import MCPClient


@pytest.mark.asyncio
async def test_list_kernels(mcp_client_parametrized: MCPClient):
    """Test list_kernels functionality in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        # Call list_kernels
        kernel_list = await mcp_client_parametrized.list_kernels()
        logging.debug(f"Kernel list: {kernel_list}")
        
        # Verify result is a string
        assert isinstance(kernel_list, str), "list_kernels should return a string"
        
        # Check for either TSV header or "No kernels found" message
        has_header = "ID\tName\tDisplay_Name\tLanguage\tState\tConnections\tLast_Activity\tEnvironment" in kernel_list
        has_no_kernels_msg = "No kernels found" in kernel_list
        
        assert has_header or has_no_kernels_msg, \
            f"Kernel list should have TSV header or 'No kernels found' message, got: {kernel_list[:100]}"
        
        # Parse the output
        lines = kernel_list.strip().split('\n')
        
        # Should have at least one line (header or message)
        assert len(lines) >= 1, "Should have at least one line"
        
        # If there are running kernels (header present), verify the format
        if has_header and len(lines) > 1:
            # Check that data lines have the right number of columns
            header_cols = lines[0].split('\t')
            assert len(header_cols) == 8, f"Header should have 8 columns, got {len(header_cols)}"
            
            # Check first data line
            data_line = lines[1].split('\t')
            assert len(data_line) == 8, f"Data lines should have 8 columns, got {len(data_line)}"
            
            # Verify kernel ID is present (not empty or "unknown")
            kernel_id = data_line[0]
            assert kernel_id and kernel_id != "unknown", f"Kernel ID should not be empty or unknown, got '{kernel_id}'"
            
            # Verify kernel name is present
            kernel_name = data_line[1]
            assert kernel_name and kernel_name != "unknown", f"Kernel name should not be empty or unknown, got '{kernel_name}'"
            
            logging.info(f"Found {len(lines) - 1} running kernel(s)")
        else:
            # No kernels found - this is valid
            logging.info("No running kernels found")


@pytest.mark.asyncio
async def test_list_kernels_after_execution(mcp_client_parametrized: MCPClient):
    """Test that list_kernels shows kernel after code execution in both modes"""
    async with mcp_client_parametrized:
        # Get initial kernel list
        initial_list = await mcp_client_parametrized.list_kernels()
        logging.debug(f"Initial kernel list: {initial_list}")
        
        # Execute some code which should start a kernel
        await mcp_client_parametrized.insert_execute_code_cell(-1, "x = 1 + 1")
        
        # Now list kernels again - should have at least one
        kernel_list = await mcp_client_parametrized.list_kernels()
        logging.debug(f"Kernel list after execution: {kernel_list}")
        
        # Verify we have at least one kernel now
        lines = kernel_list.strip().split('\n')
        assert len(lines) >= 2, "Should have header and at least one kernel after code execution"
        
        # Verify kernel state is valid
        data_line = lines[1].split('\t')
        kernel_state = data_line[4]  # State is the 5th column (index 4)
        # State could be 'idle', 'busy', 'starting', etc.
        assert kernel_state != "unknown", f"Kernel state should be known, got '{kernel_state}'"
        
        # Clean up - delete the cell we created
        cell_count = await mcp_client_parametrized.get_cell_count()
        await mcp_client_parametrized.delete_cell(cell_count - 1)


@pytest.mark.asyncio
async def test_list_kernels_format(mcp_client_parametrized: MCPClient):
    """Test that list_kernels output format is consistent in both modes"""
    async with mcp_client_parametrized:
        # Ensure we have a running kernel by executing code
        initial_count = await mcp_client_parametrized.get_cell_count()
        
        await mcp_client_parametrized.insert_execute_code_cell(-1, "print('hello')")
        
        # Get kernel list
        kernel_list = await mcp_client_parametrized.list_kernels()
        
        # Parse and validate structure
        lines = kernel_list.strip().split('\n')
        assert len(lines) >= 2, "Should have header and at least one kernel"
        
        # Verify header structure
        header = lines[0]
        expected_headers = ["ID", "Name", "Display_Name", "Language", "State", "Connections", "Last_Activity", "Environment"]
        for expected_header in expected_headers:
            assert expected_header in header, f"Header should contain '{expected_header}'"
        
        # Verify data structure
        for i in range(1, len(lines)):
            data_line = lines[i].split('\t')
            assert len(data_line) == 8, f"Line {i} should have 8 columns"
            
            # ID should be a valid UUID-like string
            kernel_id = data_line[0]
            assert len(kernel_id) > 0, "Kernel ID should not be empty"
            
            # Name should not be empty
            kernel_name = data_line[1]
            assert len(kernel_name) > 0, "Kernel name should not be empty"
        
        # Clean up
        cell_count = await mcp_client_parametrized.get_cell_count()
        await mcp_client_parametrized.delete_cell(cell_count - 1)
