# Copyright (c) 2024- Datalayer, Inc.
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
import uuid
from http import HTTPStatus

import nbformat
import pytest
import pytest_asyncio
import requests
from requests.exceptions import ConnectionError


JUPYTER_TOKEN = "MY_TOKEN"


def _find_free_port():
    """Return an OS-assigned ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


# Test mode configuration - set to False to skip testing specific modes
TEST_MCP_SERVER = os.environ.get("TEST_MCP_SERVER", "true").lower() == "true"
TEST_JUPYTER_SERVER = os.environ.get("TEST_JUPYTER_SERVER", "true").lower() == "true"


def _start_server(
    name: str, host: str, port: int, command: list, readiness_endpoint: str,
    max_retries: int = 5, extra_env: dict | None = None,
    stderr_file: str | None = None,
):
    """A Helper that starts a web server as a python subprocess and wait until it's ready to accept connections

    This method can be used to start both Jupyter and Jupyter MCP servers

    Uses subprocess.DEVNULL to prevent pipe blocking issues with verbose output.
    When *extra_env* is provided the subprocess inherits ``os.environ`` merged
    with those extra variables (without polluting the parent process).
    When *stderr_file* is provided, stderr is captured to that file for diagnostics.
    """
    _log_prefix = name
    url = f"http://{host}:{port}"
    url_readiness = f"{url}{readiness_endpoint}"
    logging.info(f"{_log_prefix}: starting ...")
    logging.info(f"{_log_prefix}: command: {' '.join(command)}")

    env = {**os.environ, **extra_env} if extra_env else None

    # Use DEVNULL to prevent any pipe blocking issues.
    # When stderr_file is set, capture stderr for diagnostics instead.
    stderr_fh = None
    if stderr_file:
        stderr_fh = open(stderr_file, "w")  # noqa: SIM115
    p_serv = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=stderr_fh or subprocess.DEVNULL,
        env=env,
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
    finally:
        if stderr_fh:
            stderr_fh.close()
            # Dump captured stderr to the test log for diagnostics
            try:
                with open(stderr_file) as f:
                    content = f.read().strip()
                if content:
                    for line in content.splitlines()[:50]:
                        logging.info(f"{_log_prefix} stderr: {line}")
            except Exception:
                pass


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
    port = _find_free_port()
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


###############################################################################
# Helpers – build commands and shared parametrized logic
###############################################################################


def _jupyter_extension_command(host, port, otel_file=""):
    """Build the ``jupyter lab`` command with the MCP extension enabled."""
    cmd = [
        "jupyter", "lab",
        "--port", str(port),
        "--IdentityProvider.token", JUPYTER_TOKEN,
        "--ip", host,
        "--ServerApp.root_dir", "./dev/content",
        "--no-browser",
        "--ServerApp.jpserver_extensions", '{"jupyter_mcp_server": True}',
    ]
    if otel_file:
        cmd += ["--JupyterMCPServerExtensionApp.otel_file", otel_file]
    return cmd


def _mcp_server_command(jupyter_url, port, otel_file=""):
    """Build the standalone MCP server command."""
    cmd = [
        "python", "-m", "jupyter_mcp_server",
        "--transport", "streamable-http",
        "--document-url", jupyter_url,
        "--document-id", "notebook.ipynb",
        "--document-token", JUPYTER_TOKEN,
        "--runtime-url", jupyter_url,
        "--start-new-runtime", "True",
        "--runtime-token", JUPYTER_TOKEN,
        # Below we use the same token for simplicity in tests.
        # The separation tested in test_mcp_token_rejects_runtime_token()
        "--mcp-token", JUPYTER_TOKEN, 
        "--port", str(port),
    ]
    if otel_file:
        cmd += ["--otel-file", otel_file]
    return cmd


def _get_test_params():
    """Generate test parameters based on TEST_MCP_SERVER and TEST_JUPYTER_SERVER flags."""
    params = []
    if TEST_MCP_SERVER:
        params.append("mcp_server")
    if TEST_JUPYTER_SERVER:
        params.append("jupyter_extension")
    if not params:
        pytest.skip("Both TEST_MCP_SERVER and TEST_JUPYTER_SERVER are disabled")
    return params


def _yield_mcp_url(request, extension_fixture, name_suffix="", otel_file=""):
    """Shared generator for the parametrized ``mcp_server_url*`` fixtures.

    * ``"mcp_server"``      – spins up a standalone MCP server subprocess.
    * ``"jupyter_extension"`` – yields the URL from *extension_fixture*.
    """
    if request.param == "mcp_server":
        jupyter_server = request.getfixturevalue("jupyter_server")
        host = "localhost"
        port = _find_free_port()
        yield from _start_server(
            name=f"Jupyter MCP{name_suffix}",
            host=host,
            port=port,
            command=_mcp_server_command(jupyter_server, port, otel_file=otel_file),
            readiness_endpoint="/api/healthz",
        )
    else:  # jupyter_extension
        yield request.getfixturevalue(extension_fixture)


###############################################################################
# Jupyter server fixtures
###############################################################################


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
    port = _find_free_port()
    yield from _start_server(
        name="JupyterLab+MCP",
        host=host,
        port=port,
        command=_jupyter_extension_command(host, port),
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
    host = "localhost"
    port = _find_free_port()
    start_new_runtime = True
    try:
        start_new_runtime = request.param
    except AttributeError:
        pass

    yield from _start_server(
        name="Jupyter MCP",
        host=host,
        port=port,
        command=[
            "python", "-m", "jupyter_mcp_server",
            "--transport", "streamable-http",
            "--document-url", jupyter_server,
            "--document-id", "notebook.ipynb",
            "--document-token", JUPYTER_TOKEN,
            "--runtime-url", jupyter_server,
            "--start-new-runtime", str(start_new_runtime),
            "--runtime-token", JUPYTER_TOKEN,
            # Below we use the same token for simplicity in tests.
            # The separation tested in test_mcp_token_rejects_runtime_token()
            "--mcp-token", JUPYTER_TOKEN,
            "--port", str(port),
        ],
        readiness_endpoint="/api/healthz",
    )


@pytest.fixture(scope="function", params=_get_test_params())
def mcp_server_url(request):
    """Parametrized fixture that provides both MCP_SERVER and JUPYTER_SERVER mode URLs

    This fixture enables testing the same functionality against both deployment modes:
    - mcp_server: Standalone MCP server (HTTP transport) - when TEST_MCP_SERVER=True
    - jupyter_extension: Jupyter extension mode (direct API access) - when TEST_JUPYTER_SERVER=True

    You can control which modes to test via environment variables:
        TEST_MCP_SERVER=true/false (default: true)
        TEST_JUPYTER_SERVER=true/false (default: true)

    Parameters:
        request.param (str): Either "mcp_server" or "jupyter_extension"

    Returns:
        str: URL of the MCP endpoint for the selected mode
    """
    yield from _yield_mcp_url(request, "jupyter_server_with_extension")


###############################################################################
# Client fixtures
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
    return MCPClient(jupyter_mcp_server, token=JUPYTER_TOKEN)


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
    return MCPClient(mcp_server_url, token=JUPYTER_TOKEN)


###############################################################################
# OTel-isolated fixtures
#
# These mirror the non-OTel fixtures above but pass --otel-file / traitlet
# args to each subprocess, so OTel is never active globally.
###############################################################################


@pytest.fixture(scope="session")
def otel_spans_file(tmp_path_factory):
    """Temp JSONL file for OTel spans – shared by all OTel fixtures."""
    return str(tmp_path_factory.mktemp("otel") / "spans.jsonl")


@pytest.fixture(scope="session")
def jupyter_server_with_extension_otel(otel_spans_file, tmp_path_factory):
    """JupyterLab with MCP extension + OTel (port 8890)."""
    if not TEST_JUPYTER_SERVER:
        pytest.skip("TEST_JUPYTER_SERVER is disabled")

    host = "localhost"
    port = _find_free_port()
    stderr_log = str(tmp_path_factory.mktemp("otel_diag") / "extension_stderr.log")
    yield from _start_server(
        name="JupyterLab+MCP+OTel",
        host=host,
        port=port,
        command=_jupyter_extension_command(host, port, otel_file=otel_spans_file),
        readiness_endpoint="/api",
        max_retries=10,
        stderr_file=stderr_log,
    )


@pytest.fixture(scope="function", params=_get_test_params())
def mcp_server_url_otel(request, otel_spans_file):
    """Parametrized MCP URL – both modes, with OTel enabled."""
    yield from _yield_mcp_url(
        request, "jupyter_server_with_extension_otel",
        name_suffix=" (OTel)",
        otel_file=otel_spans_file,
    )


@pytest.fixture(scope="function")
def mcp_client_otel(mcp_server_url_otel):
    """MCPClient talking to an OTel-enabled server (both modes)."""
    from .test_common import MCPClient
    return MCPClient(mcp_server_url_otel, token=JUPYTER_TOKEN)


###############################################################################
# Password-auth fixtures (e2e tests for password-based authentication)
###############################################################################

JUPYTER_PASSWORD = "test-password-e2e"


@pytest.fixture(scope="session")
def jupyter_password_root_dir(tmp_path_factory):
    """Isolated root directory for the password-auth Jupyter server.

    Tests write their own scratch notebooks here instead of into the repo's
    ``./dev/content`` (which holds notebooks that ship with the repo).
    """
    return tmp_path_factory.mktemp("jupyter_password_content")


@pytest.fixture(scope="session")
def jupyter_server_password(jupyter_password_root_dir):
    """Start a Jupyter server with both a password and a token configured.

    The password is set via ``jupyter server password`` hashing. A token is also
    configured on purpose: token and password are independent mechanisms, so this
    verifies the MCP server authenticates via password (the only credential it is
    given) even when the server still accepts a token — the real-world scenario,
    and it avoids leaving the server with no authentication at all.
    """
    if not TEST_MCP_SERVER:
        pytest.skip("TEST_MCP_SERVER is disabled — password e2e tests only run in MCP_SERVER mode")

    from jupyter_server.auth import passwd
    password_hash = passwd(JUPYTER_PASSWORD)

    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="JupyterLab (password)",
        host=host,
        port=port,
        command=[
            "jupyter", "lab",
            "--port", str(port),
            "--IdentityProvider.token", JUPYTER_TOKEN,
            "--ServerApp.password", password_hash,
            "--ip", host,
            "--ServerApp.root_dir", str(jupyter_password_root_dir),
            "--no-browser",
        ],
        readiness_endpoint="/login",
        max_retries=10,
    )


@pytest.fixture(scope="function")
def password_notebook(jupyter_password_root_dir):
    """Create a uniquely-named empty notebook in the password server's root dir.

    Yields the notebook filename (relative to the server root). A unique name per
    test avoids cross-test collisions on a shared hardcoded notebook path.
    """
    notebook_name = f"password_test_{uuid.uuid4().hex[:8]}.ipynb"
    notebook_path = jupyter_password_root_dir / notebook_name
    nbformat.write(nbformat.v4.new_notebook(), str(notebook_path))
    yield notebook_name
    notebook_path.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def jupyter_mcp_server_password(jupyter_server_password, password_notebook):
    """Start a standalone MCP server that authenticates to Jupyter via password."""
    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="Jupyter MCP (password)",
        host=host,
        port=port,
        command=[
            "python", "-m", "jupyter_mcp_server",
            "--transport", "streamable-http",
            "--document-url", jupyter_server_password,
            "--document-id", password_notebook,
            "--runtime-url", jupyter_server_password,
            "--start-new-runtime", "True",
            "--jupyter-password", JUPYTER_PASSWORD,
            "--insecure-mcp-noauth",
            "--port", str(port),
        ],
        readiness_endpoint="/api/healthz",
    )


@pytest.fixture(scope="function")
def mcp_client_password(jupyter_mcp_server_password):
    """MCPClient connected to the password-auth MCP server (no Bearer token needed)."""
    from .test_common import MCPClient
    return MCPClient(jupyter_mcp_server_password, token=None)


###############################################################################
# Short-cookie fixtures (session-expiry / re-login tests)
###############################################################################

_COOKIE_TTL_SECONDS = 2


@pytest.fixture(scope="session")
def jupyter_short_cookie_root_dir(tmp_path_factory):
    """Isolated root directory for the short-cookie Jupyter server."""
    return tmp_path_factory.mktemp("jupyter_short_cookie_content")


@pytest.fixture(scope="session")
def jupyter_server_short_cookie(jupyter_short_cookie_root_dir, tmp_path_factory):
    """Jupyter server whose session cookie expires after a few seconds.

    Writes a ``jupyter_server_config.py`` that sets
    ``IdentityProvider.cookie_options = {"expires_days": N}`` where N is a
    tiny fraction of a day, then passes ``JUPYTER_CONFIG_DIR`` so Jupyter
    picks it up.  Used to exercise the re-login path without waiting 30 days.
    """
    if not TEST_MCP_SERVER:
        pytest.skip("TEST_MCP_SERVER is disabled")

    config_dir = tmp_path_factory.mktemp("jupyter_short_cookie_config")

    expires_days = _COOKIE_TTL_SECONDS / (24 * 60 * 60)
    config_py = config_dir / "jupyter_server_config.py"
    config_py.write_text(
        f"c.IdentityProvider.cookie_options = {{'expires_days': {expires_days}}}\n"
    )

    from jupyter_server.auth import passwd
    password_hash = passwd(JUPYTER_PASSWORD)

    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="JupyterLab (short-cookie)",
        host=host,
        port=port,
        command=[
            "jupyter", "lab",
            "--port", str(port),
            "--IdentityProvider.token", JUPYTER_TOKEN,
            "--ServerApp.password", password_hash,
            "--ip", host,
            "--ServerApp.root_dir", str(jupyter_short_cookie_root_dir),
            "--no-browser",
        ],
        readiness_endpoint="/login",
        max_retries=10,
        extra_env={"JUPYTER_CONFIG_DIR": str(config_dir)},
    )
