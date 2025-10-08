# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Pytest configuration and shared fixtures for Jupyter MCP Server tests.

This module provides:
- jupyter_server fixture: Session-scoped Jupyter Lab server
- jupyter_server_with_extension fixture: Jupyter Lab with MCP extension
- jupyter_mcp_server fixture: Standalone MCP server instance
- mcp_client fixture: MCP protocol client for testing
- _start_server helper: Generic server startup with health checks
- JUPYTER_TOKEN: Authentication token for Jupyter API
"""

import logging
import os
import socket
import subprocess
import time
from http import HTTPStatus

import pytest
import pytest_asyncio
import requests
from requests.exceptions import ConnectionError


JUPYTER_TOKEN = "MY_TOKEN"

# Test mode configuration - set to False to skip testing specific modes
TEST_MCP_SERVER = os.environ.get("TEST_MCP_SERVER", "true").lower() == "true"
TEST_JUPYTER_SERVER = os.environ.get("TEST_JUPYTER_SERVER", "true").lower() == "true"


def _start_server(
    name: str, host: str, port: int, command: list, readiness_endpoint: str, max_retries: int = 5
):
    """A Helper that starts a web server as a python subprocess and wait until it's ready to accept connections

    This method can be used to start both Jupyter and Jupyter MCP servers
    
    Uses subprocess.DEVNULL to prevent pipe blocking issues with verbose output.
    """
    _log_prefix = name
    url = f"http://{host}:{port}"
    url_readiness = f"{url}{readiness_endpoint}"
    logging.info(f"{_log_prefix}: starting ...")
    logging.debug(f"{_log_prefix}: command: {' '.join(command)}")
    
    # Use DEVNULL to prevent any pipe blocking issues
    p_serv = subprocess.Popen(
        command, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    )
    _log_prefix = f"{_log_prefix} [{p_serv.pid}]"
    
    while max_retries > 0:
        # Check if process died
        poll_result = p_serv.poll()
        if poll_result is not None:
            logging.error(f"{_log_prefix}: process died with exit code {poll_result}")
            pytest.fail(f"{name} failed to start (exit code {poll_result}). Check if port {port} is available.")
        
        try:
            response = requests.get(url_readiness, timeout=10)
            if response is not None and response.status_code == HTTPStatus.OK:
                logging.info(f"{_log_prefix}: started ({url})!")
                yield url
                break
        except (ConnectionError, requests.exceptions.Timeout):
            logging.debug(
                f"{_log_prefix}: waiting to accept connections [{max_retries}]"
            )
            time.sleep(2)
            max_retries -= 1
            
    if not max_retries:
        logging.error(f"{_log_prefix}: fail to start after retries. Check if port {port} is available.")
        pytest.fail(f"{name} failed to start after max retries. Port {port} may be in use or server crashed.")
    logging.debug(f"{_log_prefix}: stopping ...")
    try:
        p_serv.terminate()
        p_serv.wait(timeout=5)  # Reduced timeout for faster cleanup
        logging.info(f"{_log_prefix}: stopped")
    except subprocess.TimeoutExpired:
        logging.warning(f"{_log_prefix}: terminate timeout, forcing kill")
        p_serv.kill()
        try:
            p_serv.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logging.error(f"{_log_prefix}: kill timeout, process may be stuck")
    except Exception as e:
        logging.error(f"{_log_prefix}: error during shutdown: {e}")


@pytest.fixture(scope="session")
def jupyter_server():
    """Start the Jupyter server and returns its URL
    
    This is a session-scoped fixture that starts a single Jupyter Lab instance
    for all tests. Both MCP_SERVER and JUPYTER_SERVER mode tests can share this.
    
    Only starts if at least one test mode is enabled.
    """
    if not TEST_MCP_SERVER and not TEST_JUPYTER_SERVER:
        pytest.skip("Both TEST_MCP_SERVER and TEST_JUPYTER_SERVER are disabled")
    
    host = "localhost"
    port = 8888
    yield from _start_server(
        name="JupyterLab",
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
def jupyter_server_with_extension():
    """Start Jupyter server with MCP extension loaded (JUPYTER_SERVER mode)
    
    This fixture starts Jupyter Lab with the jupyter_mcp_server extension enabled,
    allowing tests to verify JUPYTER_SERVER mode functionality (YDoc, direct kernel access, etc).
    
    Only starts if TEST_JUPYTER_SERVER=True, otherwise skips.
    """
    if not TEST_JUPYTER_SERVER:
        pytest.skip("TEST_JUPYTER_SERVER is disabled")
    
    host = "localhost"
    port = 8889  # Different port to avoid conflicts
    yield from _start_server(
        name="JupyterLab+MCP",
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
            # Load the MCP extension
            "--ServerApp.jpserver_extensions",
            '{"jupyter_mcp_server": True}',
        ],
        readiness_endpoint="/api",
        max_retries=10,
    )


###############################################################################
# MCP Server Fixtures
###############################################################################

@pytest.fixture(scope="function")
def jupyter_mcp_server(request, jupyter_server):
    """Start the Jupyter MCP server and returns its URL
    
    This fixture starts a standalone MCP server that communicates with Jupyter
    via HTTP (MCP_SERVER mode). It can be parametrized to control runtime startup.
    
    Parameters:
        request.param (bool): Whether to start a new kernel runtime (default: True)
    """
    # Find an available port
    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
    
    host = "localhost"
    port = find_free_port()
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


def _get_test_params():
    """Generate test parameters based on TEST_MCP_SERVER and TEST_JUPYTER_SERVER flags"""
    params = []
    if TEST_MCP_SERVER:
        params.append("mcp_server")
    if TEST_JUPYTER_SERVER:
        params.append("jupyter_extension")
    
    if not params:
        pytest.skip("Both TEST_MCP_SERVER and TEST_JUPYTER_SERVER are disabled")
    
    return params


@pytest.fixture(scope="function", params=_get_test_params())
def mcp_server_url(request):
    """Parametrized fixture that provides both MCP_SERVER and JUPYTER_SERVER mode URLs
    
    This fixture enables testing the same functionality against both deployment modes:
    - mcp_server: Standalone MCP server (HTTP transport) - when TEST_MCP_SERVER=True
    - jupyter_extension: Jupyter extension mode (direct API access) - when TEST_JUPYTER_SERVER=True
    
    Both expose MCP protocol endpoints that can be tested with MCPClient.
    
    You can control which modes to test via environment variables:
        TEST_MCP_SERVER=true/false (default: true)
        TEST_JUPYTER_SERVER=true/false (default: true)
    
    Parameters:
        request.param (str): Either "mcp_server" or "jupyter_extension"
    
    Returns:
        str: URL of the MCP endpoint for the selected mode
    """
    if request.param == "mcp_server":
        # Get jupyter_server fixture dynamically
        jupyter_server = request.getfixturevalue("jupyter_server")
        
        # Start standalone MCP server
        import socket
        def find_free_port():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                s.listen(1)
                port = s.getsockname()[1]
            return port
        
        host = "localhost"
        port = find_free_port()
        
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
                "True",
                "--runtime-token",
                JUPYTER_TOKEN,
                "--port",
                str(port),
            ],
            readiness_endpoint="/api/healthz",
        )
    else:  # jupyter_extension
        # Get jupyter_server_with_extension fixture dynamically
        jupyter_server_with_extension = request.getfixturevalue("jupyter_server_with_extension")
        # Use the extension's MCP endpoints (note: no /mcp suffix, the extension handles routing)
        yield jupyter_server_with_extension


###############################################################################


@pytest_asyncio.fixture(scope="function")
async def mcp_client(jupyter_mcp_server):
    """An MCP client that can connect to the Jupyter MCP server
    
    This fixture provides an MCPClient instance configured to connect to
    the standalone MCP server. It requires the test_common module.
    
    Returns:
        MCPClient: Configured client for MCP protocol communication
    """
    from .test_common import MCPClient
    return MCPClient(jupyter_mcp_server)


@pytest.fixture(scope="function")
def mcp_client_parametrized(mcp_server_url):
    """MCP client that works with both server modes via parametrization
    
    This fixture creates an MCPClient that can connect to either:
    - Standalone MCP server (MCP_SERVER mode)
    - Jupyter extension MCP endpoints (JUPYTER_SERVER mode)
    
    Returns:
        MCPClient: Configured client for the parametrized server mode
    """
    from .test_common import MCPClient
    return MCPClient(mcp_server_url)
