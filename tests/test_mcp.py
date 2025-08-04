# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Python unit tests for jupyter_mcp_server."""

import pytest
import pytest_asyncio
import subprocess
import requests
import logging
import time
from http import HTTPStatus
from requests.exceptions import ConnectionError

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

JUPYTER_TOKEN = "MY_TOKEN"

# TODO: could be retrieved from code (inspect)
JUPYTER_TOOLS = [
    "append_markdown_cell",
    "insert_markdown_cell",
    "overwrite_cell_source",
    "append_execute_code_cell",
    "insert_execute_code_cell",
    "execute_cell_with_progress",
    "execute_cell_simple_timeout",
    "execute_cell_streaming",
    "read_all_cells",
    "read_cell",
    "get_notebook_info",
    "delete_cell",
]


class MCPClient:
    def __init__(self, url):
        self.url = f"{url}/mcp"

    async def list_tools(self):
        async with streamablehttp_client(self.url) as (
            read_stream,
            write_stream,
            _,
        ):
            # Create a session using the client streams
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the connection
                await session.initialize()
                # List available tools
                tools = await session.list_tools()
                return tools


def _start_server(name, host, port, command, readiness_endpoint="/", retries=5):
    _log_prefix = name
    url = f"http://{host}:{port}"
    url_readiness = f"{url}{readiness_endpoint}"
    logging.info(f"{_log_prefix}: starting ...")
    p_serv = subprocess.Popen(command, stdout=subprocess.PIPE)
    _log_prefix = f"{_log_prefix} ({p_serv.pid})"
    while retries > 0:
        try:
            response = requests.get(url_readiness)
            if response is not None and response.status_code == HTTPStatus.OK:
                logging.info(f"{_log_prefix}: started ({url})!")
                yield url
                break
        except ConnectionError:
            logging.debug(f"{_log_prefix}: waiting to accept connections [{retries}]")
            time.sleep(2)
            retries -= 1
    if not retries:
        logging.error(f"{_log_prefix}: fail to start")
    logging.debug(f"{_log_prefix}: stopping ...")
    p_serv.terminate()
    p_serv.wait()
    logging.info(f"{_log_prefix}: stopped")


@pytest_asyncio.fixture(scope="session")
async def mcp_client(jupyter_mcp_server):
    return MCPClient(jupyter_mcp_server)


@pytest.fixture(scope="session")
def jupyter_server():
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
        retries=10,
    )


@pytest.fixture(scope="session")
def jupyter_mcp_server(request, jupyter_server):
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
    tools = await mcp_client.list_tools()
    tools_name = [tool.name for tool in tools.tools]
    logging.debug(tools_name)
    assert len(JUPYTER_TOOLS) == len(tools_name) and sorted(JUPYTER_TOOLS) == sorted(
        tools_name
    )
