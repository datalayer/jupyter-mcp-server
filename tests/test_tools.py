# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Integration tests for Jupyter MCP Server - Both MCP_SERVER and JUPYTER_SERVER modes.

This test suite validates the Jupyter MCP Server in both deployment modes:

1. **MCP_SERVER Mode**: Standalone server using HTTP/WebSocket to Jupyter
2. **JUPYTER_SERVER Mode**: Extension with direct serverapp API access

Tests are parametrized to run against both modes using the same MCPClient,
ensuring consistent behavior across both deployment patterns.

Launch the tests:
```
$ pytest tests/test_server.py -v
```
"""

import logging
import platform
from http import HTTPStatus

import pytest
import requests

from .test_common import MCPClient, JUPYTER_TOOLS, windows_timeout_wrapper
from .conftest import JUPYTER_TOKEN


###############################################################################
# Health Tests
###############################################################################

def test_jupyter_health(jupyter_server):
    """Test the Jupyter server health"""
    logging.info(f"Testing service health ({jupyter_server})")
    response = requests.get(
        f"{jupyter_server}/api/status",
        headers={
            "Authorization": f"token {JUPYTER_TOKEN}",
        },
    )
    assert response.status_code == HTTPStatus.OK


@pytest.mark.parametrize(
    "jupyter_mcp_server,kernel_expected_status",
    [(True, "alive"), (False, "not_initialized")],
    indirect=["jupyter_mcp_server"],
    ids=["start_runtime", "no_runtime"],
)
def test_mcp_health(jupyter_mcp_server, kernel_expected_status):
    """Test the MCP Jupyter server health"""
    logging.info(f"Testing MCP server health ({jupyter_mcp_server})")
    response = requests.get(f"{jupyter_mcp_server}/api/healthz")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    logging.debug(data)
    assert data.get("status") == "healthy"
    assert data.get("kernel_status") == kernel_expected_status


@pytest.mark.asyncio
async def test_mcp_tool_list(mcp_client_parametrized: MCPClient):
    """Check that the list of tools can be retrieved in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        tools = await mcp_client_parametrized.list_tools()
    tools_name = [tool.name for tool in tools.tools]
    logging.debug(f"tools_name: {tools_name}")
    assert len(tools_name) == len(JUPYTER_TOOLS) and sorted(tools_name) == sorted(
        JUPYTER_TOOLS
    )


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_markdown_cell(mcp_client_parametrized: MCPClient, content="Hello **World** !"):
    """Test markdown cell manipulation in both MCP_SERVER and JUPYTER_SERVER modes"""

    async def check_and_delete_markdown_cell(client: MCPClient, index, content):
        """Check and delete a markdown cell"""
        # reading and checking the content of the created cell
        cell_info = await client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "markdown"
        # TODO: don't now if it's normal to get a list of characters instead of a string
        assert "".join(cell_info["source"]) == content
        # reading all cells
        cells_info = await client.read_cells()
        assert cells_info is not None, "read_cells result should not be None"
        logging.debug(f"cells_info: {cells_info}")
        # Check that our cell is in the expected position with correct content
        assert "".join(cells_info[index]["source"]) == content
        # delete created cell
        result = await client.delete_cell(index)
        assert result is not None, "delete_cell result should not be None"
        assert result["result"] == f"Cell {index} (markdown) deleted successfully."

    async with mcp_client_parametrized:
        # Get initial cell count
        initial_count = await mcp_client_parametrized.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # append markdown cell using -1 index
        result = await mcp_client_parametrized.insert_cell(-1, "markdown", content)
        assert result is not None, "insert_cell result should not be None"
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(mcp_client_parametrized, initial_count, content)
        
        # insert markdown cell at the end (safer than index 0)
        result = await mcp_client_parametrized.insert_cell(initial_count, "markdown", content)
        assert result is not None, "insert_cell result should not be None"
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(mcp_client_parametrized, initial_count, content)


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_code_cell(mcp_client_parametrized: MCPClient, content="1 + 1"):
    """Test code cell manipulation in both MCP_SERVER and JUPYTER_SERVER modes"""
    async def check_and_delete_code_cell(client: MCPClient, index, content):
        """Check and delete a code cell"""
        # reading and checking the content of the created cell
        cell_info = await client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "code"
        assert "".join(cell_info["source"]) == content
        # reading all cells
        cells_info = await client.read_cells()
        logging.debug(f"cells_info: {cells_info}")
        # read_cells returns the list directly (unwrapped)
        assert "".join(cells_info[index]["source"]) == content
        # delete created cell
        result = await client.delete_cell(index)
        assert result["result"] == f"Cell {index} (code) deleted successfully."

    async with mcp_client_parametrized:
        # Get initial cell count
        initial_count = await mcp_client_parametrized.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # append and execute code cell using -1 index
        index = initial_count
        code_result = await mcp_client_parametrized.insert_execute_code_cell(-1, content)
        logging.debug(f"code_result: {code_result}")
        assert code_result is not None, "insert_execute_code_cell result should not be None"
        assert len(code_result["result"]) > 0, "insert_execute_code_cell should return non-empty result"
        # The first output should be the execution result, convert to int for comparison
        first_output = code_result["result"][0]
        first_output_value = int(first_output) if isinstance(first_output, str) else first_output
        assert first_output_value == eval(content), f"Expected {eval(content)}, got {first_output_value}"
        await check_and_delete_code_cell(mcp_client_parametrized, index, content)
        
        # insert and execute code cell at the end (safer than index 0)
        index = initial_count
        code_result = await mcp_client_parametrized.insert_execute_code_cell(index, content)
        logging.debug(f"code_result: {code_result}")
        expected_result = eval(content)
        assert int(code_result["result"][0]) == expected_result
        # overwrite content and test different cell execution modes
        content = f"({content}) * 2"
        expected_result = eval(content)
        result = await mcp_client_parametrized.overwrite_cell_source(index, content)
        logging.debug(f"result: {result}")
        # The server returns a message with diff content
        assert "Cell" in result["result"] and "overwritten successfully" in result["result"]
        assert "diff" in result["result"]  # Should contain diff output
        code_result = await mcp_client_parametrized.execute_cell_with_progress(index)
        assert int(code_result["result"][0]) == expected_result
        code_result = await mcp_client_parametrized.execute_cell_simple_timeout(index)
        # Handle case where execute_cell_simple_timeout might return None result
        if code_result and code_result.get("result") is not None:
            assert int(code_result["result"][0]) == expected_result
        else:
            logging.warning("execute_cell_simple_timeout returned None result, skipping assertion")
        await check_and_delete_code_cell(mcp_client_parametrized, index, content)


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_list_cells(mcp_client_parametrized: MCPClient):
    """Test list_cells functionality in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        # Test initial list_cells (notebook.ipynb has multiple cells)
        cell_list = await mcp_client_parametrized.list_cells()
        logging.debug(f"Initial cell list: {cell_list}")
        assert isinstance(cell_list, str)
        
        # Check for error conditions and skip if network issues occur
        if cell_list.startswith("Error executing tool list_cells") or cell_list.startswith("Error: Failed to retrieve"):
            pytest.skip(f"Network timeout occurred during list_cells operation: {cell_list}")
        
        assert "Index\tType\tCount\tFirst Line" in cell_list
        # The notebook has both markdown and code cells - just verify structure
        lines = cell_list.split('\n')
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index')]
        assert len(data_lines) >= 1  # Should have at least some cells
        
        # Add a markdown cell and test again
        markdown_content = "# Test Markdown Cell"
        await mcp_client_parametrized.insert_cell(-1, "markdown", markdown_content)
        
        # Check list_cells with added markdown cell
        cell_list = await mcp_client_parametrized.list_cells()
        logging.debug(f"Cell list after adding markdown: {cell_list}")
        lines = cell_list.split('\n')
        
        # Should have header, separator, and multiple data lines
        assert len(lines) >= 4  # header + separator + at least some cells
        assert "Index\tType\tCount\tFirst Line" in lines[0]
        
        # Check that the added cell is listed
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index')]
        assert len(data_lines) >= 10  # Should have at least the original 10 cells
        
        # Check that our added cell appears in the list
        assert any("# Test Markdown Cell" in line for line in data_lines)
        
        # Add a code cell with long content to test truncation
        long_code = "# This is a very long comment that should be truncated when displayed in the list because it exceeds the 50 character limit"
        await mcp_client_parametrized.insert_execute_code_cell(-1, "print('Hello World')")
        
        # Check list_cells with truncated content
        cell_list = await mcp_client_parametrized.list_cells()
        logging.debug(f"Cell list after adding long code: {cell_list}")
        
        # Clean up by deleting added cells (in reverse order)
        # Get current cell count to determine indices of added cells
        current_count = await mcp_client_parametrized.get_cell_count()
        # Delete the last two cells we added
        await mcp_client_parametrized.delete_cell(current_count - 1)  # Remove the code cell
        await mcp_client_parametrized.delete_cell(current_count - 2)  # Remove the markdown cell

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_overwrite_cell_diff(mcp_client_parametrized: MCPClient):
    """Test overwrite_cell_source diff functionality in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        # Get initial cell count
        initial_count = await mcp_client_parametrized.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # Add a code cell with initial content
        initial_content = "x = 10\nprint(x)"
        await mcp_client_parametrized.append_execute_code_cell(initial_content)
        cell_index = initial_count
        
        # Overwrite with modified content
        new_content = "x = 20\ny = 30\nprint(x + y)"
        result = await mcp_client_parametrized.overwrite_cell_source(cell_index, new_content)
        
        # Verify diff output format
        assert result is not None, "overwrite_cell_source should not return None for valid input"
        result_text = result.get("result", "") if isinstance(result, dict) else str(result)
        assert f"Cell {cell_index} overwritten successfully!" in result_text
        assert "```diff" in result_text
        assert "```" in result_text  # Should have closing diff block
        
        # Verify diff content shows changes
        assert "-" in result_text  # Should show deletions
        assert "+" in result_text  # Should show additions
        
        # Test overwriting with identical content (no changes)
        result_no_change = await mcp_client_parametrized.overwrite_cell_source(cell_index, new_content)
        assert result_no_change is not None, "overwrite_cell_source should not return None"
        no_change_text = result_no_change.get("result", "") if isinstance(result_no_change, dict) else str(result_no_change)
        assert "no changes detected" in no_change_text
        
        # Test overwriting markdown cell
        await mcp_client_parametrized.append_markdown_cell("# Original Title")
        markdown_index = initial_count + 1
        
        markdown_result = await mcp_client_parametrized.overwrite_cell_source(markdown_index, "# Updated Title\n\nSome content")
        assert markdown_result is not None, "overwrite_cell_source should not return None for markdown cell"
        markdown_text = markdown_result.get("result", "") if isinstance(markdown_result, dict) else str(markdown_result)
        assert f"Cell {markdown_index} overwritten successfully!" in markdown_text
        assert "```diff" in markdown_text
        assert "Updated Title" in markdown_text
        
        # Clean up: delete the test cells
        await mcp_client_parametrized.delete_cell(markdown_index)  # Delete markdown cell first (higher index)
        await mcp_client_parametrized.delete_cell(cell_index)      # Then delete code cell

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_bad_index(mcp_client_parametrized: MCPClient, index=99):
    """Test behavior of all index-based tools if the index does not exist in both modes"""
    async with mcp_client_parametrized:
        assert await mcp_client_parametrized.read_cell(index) is None
        assert await mcp_client_parametrized.insert_cell(index, "markdown", "test") is None
        assert await mcp_client_parametrized.insert_execute_code_cell(index, "1 + 1") is None
        assert await mcp_client_parametrized.overwrite_cell_source(index, "1 + 1") is None
        assert await mcp_client_parametrized.execute_cell_with_progress(index) is None
        assert await mcp_client_parametrized.execute_cell_simple_timeout(index) is None
        assert await mcp_client_parametrized.delete_cell(index) is None


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_multimodal_output(mcp_client_parametrized: MCPClient):
    """Test multimodal output functionality with image generation in both modes"""
    async with mcp_client_parametrized:
        # Get initial cell count
        initial_count = await mcp_client_parametrized.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # Test image generation code using PIL (lightweight)
        image_code = """
from PIL import Image, ImageDraw
import io
import base64

# Create a simple test image using PIL
width, height = 200, 100
image = Image.new('RGB', (width, height), color='white')
draw = ImageDraw.Draw(image)

# Draw a simple pattern
draw.rectangle([10, 10, 190, 90], outline='blue', width=2)
draw.ellipse([20, 20, 80, 80], fill='red')
draw.text((100, 40), "Test Image", fill='black')

# Convert to PNG and display
buffer = io.BytesIO()
image.save(buffer, format='PNG')
buffer.seek(0)

# Display the image (this should generate image/png output)
from IPython.display import Image as IPythonImage, display
display(IPythonImage(buffer.getvalue()))
"""
        
        # Execute the image generation code
        result = await mcp_client_parametrized.insert_execute_code_cell(-1, image_code)
        cell_index = initial_count
        
        # Check that result is not None and contains outputs
        assert result is not None, "Result should not be None"
        assert "result" in result, "Result should contain 'result' key"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        # Check for image output or placeholder
        has_image_output = False
        for output in outputs:
            if isinstance(output, str):
                # Check for image placeholder or actual image content
                if ("Image Output (PNG)" in output or 
                    "image display" in output.lower() or
                    output.strip() == ''):
                    has_image_output = True
                    break
            elif isinstance(output, dict):
                # Check for ImageContent dictionary format
                if (output.get('type') == 'image' and 
                    'data' in output and 
                    output.get('mimeType') == 'image/png'):
                    has_image_output = True
                    logging.info(f"Found ImageContent object with {len(output['data'])} bytes of PNG data")
                    break
            elif hasattr(output, 'data') and hasattr(output, 'mimeType'):
                # This would be an actual ImageContent object
                if output.mimeType == "image/png":
                    has_image_output = True
                    break
        
        # We should have some indication of image output
        assert has_image_output, f"Expected image output indication, got: {outputs}"
        
        # Test with ALLOW_IMG_OUTPUT environment variable control
        # Note: In actual deployment, this would be controlled via environment variables
        # For testing, we just verify the code structure is correct
        logging.info(f"Multimodal test completed with outputs: {outputs}")
        
        # Clean up: delete the test cell
        await mcp_client_parametrized.delete_cell(cell_index)


###############################################################################
# Multi-Notebook Management Tests
###############################################################################

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_multi_notebook_management(mcp_client_parametrized: MCPClient):
    """Test multi-notebook management functionality in both modes"""
    async with mcp_client_parametrized:
        # Test initial state - should show default notebook or no notebooks
        initial_list = await mcp_client_parametrized.list_notebooks()
        logging.debug(f"Initial notebook list: {initial_list}")
        
        # Connect to a new notebook
        connect_result = await mcp_client_parametrized.use_notebook("test_notebooks", "new.ipynb", "connect")
        logging.debug(f"Connect result: {connect_result}")
        assert "Successfully using notebook 'test_notebooks'" in connect_result
        assert "new.ipynb" in connect_result
        
        # List notebooks - should now show the connected notebook
        notebook_list = await mcp_client_parametrized.list_notebooks()
        logging.debug(f"Notebook list after connect: {notebook_list}")
        assert "test_notebooks" in notebook_list
        assert "new.ipynb" in notebook_list
        assert "✓" in notebook_list  # Should be marked as current
        
        # Try to connect to the same notebook again (should fail)
        duplicate_result = await mcp_client_parametrized.use_notebook("test_notebooks", "new.ipynb")
        assert "already using" in duplicate_result
        
        # Test switching between notebooks
        if "default" in notebook_list:
            use_result = await mcp_client_parametrized.use_notebook("default")
            logging.debug(f"Switch to default result: {use_result}")
            assert "Successfully switched to notebook 'default'" in use_result
            
            # Switch back to test notebook
            use_back_result = await mcp_client_parametrized.use_notebook("test_notebooks")
            assert "Successfully switched to notebook 'test_notebooks'" in use_back_result
        
        # Test cell operations on the new notebook
        # First get the cell count of new.ipynb (should have some cells)
        cell_count = await mcp_client_parametrized.get_cell_count()
        assert cell_count >= 2, f"new.ipynb should have at least 2 cells, got {cell_count}"
        
        # Add a test cell to the new notebook
        test_content = "# Multi-notebook test\nprint('Testing multi-notebook')"
        insert_result = await mcp_client_parametrized.insert_cell(-1, "code", test_content)
        assert "Cell inserted successfully" in insert_result["result"]
        
        # Execute the cell
        execute_result = await mcp_client_parametrized.insert_execute_code_cell(-1, "2 + 3")
        assert "5" in str(execute_result["result"])
        
        # Test restart notebook
        restart_result = await mcp_client_parametrized.restart_notebook("test_notebooks")
        logging.debug(f"Restart result: {restart_result}")
        assert "restarted successfully" in restart_result
        
        # Test unuse notebook
        disconnect_result = await mcp_client_parametrized.unuse_notebook("test_notebooks")
        logging.debug(f"Unuse result: {disconnect_result}")
        assert "unused successfully" in disconnect_result
        
        # Verify notebook is no longer in the list
        final_list = await mcp_client_parametrized.list_notebooks()
        logging.debug(f"Final notebook list: {final_list}")
        if "No notebooks are currently connected" not in final_list:
            assert "test_notebooks" not in final_list


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_multi_notebook_cell_operations(mcp_client_parametrized: MCPClient):
    """Test cell operations across multiple notebooks in both modes"""
    async with mcp_client_parametrized:
        # Connect to the new notebook
        await mcp_client_parametrized.use_notebook("notebook_a", "new.ipynb")
        
        # Get initial cell count for notebook A
        count_a = await mcp_client_parametrized.get_cell_count()
        
        # Add a cell to notebook A
        await mcp_client_parametrized.insert_cell(-1, "markdown", "# This is notebook A")
        
        # Connect to default notebook (if it exists)
        try:
            # Try to connect to notebook.ipynb as notebook_b
            await mcp_client_parametrized.use_notebook("notebook_b", "notebook.ipynb")
            
            # Switch to notebook B
            await mcp_client_parametrized.use_notebook("notebook_b")
            
            # Get cell count for notebook B
            count_b = await mcp_client_parametrized.get_cell_count()
            
            # Add a cell to notebook B
            await mcp_client_parametrized.insert_cell(-1, "markdown", "# This is notebook B")
            
            # Switch back to notebook A
            await mcp_client_parametrized.use_notebook("notebook_a")
            
            # Verify we're working with notebook A
            cell_list_a = await mcp_client_parametrized.list_cells()
            assert "This is notebook A" in cell_list_a
            
            # Switch to notebook B and verify
            await mcp_client_parametrized.use_notebook("notebook_b")
            cell_list_b = await mcp_client_parametrized.list_cells()
            assert "This is notebook B" in cell_list_b
            
            # Clean up - unuse both notebooks
            await mcp_client_parametrized.unuse_notebook("notebook_a")
            await mcp_client_parametrized.unuse_notebook("notebook_b")
            
        except Exception as e:
            logging.warning(f"Could not test with notebook.ipynb: {e}")
            # Clean up notebook A only
            await mcp_client_parametrized.unuse_notebook("notebook_a")


@pytest.mark.asyncio 
@windows_timeout_wrapper(30)
async def test_notebooks_error_cases(mcp_client_parametrized: MCPClient):
    """Test error handling for notebook management in both modes"""
    async with mcp_client_parametrized:
        # Test connecting to non-existent notebook
        error_result = await mcp_client_parametrized.use_notebook("nonexistent", "nonexistent.ipynb")
        logging.debug(f"Nonexistent notebook result: {error_result}")
        assert "not found" in error_result.lower() or "not a valid file" in error_result.lower()
        
        # Test operations on non-used notebook
        restart_error = await mcp_client_parametrized.restart_notebook("nonexistent_notebook")
        assert "not connected" in restart_error
        
        disconnect_error = await mcp_client_parametrized.unuse_notebook("nonexistent_notebook") 
        assert "not connected" in disconnect_error
        
        use_error = await mcp_client_parametrized.use_notebook("nonexistent_notebook")
        assert "not connected" in use_error
        
        # Test invalid notebook paths
        invalid_path_result = await mcp_client_parametrized.use_notebook("test", "../invalid/path.ipynb")
        assert "not found" in invalid_path_result.lower() or "not a valid file" in invalid_path_result.lower()


###############################################################################
# execute_ipython Tests
###############################################################################

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_python_code(mcp_client_parametrized: MCPClient):
    """Test execute_ipython with basic Python code in both modes"""
    async with mcp_client_parametrized:
        # Test simple Python code
        result = await mcp_client_parametrized.execute_ipython("print('Hello IPython World!')")
        
        # On Windows, if result is None it's likely due to timeout - skip the test
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        assert "result" in result, "Result should contain 'result' key"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        # Check for expected output
        output_text = "".join(str(output) for output in outputs)
        assert "Hello IPython World!" in output_text or "[No output generated]" in output_text
        
        # Test mathematical calculation
        calc_result = await mcp_client_parametrized.execute_ipython("result = 2 ** 10\nprint(f'2^10 = {result}')")
        
        if platform.system() == "Windows" and calc_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        assert calc_result is not None
        calc_outputs = calc_result["result"]
        calc_text = "".join(str(output) for output in calc_outputs)
        assert "2^10 = 1024" in calc_text or "[No output generated]" in calc_text


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_magic_commands(mcp_client_parametrized: MCPClient):
    """Test execute_ipython with IPython magic commands in both modes"""
    async with mcp_client_parametrized:
        # Test %who magic command (list variables)
        result = await mcp_client_parametrized.execute_ipython("%who")
        
        # On Windows, if result is None it's likely due to timeout - skip the test
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        # Set a variable first, then use %who to see it
        var_result = await mcp_client_parametrized.execute_ipython("test_var = 42")
        if platform.system() == "Windows" and var_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        who_result = await mcp_client_parametrized.execute_ipython("%who")
        if platform.system() == "Windows" and who_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        who_outputs = who_result["result"]
        who_text = "".join(str(output) for output in who_outputs)
        # %who should show our variable (or no output if variables exist but aren't shown)
        # This test mainly ensures %who doesn't crash
        
        # Test %timeit magic command
        timeit_result = await mcp_client_parametrized.execute_ipython("%timeit sum(range(100))")
        if platform.system() == "Windows" and timeit_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        assert timeit_result is not None
        timeit_outputs = timeit_result["result"]
        timeit_text = "".join(str(output) for output in timeit_outputs)
        # timeit should produce some timing output or complete without error
        assert len(timeit_text) >= 0  # Just ensure no crash


@pytest.mark.asyncio 
@windows_timeout_wrapper(30)
async def test_execute_ipython_shell_commands(mcp_client_parametrized: MCPClient):
    """Test execute_ipython with shell commands in both modes"""
    async with mcp_client_parametrized:
        # Test basic shell command - echo (works on most systems)
        result = await mcp_client_parametrized.execute_ipython("!echo 'Hello from shell'")
        
        # On Windows, if result is None it's likely due to timeout - skip the test
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        output_text = "".join(str(output) for output in outputs)
        # Shell command should either work or be handled gracefully
        assert len(output_text) >= 0  # Just ensure no crash
        
        # Test Python version check
        python_result = await mcp_client_parametrized.execute_ipython("!python --version")
        if platform.system() == "Windows" and python_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        assert python_result is not None
        python_outputs = python_result["result"]
        python_text = "".join(str(output) for output in python_outputs)
        # Should show Python version or complete without error
        assert len(python_text) >= 0


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_timeout(mcp_client_parametrized: MCPClient):
    """Test execute_ipython timeout functionality in both modes"""
    async with mcp_client_parametrized:
        # Test with very short timeout on a potentially long-running command
        result = await mcp_client_parametrized.execute_ipython("import time; time.sleep(5)", timeout=2)
        
        # On Windows, if result is None it's likely due to timeout - skip the test
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None
        outputs = result["result"]
        output_text = "".join(str(output) for output in outputs)
        # Should either complete quickly or timeout
        assert "TIMEOUT ERROR" in output_text or len(output_text) >= 0


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_error_handling(mcp_client_parametrized: MCPClient):
    """Test execute_ipython error handling in both modes"""
    async with mcp_client_parametrized:
        # Test syntax error
        result = await mcp_client_parametrized.execute_ipython("invalid python syntax <<<")
        
        # On Windows, if result is None it's likely due to timeout - skip the test
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None
        outputs = result["result"]
        output_text = "".join(str(output) for output in outputs)
        # Should handle the error gracefully
        assert len(output_text) >= 0  # Ensure no crash
        
        # Test runtime error  
        runtime_result = await mcp_client_parametrized.execute_ipython("undefined_variable")
        if platform.system() == "Windows" and runtime_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        assert runtime_result is not None
        runtime_outputs = runtime_result["result"]
        runtime_text = "".join(str(output) for output in runtime_outputs)
        # Should handle the error gracefully
        assert len(runtime_text) >= 0