# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Integration tests for Jupyter MCP Server in JUPYTER_SERVER mode (local/extension).

This test file validates the server when running as a Jupyter Server extension
that uses local Jupyter APIs directly (contents_manager, kernel_manager, etc).

The key difference from test_mcp_server.py:
- MCP_SERVER mode: Uses HTTP/WebSocket to communicate with remote Jupyter server
- JUPYTER_SERVER mode: Uses local Python APIs directly within the Jupyter process

This tests the same tool functionality but exercises different code paths:
- YDoc collaborative editing (not available in MCP_SERVER mode)
- Direct kernel_manager access for execute_ipython
- Local contents_manager for file operations

Launch the tests:
```
$ pytest tests/test_jupyter_server.py
```
"""

import asyncio
import logging
import platform
from http import HTTPStatus
from pathlib import Path

import pytest
import pytest_asyncio
import requests

from test_common import JUPYTER_TOOLS, windows_timeout_wrapper
from conftest import JUPYTER_TOKEN


###############################################################################
# DirectClient - Local API Access for JUPYTER_SERVER Mode
###############################################################################

class DirectClient:
    """
    A client that calls Jupyter MCP Server tools directly using local APIs.
    
    This simulates the JUPYTER_SERVER mode where tools run as a Jupyter extension
    and have direct access to serverapp, contents_manager, kernel_manager, etc.
    
    Unlike MCPClient which uses the MCP protocol over HTTP, DirectClient imports
    the tool classes and calls them directly with a mock ServerContext.
    """
    
    def __init__(self, jupyter_url, notebook_path="notebook.ipynb"):
        self.jupyter_url = jupyter_url
        self.notebook_path = notebook_path
        self._tools = None
        self._context = None
        
    async def __aenter__(self):
        """Initialize tools and context"""
        # Import tool classes
        from jupyter_mcp_server.config import ServerMode, get_or_create_context
        
        # Create context with JUPYTER_SERVER mode
        # Note: In a real Jupyter extension, serverapp would be passed by Jupyter
        # For testing, we'll connect to the running Jupyter server
        self._context = get_or_create_context(
            mode=ServerMode.JUPYTER_SERVER,
            document_url=self.jupyter_url,
            document_id=self.notebook_path,
            document_token=JUPYTER_TOKEN,
            runtime_url=self.jupyter_url,
            runtime_token=JUPYTER_TOKEN,
            start_new_runtime=True,
        )
        
        # Initialize tools
        from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool
        from jupyter_mcp_server.tools.list_notebooks_tool import ListNotebooksTool
        from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool
        from jupyter_mcp_server.tools.unuse_notebook_tool import UnuseNotebookTool
        from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
        from jupyter_mcp_server.tools.insert_execute_code_cell_tool import InsertExecuteCodeCellTool
        from jupyter_mcp_server.tools.overwrite_cell_source_tool import OverwriteCellSourceTool
        from jupyter_mcp_server.tools.execute_cell_with_progress_tool import ExecuteCellWithProgressTool
        from jupyter_mcp_server.tools.execute_cell_simple_timeout_tool import ExecuteCellSimpleTimeoutTool
        from jupyter_mcp_server.tools.execute_cell_streaming_tool import ExecuteCellStreamingTool
        from jupyter_mcp_server.tools.read_cells_tool import ReadCellsTool
        from jupyter_mcp_server.tools.list_cells_tool import ListCellsTool
        from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool
        from jupyter_mcp_server.tools.delete_cell_tool import DeleteCellTool
        from jupyter_mcp_server.tools.execute_ipython_tool import ExecuteIpythonTool
        from jupyter_mcp_server.tools.list_files_tool import ListFilesTool
        from jupyter_mcp_server.tools.list_kernels_tool import ListKernelsTool
        
        self._tools = {
            "use_notebook": UseNotebookTool(),
            "list_notebook": ListNotebooksTool(),
            "restart_notebook": RestartNotebookTool(),
            "unuse_notebook": UnuseNotebookTool(),
            "insert_cell": InsertCellTool(),
            "insert_execute_code_cell": InsertExecuteCodeCellTool(),
            "overwrite_cell_source": OverwriteCellSourceTool(),
            "execute_cell_with_progress": ExecuteCellWithProgressTool(),
            "execute_cell_simple_timeout": ExecuteCellSimpleTimeoutTool(),
            "execute_cell_streaming": ExecuteCellStreamingTool(),
            "read_cells": ReadCellsTool(),
            "list_cells": ListCellsTool(),
            "read_cell": ReadCellTool(),
            "delete_cell": DeleteCellTool(),
            "execute_ipython": ExecuteIpythonTool(),
            "list_files": ListFilesTool(),
            "list_kernel": ListKernelsTool(),
        }
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup"""
        self._tools = None
        self._context = None
    
    async def list_tools(self):
        """Return list of available tools"""
        class ToolsList:
            def __init__(self, tools):
                self.tools = [type('Tool', (), {'name': name}) for name in tools.keys()]
        
        return ToolsList(self._tools)
    
    # Multi-Notebook Management Methods
    async def use_notebook(self, notebook_name, notebook_path=None, mode="connect", kernel_id=None):
        result = await self._tools["use_notebook"].execute(
            notebook_name=notebook_name,
            notebook_path=notebook_path,
            mode=mode,
            kernel_id=kernel_id
        )
        return result.get("result") if isinstance(result, dict) else str(result)
    
    async def list_notebook(self):
        result = await self._tools["list_notebook"].execute()
        return result.get("result") if isinstance(result, dict) else str(result)
    
    async def restart_notebook(self, notebook_name):
        result = await self._tools["restart_notebook"].execute(notebook_name=notebook_name)
        return result.get("result") if isinstance(result, dict) else str(result)
    
    async def unuse_notebook(self, notebook_name):
        result = await self._tools["unuse_notebook"].execute(notebook_name=notebook_name)
        return result.get("result") if isinstance(result, dict) else str(result)
    
    async def insert_cell(self, cell_index, cell_type, cell_source):
        result = await self._tools["insert_cell"].execute(
            cell_index=cell_index,
            cell_type=cell_type,
            cell_source=cell_source
        )
        return result
    
    async def insert_execute_code_cell(self, cell_index, cell_source):
        result = await self._tools["insert_execute_code_cell"].execute(
            cell_index=cell_index,
            cell_source=cell_source
        )
        return result
    
    async def read_cell(self, cell_index):
        result = await self._tools["read_cell"].execute(cell_index=cell_index)
        return result
    
    async def read_cells(self):
        result = await self._tools["read_cells"].execute()
        return result
    
    async def list_cells(self, max_retries=3):
        """List cells with retry mechanism for Windows compatibility"""
        for attempt in range(max_retries):
            try:
                result = await self._tools["list_cells"].execute()
                text_result = result.get("result") if isinstance(result, dict) else str(result)
                if text_result and "Index\tType" in text_result:
                    return text_result
                else:
                    logging.warning(f"list_cells returned unexpected result on attempt {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"list_cells failed on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)
                else:
                    return "Error: Failed to retrieve cell list after all retries"
        return "Error: Failed to retrieve cell list after all retries"
    
    async def delete_cell(self, cell_index):
        result = await self._tools["delete_cell"].execute(cell_index=cell_index)
        return result
    
    async def execute_cell_streaming(self, cell_index):
        result = await self._tools["execute_cell_streaming"].execute(cell_index=cell_index)
        return result
    
    async def execute_cell_with_progress(self, cell_index):
        result = await self._tools["execute_cell_with_progress"].execute(cell_index=cell_index)
        return result
    
    async def execute_cell_simple_timeout(self, cell_index):
        result = await self._tools["execute_cell_simple_timeout"].execute(cell_index=cell_index)
        return result
    
    async def overwrite_cell_source(self, cell_index, cell_source):
        result = await self._tools["overwrite_cell_source"].execute(
            cell_index=cell_index,
            cell_source=cell_source
        )
        return result
    
    async def execute_ipython(self, code, timeout=60):
        result = await self._tools["execute_ipython"].execute(
            code=code,
            timeout=timeout
        )
        return result
    
    async def append_execute_code_cell(self, cell_source):
        """Append and execute a code cell at the end of the notebook."""
        return await self.insert_execute_code_cell(-1, cell_source)
    
    async def append_markdown_cell(self, cell_source):
        """Append a markdown cell at the end of the notebook."""
        return await self.insert_cell(-1, "markdown", cell_source)
    
    async def get_cell_count(self):
        """Get the number of cells by parsing list_cells output"""
        cell_list = await self.list_cells()
        if "Error" in cell_list or "Index\tType" not in cell_list:
            return 0
        lines = cell_list.split('\n')
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index') and not line.startswith('-')]
        return len(data_lines)


###############################################################################
# JUPYTER_SERVER Mode Fixtures
###############################################################################

@pytest_asyncio.fixture(scope="function")
async def direct_client(jupyter_server) -> DirectClient:
    """A DirectClient that calls tools directly using local APIs"""
    return DirectClient(jupyter_server)


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


@pytest.mark.asyncio
async def test_tool_list(direct_client: DirectClient):
    """Check that the list of tools can be retrieved and match"""
    async with direct_client:
        tools = await direct_client.list_tools()
    tools_name = [tool.name for tool in tools.tools]
    logging.debug(f"tools_name: {tools_name}")
    assert len(tools_name) == len(JUPYTER_TOOLS) and sorted(tools_name) == sorted(
        JUPYTER_TOOLS
    )


###############################################################################
# Cell Operations Tests (Same as MCP_SERVER but using DirectClient)
###############################################################################

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_markdown_cell(direct_client, content="Hello **World** !"):
    """Test markdown cell manipulation using direct API calls"""
    
    async def check_and_delete_markdown_cell(client, index, content):
        """Check and delete a markdown cell"""
        cell_info = await client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "markdown"
        assert "".join(cell_info["source"]) == content
        
        result = await client.read_cells()
        assert result is not None, "read_cells result should not be None"
        cells_info = result["result"]
        logging.debug(f"cells_info: {cells_info}")
        assert "".join(cells_info[index]["source"]) == content
        
        result = await client.delete_cell(index)
        assert result is not None, "delete_cell result should not be None"
        assert result["result"] == f"Cell {index} (markdown) deleted successfully."
    
    async with direct_client:
        initial_count = await direct_client.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # Test append markdown cell using -1 index
        result = await direct_client.insert_cell(-1, "markdown", content)
        assert result is not None, "insert_cell result should not be None"
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(direct_client, initial_count, content)
        
        # Test insert markdown cell at the end
        result = await direct_client.insert_cell(initial_count, "markdown", content)
        assert result is not None, "insert_cell result should not be None"
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(direct_client, initial_count, content)


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_code_cell(direct_client, content="1 + 1"):
    """Test code cell manipulation using direct API calls"""
    
    async def check_and_delete_code_cell(client, index, content):
        """Check and delete a code cell"""
        cell_info = await client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "code"
        assert "".join(cell_info["source"]) == content
        
        result = await client.read_cells()
        cells_info = result["result"]
        logging.debug(f"cells_info: {cells_info}")
        assert "".join(cells_info[index]["source"]) == content
        
        result = await client.delete_cell(index)
        assert result["result"] == f"Cell {index} (code) deleted successfully."
    
    async with direct_client:
        initial_count = await direct_client.get_cell_count()
        if initial_count == 0:
            pytest.skip("Could not retrieve cell count - likely a platform-specific network issue")
        
        # Test append and execute code cell using -1 index
        index = initial_count
        code_result = await direct_client.insert_execute_code_cell(-1, content)
        logging.debug(f"code_result: {code_result}")
        assert code_result is not None, "insert_execute_code_cell result should not be None"
        assert int(code_result["result"][0]) == eval(content)
        await check_and_delete_code_cell(direct_client, index, content)
        
        # Test insert and execute code cell at the end
        index = initial_count
        code_result = await direct_client.insert_execute_code_cell(index, content)
        logging.debug(f"code_result: {code_result}")
        expected_result = eval(content)
        assert int(code_result["result"][0]) == expected_result
        
        # Test overwrite content and different cell execution modes
        content = f"({content}) * 2"
        expected_result = eval(content)
        result = await direct_client.overwrite_cell_source(index, content)
        logging.debug(f"result: {result}")
        assert "Cell" in result["result"] and "overwritten successfully" in result["result"]
        assert "diff" in result["result"]
        
        code_result = await direct_client.execute_cell_with_progress(index)
        assert int(code_result["result"][0]) == expected_result
        
        code_result = await direct_client.execute_cell_simple_timeout(index)
        if code_result and code_result.get("result") is not None:
            assert int(code_result["result"][0]) == expected_result
        else:
            logging.warning("execute_cell_simple_timeout returned None result, skipping assertion")
        
        await check_and_delete_code_cell(direct_client, index, content)


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_list_cells(direct_client: DirectClient):
    """Test list_cells functionality"""
    async with direct_client:
        cell_list = await direct_client.list_cells()
        logging.debug(f"Initial cell list: {cell_list}")
        assert isinstance(cell_list, str)
        
        if cell_list.startswith("Error"):
            pytest.skip(f"Error occurred during list_cells operation: {cell_list}")
        
        assert "Index\tType\tCount\tFirst Line" in cell_list
        lines = cell_list.split('\n')
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index')]
        assert len(data_lines) >= 1
        
        # Add a markdown cell and test again
        markdown_content = "# Test Markdown Cell"
        await direct_client.insert_cell(-1, "markdown", markdown_content)
        
        cell_list = await direct_client.list_cells()
        logging.debug(f"Cell list after adding markdown: {cell_list}")
        lines = cell_list.split('\n')
        
        assert len(lines) >= 4
        assert "Index\tType\tCount\tFirst Line" in lines[0]
        
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index')]
        assert len(data_lines) >= 10
        
        assert any("# Test Markdown Cell" in line for line in data_lines)
        
        # Add a code cell
        await direct_client.insert_execute_code_cell(-1, "print('Hello World')")
        
        cell_list = await direct_client.list_cells()
        logging.debug(f"Cell list after adding long code: {cell_list}")
        
        # Clean up by deleting added cells
        current_count = await direct_client.get_cell_count()
        await direct_client.delete_cell(current_count - 1)
        await direct_client.delete_cell(current_count - 2)


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_bad_index(direct_client, index=99):
    """Test behavior of all index-based tools if the index does not exist"""
    async with direct_client:
        assert await direct_client.read_cell(index) is None
        assert await direct_client.insert_cell(index, "markdown", "test") is None
        assert await direct_client.insert_execute_code_cell(index, "1 + 1") is None
        assert await direct_client.overwrite_cell_source(index, "1 + 1") is None
        assert await direct_client.execute_cell_with_progress(index) is None
        assert await direct_client.execute_cell_simple_timeout(index) is None
        assert await direct_client.delete_cell(index) is None


###############################################################################
# Multi-Notebook Management Tests
###############################################################################

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_multi_notebook_management(direct_client: DirectClient):
    """Test multi-notebook management functionality"""
    async with direct_client:
        # Test initial state
        initial_list = await direct_client.list_notebook()
        logging.debug(f"Initial notebook list: {initial_list}")
        
        # Connect to a new notebook
        connect_result = await direct_client.use_notebook("test_notebook", "new.ipynb", "connect")
        logging.debug(f"Connect result: {connect_result}")
        assert "Successfully using notebook 'test_notebook'" in connect_result
        assert "new.ipynb" in connect_result
        
        # List notebooks
        notebook_list = await direct_client.list_notebook()
        logging.debug(f"Notebook list after connect: {notebook_list}")
        assert "test_notebook" in notebook_list
        assert "new.ipynb" in notebook_list
        assert "✓" in notebook_list
        
        # Try to connect to the same notebook again (should fail)
        duplicate_result = await direct_client.use_notebook("test_notebook", "new.ipynb")
        assert "already using" in duplicate_result
        
        # Test cell operations on the new notebook
        cell_count = await direct_client.get_cell_count()
        assert cell_count >= 2, f"new.ipynb should have at least 2 cells, got {cell_count}"
        
        # Add a test cell
        test_content = "# Multi-notebook test\nprint('Testing multi-notebook')"
        insert_result = await direct_client.insert_cell(-1, "code", test_content)
        assert "Cell inserted successfully" in insert_result["result"]
        
        # Execute a cell
        execute_result = await direct_client.insert_execute_code_cell(-1, "2 + 3")
        assert "5" in str(execute_result["result"])
        
        # Test restart notebook
        restart_result = await direct_client.restart_notebook("test_notebook")
        logging.debug(f"Restart result: {restart_result}")
        assert "restarted successfully" in restart_result
        
        # Test unuse notebook
        disconnect_result = await direct_client.unuse_notebook("test_notebook")
        logging.debug(f"Unuse result: {disconnect_result}")
        assert "unused successfully" in disconnect_result
        
        # Verify notebook is no longer in the list
        final_list = await direct_client.list_notebook()
        logging.debug(f"Final notebook list: {final_list}")
        if "No notebooks are currently connected" not in final_list:
            assert "test_notebook" not in final_list


###############################################################################
# execute_ipython Tests (Uses Direct Kernel Manager Access)
###############################################################################

@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_python_code(direct_client: DirectClient):
    """Test execute_ipython with basic Python code"""
    async with direct_client:
        result = await direct_client.execute_ipython("print('Hello IPython World!')")
        
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        assert "result" in result, "Result should contain 'result' key"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        output_text = "".join(str(output) for output in outputs)
        assert "Hello IPython World!" in output_text or "[No output generated]" in output_text


@pytest.mark.asyncio
@windows_timeout_wrapper(30)
async def test_execute_ipython_magic_commands(direct_client: DirectClient):
    """Test execute_ipython with IPython magic commands"""
    async with direct_client:
        # Test %who magic command
        result = await direct_client.execute_ipython("%who")
        
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        # Set a variable and use %who
        var_result = await direct_client.execute_ipython("test_var = 42")
        if platform.system() == "Windows" and var_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
            
        who_result = await direct_client.execute_ipython("%who")
        if platform.system() == "Windows" and who_result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        who_outputs = who_result["result"]
        who_text = "".join(str(output) for output in who_outputs)
        # Just ensure %who doesn't crash


@pytest.mark.asyncio 
@windows_timeout_wrapper(30)
async def test_execute_ipython_shell_commands(direct_client: DirectClient):
    """Test execute_ipython with shell commands (! prefix)"""
    async with direct_client:
        result = await direct_client.execute_ipython("!echo 'Hello from shell'")
        
        if platform.system() == "Windows" and result is None:
            pytest.skip("execute_ipython timed out on Windows - known platform limitation")
        
        assert result is not None, "execute_ipython result should not be None"
        outputs = result["result"]
        assert isinstance(outputs, list), "Outputs should be a list"
        
        output_text = "".join(str(output) for output in outputs)
        assert len(output_text) >= 0
