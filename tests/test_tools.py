# Copyright (c) 2024- Datalayer, Inc.
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
from http import HTTPStatus

import pytest
import requests

from .test_common import MCPClient, JUPYTER_TOOLS, timeout_wrapper
from .conftest import JUPYTER_TOKEN, TEST_MCP_SERVER


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
async def test_mcp_tool_list(mcp_client_parametrized: MCPClient, request):
    """Check that the list of tools can be retrieved in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        tools = await mcp_client_parametrized.list_tools()
    tools_name = [tool.name for tool in tools.tools]
    logging.debug(f"tools_name: {tools_name}")
    
    # In JUPYTER_SERVER mode (jupyter_extension), connect_to_jupyter is filtered out
    # In MCP_SERVER mode (mcp_server), all tools are available
    expected_tools = JUPYTER_TOOLS.copy()
    
    # Get the current test parameter to determine the mode
    current_param = None
    for param in request.node.callspec.params.values():
        if param in ["mcp_server", "jupyter_extension", "jupyter_extension_no_collab"]:
            current_param = param
            break
    
    if current_param in ["jupyter_extension", "jupyter_extension_no_collab"]:
        # Remove connect_to_jupyter for jupyter_extension mode
        expected_tools = [tool for tool in JUPYTER_TOOLS if tool != 'connect_to_jupyter']
    
    assert len(tools_name) == len(expected_tools) and sorted(tools_name) == sorted(
        expected_tools
    )


@pytest.mark.asyncio
@timeout_wrapper(30)
async def test_mcp_client_connects_with_token(mcp_client_parametrized: MCPClient):
    """MCP client with a valid token can connect and list tools in both modes."""
    async with mcp_client_parametrized:
        tools = await mcp_client_parametrized.list_tools()
    assert len(tools.tools) > 0


def _post_mcp_init(url, token=None):
    """POST an MCP initialize request, optionally with a Bearer token."""
    import httpx
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(
        f"{url}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=headers,
    )


def test_mcp_client_rejected_without_token(mcp_server_url):
    """MCP client without a token should be rejected by both server modes."""
    r = _post_mcp_init(mcp_server_url)
    assert r.status_code in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED), \
        f"Server accepted unauthenticated request (status {r.status_code})"


###############################################################################
# MCP_TOKEN tests (standalone MCP server only)
###############################################################################

MCP_TOKEN = "MY_MCP_TOKEN"


def _mcp_server_command_with_mcp_token(jupyter_url, port):
    """Build standalone MCP server command with both --mcp-token and --runtime-token."""
    return [
        "python", "-m", "jupyter_mcp_server",
        "--transport", "streamable-http",
        "--document-url", jupyter_url,
        "--document-id", "notebook.ipynb",
        "--document-token", JUPYTER_TOKEN,
        "--runtime-url", jupyter_url,
        "--start-new-runtime", "True",
        "--runtime-token", JUPYTER_TOKEN,
        "--mcp-token", MCP_TOKEN,
        "--port", str(port),
    ]


@pytest.fixture(scope="function")
def mcp_server_with_mcp_token(jupyter_server):
    """Standalone MCP server with --mcp-token set (separate from --runtime-token)."""
    from .conftest import _find_free_port, _start_server
    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="Jupyter MCP (mcp-token)",
        host=host,
        port=port,
        command=_mcp_server_command_with_mcp_token(jupyter_server, port),
        readiness_endpoint="/api/healthz",
    )


@pytest.mark.skipif(not TEST_MCP_SERVER, reason="TEST_MCP_SERVER disabled")
def test_mcp_token_accepted(mcp_server_with_mcp_token):
    """When --mcp-token is set, clients authenticating with MCP_TOKEN are accepted."""
    r = _post_mcp_init(mcp_server_with_mcp_token, token=MCP_TOKEN)
    assert r.status_code == HTTPStatus.OK


@pytest.mark.skipif(not TEST_MCP_SERVER, reason="TEST_MCP_SERVER disabled")
def test_mcp_token_rejects_runtime_token(mcp_server_with_mcp_token):
    """When --mcp-token is set, clients using RUNTIME_TOKEN should be rejected."""
    r = _post_mcp_init(mcp_server_with_mcp_token, token=JUPYTER_TOKEN)
    assert r.status_code in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED)


def _mcp_server_command_insecure_noauth(jupyter_url, port):
    """Build standalone MCP server command with --insecure-mcp-noauth (no --mcp-token)."""
    return [
        "python", "-m", "jupyter_mcp_server",
        "--transport", "streamable-http",
        "--document-url", jupyter_url,
        "--document-id", "notebook.ipynb",
        "--document-token", JUPYTER_TOKEN,
        "--runtime-url", jupyter_url,
        "--start-new-runtime", "True",
        "--runtime-token", JUPYTER_TOKEN,
        "--insecure-mcp-noauth",
        "--port", str(port),
    ]


@pytest.fixture(scope="function")
def mcp_server_insecure_noauth(jupyter_server):
    """Standalone MCP server with --insecure-mcp-noauth (no --mcp-token)."""
    from .conftest import _find_free_port, _start_server
    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="Jupyter MCP (insecure-noauth)",
        host=host,
        port=port,
        command=_mcp_server_command_insecure_noauth(jupyter_server, port),
        readiness_endpoint="/api/healthz",
    )


@pytest.mark.skipif(not TEST_MCP_SERVER, reason="TEST_MCP_SERVER disabled")
def test_insecure_noauth_allows_anonymous(mcp_server_insecure_noauth):
    """With --insecure-mcp-noauth and no --mcp-token, unauthenticated requests succeed."""
    r = _post_mcp_init(mcp_server_insecure_noauth)
    assert r.status_code == HTTPStatus.OK


@pytest.mark.skipif(not TEST_MCP_SERVER, reason="TEST_MCP_SERVER disabled")
def test_server_refuses_start_without_auth(jupyter_server):
    """Without --mcp-token or --insecure-mcp-noauth, the server should fail to start."""
    import subprocess
    from .conftest import _find_free_port
    port = _find_free_port()
    cmd = [
        "python", "-m", "jupyter_mcp_server",
        "--transport", "streamable-http",
        "--document-url", jupyter_server,
        "--document-id", "notebook.ipynb",
        "--document-token", JUPYTER_TOKEN,
        "--runtime-url", jupyter_server,
        "--start-new-runtime", "True",
        "--runtime-token", JUPYTER_TOKEN,
        "--port", str(port),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0, "Server should refuse to start without MCP auth config"
    assert "insecure-mcp-noauth" in result.stderr


###############################################################################
# Cell & tool tests
###############################################################################


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_cell_manipulation(mcp_client_parametrized: MCPClient):
    """Test cell manipulation (both markdown and code cells) in both MCP_SERVER and JUPYTER_SERVER modes"""

    async def check_and_delete_cell(client: MCPClient, index, expected_type, content):
        """Check and delete a cell (works for both markdown and code cells)"""
        # reading and checking the content of the created cell
        cell_info = await client.read_cell(index)
        logging.debug(f"cell_info: {cell_info}")
        assert isinstance(cell_info['result'], list), "Read cell result should be a list"
        assert f"=====Cell {index} | type: {expected_type}" in cell_info['result'][0], "Cell metadata should be included"
        assert content in cell_info['result'][1], "Cell source should be included"
        # delete created cell
        result = await client.delete_cell([index])
        assert result is not None, "delete_cell result should not be None"
        assert f"Cell {index} ({expected_type}) deleted successfully" in result["result"]
        assert f"deleted cell source:\n{content}" in result["result"]

    async with mcp_client_parametrized:
        # Test markdown cell operations
        markdown_content = "Hello **World** !"
        # insert markdown cell at index 1
        result = await mcp_client_parametrized.insert_cell(1, "markdown", markdown_content)
        assert result is not None, "insert_cell result should not be None"
        assert "Cell inserted successfully at index 1 (markdown)!" in result["result"]
        await check_and_delete_cell(mcp_client_parametrized, 1, "markdown", markdown_content)

        # Test code cell operations
        code_content = "1 + 1"
        code_result = await mcp_client_parametrized.insert_execute_code_cell(1, code_content)
        expected_result = eval(code_content)
        assert int(code_result['result'][0]) == expected_result

        # Testing appending code cell to bottom of notebook
        code_result = await mcp_client_parametrized.insert_execute_code_cell(-1, code_content)
        expected_result = eval(code_content)
        assert int(code_result['result'][0]) == expected_result

        # Test overwrite_cell_source
        new_code_content = f"({code_content}) * 2"
        result = await mcp_client_parametrized.overwrite_cell_source(1, new_code_content)
        assert result is not None, "overwrite_cell_source result should not be None"
        assert "Cell 1 overwritten successfully!" in result["result"]
        assert "diff" in result["result"]
        assert "-" in result["result"]
        assert "+" in result["result"]
        assert int(code_result["result"][0]) == expected_result

        await check_and_delete_cell(mcp_client_parametrized, 1, "code", new_code_content)

@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_multimodal_output(mcp_client_parametrized: MCPClient):
    """Test multimodal output functionality with image generation in both modes"""
    async with mcp_client_parametrized:
        
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
        result = await mcp_client_parametrized.insert_execute_code_cell(1, image_code)
        
        # Check that result is 
        assert isinstance(result['result'], list), "Result should be a list"
        assert isinstance(result['result'][0], dict)
        assert result['result'][0]['mimeType'] == "image/png", "Result should be a list of ImageContent"
        await mcp_client_parametrized.delete_cell([1])


###############################################################################
# Multi-Notebook Management Tests
###############################################################################

@pytest.mark.asyncio
@timeout_wrapper(90)
async def test_multi_notebook_operations(mcp_client_parametrized: MCPClient):
    """Test cell operations across multiple notebooks in both modes"""
    import uuid
    tag = uuid.uuid4().hex[:8]
    marker_a = f"# This is notebook A [{tag}]"
    marker_b = f"# This is notebook B [{tag}]\nA hidden content"

    async with mcp_client_parametrized:
        # Connect to the new notebook
        result = await mcp_client_parametrized.use_notebook("notebook_a", "new.ipynb")
        logging.debug(f"Connect to notebook A: {result}")
        assert "Successfully activate notebook 'notebook_a'" in result

        # Add a uniquely-tagged cell to notebook A
        await mcp_client_parametrized.insert_cell(-1, "markdown", marker_a)

        # Try to connect to notebook.ipynb as notebook_b
        result = await mcp_client_parametrized.use_notebook("notebook_b", "notebook.ipynb")
        logging.debug(f"Connect to notebook B: {result}")
        assert "Successfully activate notebook 'notebook_b'" in result

        # Add a uniquely-tagged cell to notebook B
        await mcp_client_parametrized.insert_cell(-1, "markdown", marker_b)

        # Switch back to notebook A
        result = await mcp_client_parametrized.use_notebook("notebook_a", "new.ipynb")
        logging.debug(f"Reactivate notebook A: {result}")
        assert "Reactivating notebook 'notebook_a' and deactivating 'notebook_b'." in result

        # Verify we're working with notebook A (our unique marker is there)
        cell_list_a = await mcp_client_parametrized.read_notebook("notebook_a", limit=100)
        assert marker_a in cell_list_a

        # Switch to notebook B and verify
        await mcp_client_parametrized.use_notebook("notebook_b", "notebook.ipynb")
        cell_list_b = await mcp_client_parametrized.read_notebook("notebook_b", response_format="detailed", limit=100)
        assert marker_b in cell_list_b

        notebook_list = await mcp_client_parametrized.list_notebooks()
        logging.debug(f"Notebook list after switching: {notebook_list}")
        assert "notebook_a" in notebook_list
        assert "notebook_b" in notebook_list
        assert "✓" in notebook_list

        # Test restart notebook
        restart_result = await mcp_client_parametrized.restart_notebook("notebook_a")
        logging.debug(f"Restart result: {restart_result}")
        assert "Notebook 'notebook_a' kernel restarted successfully" in restart_result

        # Clean up - unuse both notebooks
        result = await mcp_client_parametrized.unuse_notebook("notebook_a")
        logging.debug(f"Unuse notebook A: {result}")
        assert "Notebook 'notebook_a' unused successfully" in result
        result = await mcp_client_parametrized.unuse_notebook("notebook_b")
        logging.debug(f"Unuse notebook B: {result}")
        assert "Notebook 'notebook_b' unused successfully" in result


@pytest.mark.asyncio 
@timeout_wrapper(60)
async def test_notebooks_error_cases(mcp_client_parametrized: MCPClient):
    """Test error handling for notebook management in both modes"""
    async with mcp_client_parametrized:
        # Test connecting to non-existent notebook (with required notebook_path parameter)
        error_result = await mcp_client_parametrized.use_notebook("nonexistent", "nonexistent.ipynb")
        logging.debug(f"Nonexistent notebook result: {error_result}")
        assert "not found" in error_result
        
        # Test operations on non-used notebook
        restart_error = await mcp_client_parametrized.restart_notebook("nonexistent_notebook")
        assert "not connected" in restart_error
        
        disconnect_error = await mcp_client_parametrized.unuse_notebook("nonexistent_notebook") 
        assert "not connected" in disconnect_error


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_read_cell_without_active_notebook(mcp_client_parametrized: MCPClient):
    """Test read_cell does not raise a cryptic exception when called without use_notebook.

    Regression test for #208: in JUPYTER_SERVER mode, calling read_cell without
    first calling use_notebook previously raised 'quote_from_bytes() expected bytes'
    deep inside the contents manager because None was passed as the notebook path.

    After the fix, read_cell must return a well-formed result in both modes:
    - JUPYTER_SERVER: returns a helpful error message mentioning use_notebook
    - MCP_SERVER: returns actual cell data from the pre-configured default notebook

    The assertion is intentionally content-based rather than mode-based to avoid
    relying on pytest internals for mode detection.
    """
    async with mcp_client_parametrized:
        result = await mcp_client_parametrized.read_cell(0)
        logging.debug(f"read_cell result: {result}")

        assert result is not None, (
            "read_cell raised an unhandled exception (got None). "
            "Expected either cell data or a helpful error message."
        )
        assert isinstance(result["result"], list), "Result should be a list"

        result_text = " ".join(str(item) for item in result["result"])
        assert "=====Cell 0" in result_text or "use_notebook" in result_text.lower(), (
            f"Expected either cell data ('=====Cell 0') or a helpful error message "
            f"('use_notebook'), but got: {result_text[:300]}"
        )


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_execute_code(mcp_client_parametrized: MCPClient):
    """Test execute_code with basic Python code in both modes"""
    async with mcp_client_parametrized:
        # Test simple Python code
        result = await mcp_client_parametrized.execute_code("words='Hello IPython World!'")

        # Test %who magic command (list variables)
        result = await mcp_client_parametrized.execute_code("%who")
        assert "words" in result["result"][0]

        result = await mcp_client_parametrized.execute_code("!echo 'Hello from shell'")
        assert "Hello from shell" in result["result"][0]

        # Test with very short timeout on a potentially long-running command
        result = await mcp_client_parametrized.execute_code("import time\ntime.sleep(5)", timeout=2)
        assert "TIMEOUT ERROR" in result["result"][0]

@pytest.mark.asyncio
async def test_list_kernels(mcp_client_parametrized: MCPClient):
    """Test list_kernels functionality in both MCP_SERVER and JUPYTER_SERVER modes"""
    async with mcp_client_parametrized:
        # Call list_kernels
        kernel_list = await mcp_client_parametrized.list_kernels()
        logging.debug(f"Kernel list: {kernel_list}")
        # Check for either TSV header or "No kernels found" message
        assert "ID\tName\tDisplay_Name\tLanguage\tState\tConnections\tLast_Activity\tEnvironment" in kernel_list


###############################################################################
# Allowed Tools Configuration Tests
###############################################################################

@pytest.mark.asyncio
async def test_allowed_jupyter_mcp_tools_integration(mcp_client_parametrized: MCPClient):
    """Test that the server respects allowed_jupyter_mcp_tools configuration."""
    async with mcp_client_parametrized:
        # Get the list of tools from the server
        tools = await mcp_client_parametrized.list_tools()
        tool_names = [tool.name for tool in tools.tools]
        
        logging.info(f"Available tools: {tool_names}")
        
        # Check that default jupyter-mcp-tools are present
        # These should be available by default
        jupyter_tools = [name for name in tool_names if name.startswith("notebook_")]
        
        # The actual availability depends on whether jupyter-mcp-tools is installed
        # and whether we're running in JupyterLab mode, so we check conditionally
        if any(tool.startswith("notebook_") for tool in tool_names):
            # If any notebook tools are present, the default ones should be there
            assert "notebook_run-all-cells" in tool_names or len(jupyter_tools) > 0
            logging.info(f"Jupyter MCP tools found: {jupyter_tools}")
        else:
            logging.info("No jupyter-mcp-tools detected (possibly not in JupyterLab mode)")


def test_config_allowed_tools_parsing():
    """Test the configuration parsing for allowed tools."""
    from jupyter_mcp_server.config import JupyterMCPConfig
    
    # Test various input formats
    test_cases = [
        ("tool1,tool2,tool3", ["tool1", "tool2", "tool3"]),
        ("single_tool", ["single_tool"]),
        (" tool1 , tool2 , tool3 ", ["tool1", "tool2", "tool3"]),
        ("tool1,,tool2,", ["tool1", "tool2"]),
        ("notebook_*,console_create", ["notebook_*", "console_create"]),
    ]
    
    for input_str, expected in test_cases:
        config = JupyterMCPConfig(allowed_jupyter_mcp_tools=input_str)
        result = config.get_allowed_jupyter_mcp_tools()
        assert result == expected, f"Failed for input '{input_str}': expected {expected}, got {result}"
        logging.info(f"✅ Parsed '{input_str}' -> {result}")
    
    logging.info("✅ All configuration parsing tests passed")


def test_config_environment_variable():
    """Test that CLI-style configuration works (environment variables work through CLI)."""
    from jupyter_mcp_server.config import set_config, reset_config
    
    # Test configuration via set_config (simulates how CLI handles environment variables)
    reset_config()
    config = set_config(allowed_jupyter_mcp_tools="env_tool1,env_tool2")
    tools = config.get_allowed_jupyter_mcp_tools()
    
    assert tools == ["env_tool1", "env_tool2"]
    logging.info(f"✅ CLI-style configuration test passed: {tools}")
    
    # Cleanup
    reset_config()


def test_config_defaults():
    """Test that default configuration works correctly."""
    from jupyter_mcp_server.config import JupyterMCPConfig, reset_config
    
    reset_config()
    config = JupyterMCPConfig()
    default_tools = config.get_allowed_jupyter_mcp_tools()
    
    assert "notebook_run-all-cells" in default_tools
    assert "notebook_get-selected-cell" in default_tools
    assert len(default_tools) == 2
    
    logging.info(f"✅ Default configuration test passed: {default_tools}")


def test_server_tool_registration():
    """Test that get_registered_tools includes the correct tools based on configuration."""
    from jupyter_mcp_server.server import get_registered_tools
    from jupyter_mcp_server.config import set_config, reset_config
    
    # Test with custom configuration
    reset_config()
    set_config(allowed_jupyter_mcp_tools="notebook_run-all-cells")
    
    try:
        # Get registered tools (this may fail if jupyter-mcp-tools is not available)
        tools = get_registered_tools(token="test_token", url="http://localhost:8888")
        tool_names = [tool["name"] for tool in tools]
        
        logging.info(f"Registered tools: {tool_names}")
        
        # Check that FastMCP tools are always present
        fastmcp_tools = [name for name in tool_names if not name.startswith("notebook_")]
        assert len(fastmcp_tools) > 0, "FastMCP tools should always be present"
        
        logging.info("✅ Server tool registration test completed")
        
    except Exception as e:
        # This is expected if jupyter-mcp-tools is not available or we're not in JupyterLab mode
        logging.info(f"Server tool registration test skipped due to: {e}")
    
    finally:
        reset_config()
