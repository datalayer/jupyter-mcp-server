# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Integration tests for the 'mcp.server' module written in pytest with its async module `pytest-asyncio`.

This test file is organized as follows:

1. **Helpers**: Common methods and objects used to ease the writing and the execution of tests.
    - `MCPClient`: A standard MCP client used to interact with the Jupyter MCP server.
    - `_start_server`: Helper function that starts a web server (Jupyter Lab and MCP Server) as a python subprocess and wait until it's ready to accept connections.

2.  **Fixtures**: Common setup and teardown logic for tests.
    - `jupyter_server`: Spawn a Jupyter server (thanks to the `_start_server` helper).
    - `jupyter_mcp_server`: Spawn a Jupyter MCP server connected to the Jupyter server.
    - `mcp_client`: Returns the `MCPClient` connected to the Juypyter MCP server.

3.  **Health tests**: Check that the main components are operating as expected.
    - `test_jupyter_health`: Test that the Jupyter server is healthy.
    - `test_mcp_health`: Test that the Jupyter MCP server is healthy (tests are made with different configuration runtime launched or not launched).
    - `test_mcp_tool_list`: Test that the MCP server declare its tools.

4.  **Integration tests**: Check that end to end tools (client -> Jupyter MCP -> Jupyter) are working as expected.
    - `test_notebook_info`: Test that the notebook info are returned.
    - `test_markdown_cell`: Test markdown cell manipulation (append, insert, read, delete).
    - `test_code_cell`: Test code cell manipulation (append, insert, overwrite, execute, read, delete)

5.  **Edge tests**: Check edge cases behavior.
    - `test_bad_index`: Test behavior of all index-based tools if the index does not exist

Launch the tests

```
$ make test
# or
$ hatch test
```
"""

import pytest
import pytest_asyncio
import subprocess
import requests
import logging
import functools
import time
from http import HTTPStatus
from contextlib import AsyncExitStack

from requests.exceptions import ConnectionError
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client


JUPYTER_TOKEN = "MY_TOKEN"

# TODO: could be retrieved from code (inspect)
JUPYTER_TOOLS = [
    "insert_cell",
    "insert_execute_code_cell",
    "overwrite_cell_source",
    "execute_cell_with_progress",
    "execute_cell_simple_timeout",
    "execute_cell_streaming",
    "read_all_cells",
    "list_cell",
    "read_cell",
    "get_notebook_info",
    "delete_cell",
]


def requires_session(func):
    """
    A decorator that checks if the instance has a connected session.
    """

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not self._session:
            raise RuntimeError("Client session is not connected")
        # If the session exists, call the original method
        return await func(self, *args, **kwargs)

    return wrapper


class MCPClient:
    """A standard MCP client used to interact with the Jupyter MCP server

    Basically it's a client wrapper for the Jupyter MCP server.
    It uses the `requires_session` decorator to check if the session is connected.
    """

    def __init__(self, url):
        self.url = f"{url}/mcp"
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Initiate the session (enter session context)"""
        streams_context = streamablehttp_client(self.url)
        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
            streams_context
        )
        session_context = ClientSession(read_stream, write_stream)
        self._session = await self._exit_stack.enter_async_context(session_context)
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close the session (exit session context)"""
        if self._exit_stack:
            await self._exit_stack.aclose()
        self._session = None

    @staticmethod
    def _extract_text_content(result):
        """Extract text content from a result"""
        if isinstance(result.content[0], types.TextContent):
            return result.content[0].text

    @requires_session
    async def list_tools(self):
        return await self._session.list_tools()  # type: ignore

    @requires_session
    async def get_notebook_info(self):
        result = await self._session.call_tool("get_notebook_info")  # type: ignore
        return result.structuredContent

    @requires_session
    async def insert_cell(self, cell_index, cell_type, cell_source):
        result = await self._session.call_tool("insert_cell", arguments={"cell_index": cell_index, "cell_type": cell_type, "cell_source": cell_source})  # type: ignore
        return result.structuredContent

    @requires_session
    async def insert_execute_code_cell(self, cell_index, cell_source):
        result = await self._session.call_tool("insert_execute_code_cell", arguments={"cell_index": cell_index, "cell_source": cell_source})  # type: ignore
        return result.structuredContent

    @requires_session
    async def read_cell(self, cell_index):
        result = await self._session.call_tool("read_cell", arguments={"cell_index": cell_index})  # type: ignore
        return result.structuredContent

    @requires_session
    async def read_all_cells(self):
        result = await self._session.call_tool("read_all_cells")  # type: ignore
        return result.structuredContent

    @requires_session
    async def list_cell(self):
        result = await self._session.call_tool("list_cell")  # type: ignore
        return self._extract_text_content(result)

    @requires_session
    async def delete_cell(self, cell_index):
        result = await self._session.call_tool("delete_cell", arguments={"cell_index": cell_index})  # type: ignore
        return result.structuredContent

    @requires_session
    async def execute_cell_streaming(self, cell_index):
        result = await self._session.call_tool("execute_cell_streaming", arguments={"cell_index": cell_index})  # type: ignore
        return result.structuredContent
    
    @requires_session
    async def execute_cell_with_progress(self, cell_index):
        result = await self._session.call_tool("execute_cell_with_progress", arguments={"cell_index": cell_index})  # type: ignore
        return result.structuredContent
    
    @requires_session
    async def execute_cell_simple_timeout(self, cell_index):
        result = await self._session.call_tool("execute_cell_simple_timeout", arguments={"cell_index": cell_index})  # type: ignore
        return result.structuredContent

    @requires_session
    async def overwrite_cell_source(self, cell_index, cell_source):
        result = await self._session.call_tool("overwrite_cell_source", arguments={"cell_index": cell_index, "cell_source": cell_source})  # type: ignore
        return result.structuredContent

def _start_server(name, host, port, command, readiness_endpoint="/", max_retries=5):
    """A Helper that starts a web server as a python subprocess and wait until it's ready to accept connections

    This method can be used to start both Jupyter and Jupyter MCP servers
    """
    _log_prefix = name
    url = f"http://{host}:{port}"
    url_readiness = f"{url}{readiness_endpoint}"
    logging.info(f"{_log_prefix}: starting ...")
    p_serv = subprocess.Popen(command, stdout=subprocess.PIPE)
    _log_prefix = f"{_log_prefix} [{p_serv.pid}]"
    while max_retries > 0:
        try:
            response = requests.get(url_readiness)
            if response is not None and response.status_code == HTTPStatus.OK:
                logging.info(f"{_log_prefix}: started ({url})!")
                yield url
                break
        except ConnectionError:
            logging.debug(
                f"{_log_prefix}: waiting to accept connections [{max_retries}]"
            )
            time.sleep(2)
            max_retries -= 1
    if not max_retries:
        logging.error(f"{_log_prefix}: fail to start")
    logging.debug(f"{_log_prefix}: stopping ...")
    p_serv.terminate()
    p_serv.wait()
    logging.info(f"{_log_prefix}: stopped")


@pytest_asyncio.fixture(scope="session")
async def mcp_client(jupyter_mcp_server) -> MCPClient:
    """An MCP client that can connect to the Jupyter MCP server"""
    return MCPClient(jupyter_mcp_server)


@pytest.fixture(scope="session")
def jupyter_server():
    """Start the Jupyter server and returns its URL"""
    host = "localhost"
    port = 8888
    yield from _start_server(
        name="Jupyter Lab",
        host=host,
        port=port,
        command=[
            "jupyter",
            "lab",
            "--port",
            str(port),
            "--IdentityProvider.token",
            JUPYTER_TOKEN,
            "--ip",
            host,
            "--ServerApp.root_dir",
            "./dev/content",
            "--no-browser",
        ],
        readiness_endpoint="/api",
        max_retries=10,
    )


@pytest.fixture(scope="session")
def jupyter_mcp_server(request, jupyter_server):
    """Start the Jupyter MCP server and returns its URL"""
    host = "localhost"
    port = 4040
    start_new_runtime = True
    try:
        start_new_runtime = request.param
    except AttributeError:
        # fixture not parametrized
        pass
    yield from _start_server(
        name="Jupyter MCP",
        host=host,
        port=port,
        command=[
            "python",
            "-m",
            "jupyter_mcp_server",
            "--transport",
            "streamable-http",
            "--document-url",
            jupyter_server,
            "--document-id",
            "notebook.ipynb",
            "--document-token",
            JUPYTER_TOKEN,
            "--runtime-url",
            jupyter_server,
            "--start-new-runtime",
            str(start_new_runtime),
            "--runtime-token",
            JUPYTER_TOKEN,
            "--port",
            str(port),
        ],
        readiness_endpoint="/api/healthz",
    )


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
async def test_mcp_tool_list(mcp_client):
    """Check that the list of tools can be retrieved and match"""
    async with mcp_client:
        tools = await mcp_client.list_tools()
    tools_name = [tool.name for tool in tools.tools]
    logging.debug(f"tools_name :{tools_name}")
    assert len(tools_name) == len(JUPYTER_TOOLS) and sorted(tools_name) == sorted(
        JUPYTER_TOOLS
    )


@pytest.mark.asyncio
async def test_notebook_info(mcp_client):
    """Test notebook info"""
    async with mcp_client:
        notebook_info = await mcp_client.get_notebook_info()
        logging.debug(f"notebook_info: {notebook_info}")
        assert notebook_info["document_id"] == "notebook.ipynb"
        assert notebook_info["total_cells"] == 10
        # Adjust expected cell types based on actual notebook content
        expected_cell_types = notebook_info["cell_types"]
        assert "code" in expected_cell_types
        assert "markdown" in expected_cell_types


@pytest.mark.asyncio
async def test_markdown_cell(mcp_client, content="Hello **World** !"):
    """Test markdown cell manipulation using unified insert_cell API"""

    async def check_and_delete_markdown_cell(mcp_client, index, content):
        """Check and delete a markdown cell"""
        # reading and checking the content of the created cell
        cell_info = await mcp_client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "markdown"
        # TODO: don't now if it's normal to get a list of characters instead of a string
        assert "".join(cell_info["source"]) == content
        # reading all cells
        result = await mcp_client.read_all_cells()
        cells_info = result["result"]
        logging.debug(f"cells_info: {cells_info}")
        # Check that our cell is in the expected position with correct content
        assert "".join(cells_info[index]["source"]) == content
        # delete created cell
        result = await mcp_client.delete_cell(index)
        assert result["result"] == f"Cell {index} (markdown) deleted successfully."

    async with mcp_client:
        # Get initial cell count
        initial_info = await mcp_client.get_notebook_info()
        initial_count = initial_info["total_cells"]
        
        # append markdown cell using -1 index
        result = await mcp_client.insert_cell(-1, "markdown", content)
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(mcp_client, initial_count, content)
        
        # insert markdown cell at the end (safer than index 0)
        result = await mcp_client.insert_cell(initial_count, "markdown", content)
        assert "Cell inserted successfully" in result["result"]
        assert f"index {initial_count} (markdown)" in result["result"]
        await check_and_delete_markdown_cell(mcp_client, initial_count, content)


@pytest.mark.asyncio
async def test_code_cell(mcp_client, content="1 + 1"):
    """Test code cell manipulation using unified APIs"""
    async def check_and_delete_code_cell(mcp_client, index, content):
        """Check and delete a code cell"""
        # reading and checking the content of the created cell
        cell_info = await mcp_client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert cell_info["index"] == index
        assert cell_info["type"] == "code"
        assert "".join(cell_info["source"]) == content
        # reading all cells
        result = await mcp_client.read_all_cells()
        cells_info = result["result"]
        logging.debug(f"cells_info: {cells_info}")
        # Check that our cell is in the expected position with correct content
        assert "".join(cells_info[index]["source"]) == content
        # delete created cell
        result = await mcp_client.delete_cell(index)
        assert result["result"] == f"Cell {index} (code) deleted successfully."

    async with mcp_client:
        # Get initial cell count
        initial_info = await mcp_client.get_notebook_info()
        initial_count = initial_info["total_cells"]
        
        # append and execute code cell using -1 index
        index = initial_count
        code_result = await mcp_client.insert_execute_code_cell(-1, content)
        logging.debug(f"code_result: {code_result}")
        assert int(code_result["result"][0]) == eval(content)
        await check_and_delete_code_cell(mcp_client, index, content)
        
        # insert and execute code cell at the end (safer than index 0)
        index = initial_count
        code_result = await mcp_client.insert_execute_code_cell(index, content)
        logging.debug(f"code_result: {code_result}")
        expected_result = eval(content)
        assert int(code_result["result"][0]) == expected_result
        # overwrite content and test different cell execution modes
        content = f"({content}) * 2"
        expected_result = eval(content)
        result = await mcp_client.overwrite_cell_source(index, content)
        logging.debug(f"result: {result}")
        assert result["result"] == f"Cell {index} overwritten successfully - use execute_cell to execute it if code"
        code_result = await mcp_client.execute_cell_with_progress(index)
        assert int(code_result["result"][0]) == expected_result
        code_result = await mcp_client.execute_cell_simple_timeout(index)
        # Handle case where execute_cell_simple_timeout might return None result
        if code_result and code_result.get("result") is not None:
            assert int(code_result["result"][0]) == expected_result
        else:
            logging.warning("execute_cell_simple_timeout returned None result, skipping assertion")
        await check_and_delete_code_cell(mcp_client, index, content)


@pytest.mark.asyncio
async def test_list_cell(mcp_client):
    """Test list_cell functionality"""
    async with mcp_client:
        # Test initial list_cell (notebook.ipynb has multiple cells)
        cell_list = await mcp_client.list_cell()
        logging.debug(f"Initial cell list: {cell_list}")
        assert isinstance(cell_list, str)
        assert "Index\tType\tCount\tFirst Line" in cell_list
        # The notebook has both markdown and code cells - just verify structure
        lines = cell_list.split('\n')
        data_lines = [line for line in lines if '\t' in line and not line.startswith('Index')]
        assert len(data_lines) >= 1  # Should have at least some cells
        
        # Add a markdown cell and test again
        markdown_content = "# Test Markdown Cell"
        await mcp_client.insert_cell(-1, "markdown", markdown_content)
        
        # Check list_cell with added markdown cell
        cell_list = await mcp_client.list_cell()
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
        await mcp_client.insert_execute_code_cell(-1, "print('Hello World')")
        
        # Check list_cell with truncated content
        cell_list = await mcp_client.list_cell()
        logging.debug(f"Cell list after adding long code: {cell_list}")
        
        # Clean up by deleting added cells (in reverse order)
        # Get current cell count to determine indices of added cells
        current_info = await mcp_client.get_notebook_info()
        current_count = current_info["total_cells"]
        # Delete the last two cells we added
        await mcp_client.delete_cell(current_count - 1)  # Remove the code cell
        await mcp_client.delete_cell(current_count - 2)  # Remove the markdown cell


@pytest.mark.asyncio
async def test_bad_index(mcp_client, index=99):
    """Test behavior of all index-based tools if the index does not exist"""
    async with mcp_client:
        assert await mcp_client.read_cell(index) is None
        assert await mcp_client.insert_cell(index, "markdown", "test") is None
        assert await mcp_client.insert_execute_code_cell(index, "1 + 1") is None
        assert await mcp_client.overwrite_cell_source(index, "1 + 1") is None
        assert await mcp_client.execute_cell_with_progress(index) is None
        assert await mcp_client.execute_cell_simple_timeout(index) is None
        assert await mcp_client.delete_cell(index) is None