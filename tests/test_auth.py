# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for password-based authentication support."""

import asyncio
import time
import uuid
from unittest.mock import patch, MagicMock

import pytest
import requests
from requests.cookies import RequestsCookieJar

from jupyter_mcp_server.auth import JupyterPasswordAuth
from jupyter_mcp_server.config import reset_config, set_config, get_config
from jupyter_mcp_server.server_context import ServerContext


def _patch_session(mock_session_cls):
    """Wire mock_session_cls so `requests.Session()` returns a controllable mock.

    The auth module now uses `session.request(method, url, ...)` for all HTTP
    calls (via `_do_request`), so configure `session.request` rather than
    `session.get` / `session.post`. Returns the mock session.
    """
    session = MagicMock()
    mock_session_cls.return_value = session
    return session


def _make_response(status_code: int = 200, text: str = "") -> MagicMock:
    """Build a MagicMock response with a real `.text` attribute.

    `auth._truncate` reads `response.text`; we set it explicitly so error-path
    tests don't accidentally feed a MagicMock into string ops.
    """
    response = MagicMock(spec_set=["status_code", "text"])
    response.status_code = status_code
    response.text = text
    return response


def _request_responses(*responses):
    """Build a side_effect that yields the given responses in order.

    Mix of HTTP responses (MagicMock-like) and exceptions.
    """
    iterator = iter(responses)

    def side_effect(method, url, **kwargs):
        value = next(iterator)
        if isinstance(value, BaseException):
            raise value
        return value

    return side_effect


# ---------------------------------------------------------------------------
# JupyterPasswordAuth unit tests
# ---------------------------------------------------------------------------


class TestJupyterPasswordAuth:
    """Tests for the JupyterPasswordAuth login flow."""

    def _make_auth(self, url="http://localhost:8888", password="secret"):
        return JupyterPasswordAuth(url, password)

    # -- login success -------------------------------------------------------

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_success(self, mock_session_cls):
        """Successful login keeps the session alive and exposes live cookies."""
        session = _patch_session(mock_session_cls)
        jar = RequestsCookieJar()
        jar.set("_xsrf", "2|abc123")
        jar.set("username-localhost", "user123")
        session.cookies = jar

        # GET /login, POST /login (302), GET /api/status (200)
        session.request.side_effect = _request_responses(
            MagicMock(),                      # GET /login
            MagicMock(status_code=302),       # POST /login
            MagicMock(status_code=200),       # GET /api/status
        )

        auth = self._make_auth()
        auth.login()

        assert auth._authenticated is True
        assert auth._session is session  # session kept alive
        assert auth._xsrf_token == "2|abc123"

        # POST /login must include the _xsrf token and disable redirects
        post_call = session.request.call_args_list[1]
        assert post_call.args[0] == "POST"
        assert post_call.kwargs["data"]["password"] == "secret"
        assert post_call.kwargs["data"]["_xsrf"] == "2|abc123"
        assert post_call.kwargs["allow_redirects"] is False
        # Initial GET /login must also disable redirects (cross-origin guard)
        get_call = session.request.call_args_list[0]
        assert get_call.args[0] == "GET"
        assert get_call.kwargs["allow_redirects"] is False

        headers = auth.get_headers()
        assert headers["X-XSRFToken"] == "2|abc123"
        assert "_xsrf=2|abc123" in headers["Cookie"]
        assert "username-localhost=user123" in headers["Cookie"]

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_get_headers_returns_live_cookies(self, mock_session_cls):
        """get_headers reflects cookies set on the session AFTER login."""
        session = _patch_session(mock_session_cls)
        jar = RequestsCookieJar()
        jar.set("_xsrf", "initial")
        session.cookies = jar
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=200),
        )

        auth = self._make_auth()
        auth.login()

        # Simulate the server rotating a cookie post-login
        jar.set("_xsrf", "rotated")
        jar.set("new", "value")

        headers = auth.get_headers()
        assert headers["X-XSRFToken"] == "rotated"
        assert "new=value" in headers["Cookie"]

    # -- get_headers ---------------------------------------------------------

    def test_get_headers_not_authenticated(self):
        """get_headers returns empty dict when not authenticated."""
        auth = self._make_auth()
        assert auth.get_headers() == {}

    def test_get_headers_without_xsrf_in_jar(self):
        """get_headers omits X-XSRFToken when no _xsrf cookie is present."""
        auth = self._make_auth()
        auth._authenticated = True
        session = requests.Session()
        session.cookies.set("session", "abc")
        auth._session = session

        headers = auth.get_headers()
        assert "Cookie" in headers
        assert "session=abc" in headers["Cookie"]
        assert "X-XSRFToken" not in headers

    # -- inject_into_session -------------------------------------------------

    def test_inject_into_session(self):
        """inject_into_session copies live cookies but NOT a stale XSRF header."""
        auth = self._make_auth()
        auth._authenticated = True
        src_session = requests.Session()
        src_session.cookies.set("_xsrf", "token123")
        src_session.cookies.set("session", "abc")
        auth._session = src_session

        target = requests.Session()
        auth.inject_into_session(target)

        assert target.cookies.get("_xsrf") == "token123"
        assert target.cookies.get("session") == "abc"
        # X-XSRFToken is deliberately NOT injected as a default header; it must
        # be set per-request from the live cookie jar so cookie rotation works.
        assert "X-XSRFToken" not in target.headers

    def test_inject_into_session_not_authenticated(self):
        """inject_into_session is a no-op when not authenticated."""
        auth = self._make_auth()
        target = requests.Session()
        original_cookies = dict(target.cookies)

        auth.inject_into_session(target)

        assert dict(target.cookies) == original_cookies

    # -- close ---------------------------------------------------------------

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_close_clears_state(self, mock_session_cls):
        session = _patch_session(mock_session_cls)
        jar = RequestsCookieJar()
        jar.set("_xsrf", "x")
        session.cookies = jar
        session.request.side_effect = _request_responses(
            MagicMock(), MagicMock(status_code=302), MagicMock(status_code=200),
        )

        auth = self._make_auth()
        auth.login()
        auth.close()
        session.close.assert_called_once()
        assert auth._session is None
        assert auth._authenticated is False

    # -- login error cases ---------------------------------------------------

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_error_on_initial_get(self, mock_session_cls):
        """ConnectionError on initial GET surfaces as RuntimeError."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = requests.exceptions.ConnectionError("refused")

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Connection error"):
            auth.login()
        # Session must be closed on failure
        session.close.assert_called_once()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_error_on_post(self, mock_session_cls):
        """ConnectionError on POST /login also surfaces as RuntimeError."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            requests.exceptions.ConnectionError("reset"),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Connection error.*POST"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_error_on_verify(self, mock_session_cls):
        """ConnectionError on /api/status verify also surfaces as RuntimeError."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            requests.exceptions.ConnectionError("reset during verify"),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Connection error.*api/status"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_timeout(self, mock_session_cls):
        """Timeout on GET /login surfaces as RuntimeError."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = requests.exceptions.Timeout("slow")

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Timed out"):
            auth.login(timeout=0.5)

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_server_error_5xx_on_login(self, mock_session_cls):
        """5xx from /login surfaces a 'server is failing' message."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=503),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match=r"503.*server is failing"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_server_error_5xx_on_verify(self, mock_session_cls):
        """5xx from /api/status is also classified as server failure, not auth."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=502),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match=r"502.*server is failing"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_bad_status(self, mock_session_cls):
        """Non-200/302 status from /login is treated as a login failure."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=400),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="login failed with status 400"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_wrong_password_403(self, mock_session_cls):
        """403 from /api/status verify means cookies didn't authenticate."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=403),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="password may be incorrect"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_wrong_password_401(self, mock_session_cls):
        """401 from /api/status verify is also treated as auth failure (not just 403)."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=401),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="password may be incorrect"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_unexpected_verify_status(self, mock_session_cls):
        """Non-200/4xx/5xx from /api/status (e.g. 3xx redirect) is its own error."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.cookies.set("_xsrf", "tok")  # set so we don't hit the missing-xsrf raise
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=302),  # /api/status redirect (unexpected)
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match=r"Unexpected status 302"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_error_includes_response_body(self, mock_session_cls):
        """Login failures surface a (truncated) response body for debuggability."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.request.side_effect = _request_responses(
            _make_response(),
            _make_response(status_code=400, text="<html>Bad password!</html>"),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Bad password"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_fails_when_no_xsrf_cookie(self, mock_session_cls):
        """Login that succeeds at HTTP level but leaves no _xsrf cookie must fail fast."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()  # never sets _xsrf
        session.request.side_effect = _request_responses(
            MagicMock(),
            MagicMock(status_code=302),
            MagicMock(status_code=200),
        )

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="no _xsrf cookie"):
            auth.login()
        # Session is closed on failure
        session.close.assert_called_once()


# ---------------------------------------------------------------------------
# Config password fields
# ---------------------------------------------------------------------------


class TestPasswordConfig:
    """Tests for password fields in JupyterMCPConfig."""

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_password_fields_default_none(self):
        config = get_config()
        assert config.runtime_password is None
        assert config.document_password is None

    def test_set_password(self):
        config = set_config(runtime_password="secret", document_password="other")
        assert config.runtime_password == "secret"
        assert config.document_password == "other"

    def test_password_normalization_none_string(self):
        """String 'None' is normalized to actual None."""
        config = set_config(runtime_password="None", document_password="null")
        assert config.runtime_password is None
        assert config.document_password is None

    def test_password_normalization_empty_string(self):
        """Empty string is normalized to actual None."""
        config = set_config(runtime_password="", document_password="")
        assert config.runtime_password is None
        assert config.document_password is None


# ---------------------------------------------------------------------------
# ServerContext auth_headers tests
# ---------------------------------------------------------------------------


class TestServerContextAuthHeaders:
    """Tests for ServerContext.auth_headers property."""

    def setup_method(self):
        reset_config()
        ServerContext.reset()
        # Ensure a fresh singleton
        ServerContext._instance = None

    def teardown_method(self):
        reset_config()
        ServerContext.reset()
        ServerContext._instance = None

    def test_auth_headers_empty_without_password(self):
        """auth_headers returns {} when no password is configured."""
        set_config(runtime_url="http://localhost:8888", runtime_token="mytoken")
        context = ServerContext.get_instance()
        # Manually set up MCP_SERVER mode without password
        from jupyter_mcp_server.tools import ServerMode
        context._mode = ServerMode.MCP_SERVER
        context._runtime_password_auth = None
        context._server_client = MagicMock()
        context._initialized = True

        assert context.auth_headers == {}

    def test_auth_headers_reads_from_session_cookies(self):
        """auth_headers reads fresh cookies from JupyterServerClient session."""
        from jupyter_mcp_server.tools import ServerMode

        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True

        # Set up a mock password auth and server client
        mock_auth = MagicMock()
        mock_auth.get_headers.return_value = {"Cookie": "old=stale", "X-XSRFToken": "old"}
        context._runtime_password_auth = mock_auth

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()
        mock_session.cookies.set("_xsrf", "fresh_token")
        mock_session.cookies.set("username-localhost", "user1")
        mock_client.http_client.session = mock_session
        context._server_client = mock_client

        headers = context.auth_headers
        assert "X-XSRFToken" in headers
        assert headers["X-XSRFToken"] == "fresh_token"
        assert "_xsrf=fresh_token" in headers["Cookie"]
        assert "username-localhost=user1" in headers["Cookie"]

    def test_auth_headers_falls_back_to_login_headers(self):
        """auth_headers falls back to login-time headers if session has no cookies."""
        from jupyter_mcp_server.tools import ServerMode

        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True

        mock_auth = MagicMock()
        mock_auth.get_headers.return_value = {"Cookie": "login=cookie", "X-XSRFToken": "login_xsrf"}
        context._runtime_password_auth = mock_auth

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()  # empty jar
        mock_client.http_client.session = mock_session
        context._server_client = mock_client

        headers = context.auth_headers
        assert headers == {"Cookie": "login=cookie", "X-XSRFToken": "login_xsrf"}

    def test_auth_headers_triggers_initialize(self):
        """auth_headers triggers initialize() when not yet initialized (the bug we fixed)."""
        set_config(runtime_url="http://localhost:8888")
        context = ServerContext.get_instance()
        assert context._initialized is False

        # Patch _init_mcp_server_mode to avoid real HTTP calls
        with patch.object(context, "_init_mcp_server_mode") as mock_init:
            _ = context.auth_headers
            mock_init.assert_called_once()

    def test_reset_clears_password_auth(self):
        """ServerContext.reset() clears both runtime and document password auth."""
        context = ServerContext.get_instance()
        context._runtime_password_auth = MagicMock()
        context._document_password_auth = MagicMock()
        context._initialized = True

        ServerContext.reset()

        assert context._runtime_password_auth is None
        assert context._document_password_auth is None
        assert context._initialized is False

    def test_document_auth_headers_shares_runtime_when_urls_match(self):
        """When document and runtime URLs match, document auth reuses runtime session."""
        from jupyter_mcp_server.tools import ServerMode

        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True

        shared_auth = MagicMock()
        shared_auth.get_headers.return_value = {"Cookie": "stale", "X-XSRFToken": "stale"}
        context._runtime_password_auth = shared_auth
        context._document_password_auth = shared_auth  # same instance → shared

        mock_client = MagicMock()
        jar = RequestsCookieJar()
        jar.set("_xsrf", "fresh")
        jar.set("session", "fresh-session")
        mock_client.http_client.session.cookies = jar
        context._server_client = mock_client

        # document_auth_headers should return the FRESH runtime cookies,
        # not the stale login-time snapshot
        headers = context.document_auth_headers
        assert headers["X-XSRFToken"] == "fresh"
        assert "_xsrf=fresh" in headers["Cookie"]

    def test_document_auth_headers_separate_when_urls_differ(self):
        """When document and runtime URLs differ, document auth uses its own session."""
        from jupyter_mcp_server.tools import ServerMode

        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True

        runtime_auth = MagicMock()
        runtime_auth.get_headers.return_value = {"Cookie": "runtime=cookie"}
        document_auth = MagicMock()
        document_auth.get_headers.return_value = {"Cookie": "doc=cookie", "X-XSRFToken": "doc-xsrf"}

        context._runtime_password_auth = runtime_auth
        context._document_password_auth = document_auth  # different instance

        mock_client = MagicMock()
        mock_client.http_client.session.cookies = RequestsCookieJar()
        context._server_client = mock_client

        # document_auth_headers should come from document_auth, not runtime
        headers = context.document_auth_headers
        assert headers == {"Cookie": "doc=cookie", "X-XSRFToken": "doc-xsrf"}

    def test_document_auth_headers_empty_without_password(self):
        """document_auth_headers returns {} when no document password configured."""
        from jupyter_mcp_server.tools import ServerMode

        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True
        context._runtime_password_auth = None
        context._document_password_auth = None

        assert context.document_auth_headers == {}


# ---------------------------------------------------------------------------
# NotebookConnection auth headers tests
# ---------------------------------------------------------------------------


class TestNotebookConnectionAuth:
    """Tests for auth header injection in NotebookConnection."""

    def setup_method(self):
        reset_config()
        ServerContext.reset()
        ServerContext._instance = None

    def teardown_method(self):
        reset_config()
        ServerContext.reset()
        ServerContext._instance = None

    def _make_password_auth_connection(self):
        """Set up MCP_SERVER mode with shared runtime/document password auth and
        return a NotebookConnection whose document_auth_headers resolve to the
        fresh session cookies (Cookie: ``_xsrf=tok; session=abc``)."""
        from jupyter_mcp_server.notebook_manager import NotebookConnection

        set_config(
            runtime_url="http://localhost:8888",
            document_url="http://localhost:8888",
            runtime_password="secret",
            provider="jupyter",
        )

        from jupyter_mcp_server.tools import ServerMode
        context = ServerContext.get_instance()
        context._mode = ServerMode.MCP_SERVER
        context._initialized = True
        mock_auth = MagicMock()
        context._runtime_password_auth = mock_auth
        # Share runtime auth with document since URLs match in this test
        context._document_password_auth = mock_auth
        context._server_client = MagicMock()
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()
        mock_session.cookies.set("_xsrf", "tok")
        mock_session.cookies.set("session", "abc")
        context._server_client.http_client.session = mock_session

        return NotebookConnection(
            notebook_info={
                "server_url": "http://localhost:8888",
                "token": None,
                "path": "test.ipynb",
            }
        )

    @pytest.mark.asyncio
    async def test_nbmodel_client_receives_cookie_in_additional_headers(self):
        """When auth_headers present, NbModelClient is constructed with the Cookie
        header so the WebSocket handshake carries the password session cookie."""
        connection = self._make_password_auth_connection()

        async def fake_aenter(self_):
            return self_

        async def fake_aexit(self_, *args):
            return None

        with patch(
            "jupyter_mcp_server.notebook_manager.get_notebook_websocket_url",
            return_value="ws://localhost:8888/api/collaboration/room/abc",
        ), patch(
            "jupyter_mcp_server.notebook_manager.NbModelClient"
        ) as MockClient:
            mock_notebook = MagicMock()
            mock_notebook.__aenter__ = fake_aenter
            mock_notebook.__aexit__ = fake_aexit
            MockClient.return_value = mock_notebook

            await connection.__aenter__()

        # The WebSocket handshake carries only the Cookie, not the XSRF token.
        assert MockClient.call_args.kwargs["additional_headers"] == {
            "Cookie": "_xsrf=tok; session=abc"
        }

    @pytest.mark.asyncio
    async def test_collaboration_session_url_called_with_auth_headers(self):
        """The collaboration-session URL request carries Cookie and X-XSRFToken,
        forwarded to get_notebook_websocket_url via the headers kwarg."""
        connection = self._make_password_auth_connection()

        async def fake_aenter(self_):
            return self_

        async def fake_aexit(self_, *args):
            return None

        with patch(
            "jupyter_mcp_server.notebook_manager.get_notebook_websocket_url",
            return_value="ws://localhost:8888/api/collaboration/room/abc",
        ) as mock_ws_url, patch(
            "jupyter_mcp_server.notebook_manager.NbModelClient"
        ) as MockClient:
            mock_notebook = MagicMock()
            mock_notebook.__aenter__ = fake_aenter
            mock_notebook.__aexit__ = fake_aexit
            MockClient.return_value = mock_notebook

            await connection.__aenter__()

        assert mock_ws_url.call_args.kwargs["headers"] == {
            "Cookie": "_xsrf=tok; session=abc",
            "X-XSRFToken": "tok",
        }
        assert mock_ws_url.call_args.kwargs["provider"] == "jupyter"


# ---------------------------------------------------------------------------
# End-to-end tests against a real password-protected Jupyter server
# ---------------------------------------------------------------------------


async def _read_cell_until(mcp_client, cell_index, expected_substring, timeout=30.0, interval=0.5):
    """Read a cell repeatedly until ``expected_substring`` appears, or timeout.

    In MCP_SERVER mode both execute and read go through the collaboration YDoc,
    which is eventually consistent: a kernel's outputs are applied to the shared
    document slightly *after* insert_execute_code_cell returns. A single read can
    therefore race ahead of the sync and see the cell with no output yet
    ("execution count: N/A"). Poll the read-back so the round-trip assertion is
    robust to that lag under load, while still failing if the output never syncs.
    """
    deadline = time.monotonic() + timeout
    cell = await mcp_client.read_cell(cell_index=cell_index)
    while expected_substring not in str(cell) and time.monotonic() < deadline:
        await asyncio.sleep(interval)
        cell = await mcp_client.read_cell(cell_index=cell_index)
    return cell


class TestPasswordAuthE2E:
    """E2E tests that spin up a real Jupyter server with password auth
    and verify the full MCP flow works end-to-end.

    These tests use the ``mcp_client_password`` fixture which starts:
    1. A JupyterLab server with password auth (no token)
    2. A standalone MCP server configured with --jupyter-password
    3. An MCPClient connected to the MCP server
    """

    @pytest.mark.asyncio
    async def test_password_auth_health(self, jupyter_mcp_server_password):
        """MCP server health endpoint works when authenticated via password."""
        import requests
        response = requests.get(f"{jupyter_mcp_server_password}/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_password_auth_list_tools(self, mcp_client_password):
        """MCP protocol list_tools works with password auth."""
        async with mcp_client_password:
            tools = await mcp_client_password.list_tools()
        tool_names = [tool.name for tool in tools.tools]
        assert "execute_code" in tool_names
        assert "use_notebook" in tool_names

    @pytest.mark.asyncio
    async def test_password_auth_execute_code(self, mcp_client_password):
        """KernelClient works with password cookie/XSRF auth."""
        # Multiply two large ints so the expected value can't appear incidentally
        # in an error message or unrelated output (a bare "4" easily could).
        factor_a, factor_b = 98765, 43210
        expected_product = str(factor_a * factor_b)
        async with mcp_client_password:
            result = await mcp_client_password.execute_code(f"{factor_a} * {factor_b}")
        assert result is not None
        assert "result" in result
        outputs = result["result"]
        assert any(expected_product in str(output) for output in outputs), (
            f"expected product {expected_product} not found in outputs: {outputs}"
        )

    @pytest.mark.asyncio
    async def test_password_auth_create_notebook(
        self, mcp_client_password, jupyter_password_root_dir
    ):
        """Creating a notebook via mode="create" works under password auth.

        Creating a notebook is a state-changing PUT to /api/contents, which
        Jupyter's XSRF protection guards. The injected session carries the
        _xsrf cookie but not the matching X-XSRFToken header; without the header
        the create POST fails with "403: '_xsrf' argument missing from POST".
        This exercises the header-echo fix and is the create-mode counterpart to
        test_password_auth_notebook_operations (which only covers connect).
        """
        notebook_name = f"created_{uuid.uuid4().hex[:8]}.ipynb"
        notebook_path = jupyter_password_root_dir / notebook_name
        try:
            async with mcp_client_password:
                create_result = await mcp_client_password.use_notebook(
                    notebook_name="created_test",
                    notebook_path=notebook_name,
                    mode="create",
                )
                assert isinstance(create_result, str)
                assert "error" not in create_result.lower(), (
                    f"use_notebook(mode='create') returned an error: {create_result}"
                )
                assert "_xsrf" not in create_result, (
                    f"create hit the XSRF check: {create_result}"
                )
                # The file must actually exist on the server's disk.
                assert notebook_path.exists(), (
                    f"notebook was not created on disk at {notebook_path}"
                )

                # A round-trip over the freshly-created notebook should work too.
                factor_a, factor_b = 31337, 71993
                expected_product = str(factor_a * factor_b)
                await mcp_client_password.insert_execute_code_cell(
                    0, f"{factor_a} * {factor_b}"
                )
                cell = await _read_cell_until(mcp_client_password, 0, expected_product)
                assert expected_product in str(cell), (
                    f"expected product {expected_product} not found in cell: {cell}"
                )
        finally:
            notebook_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_password_auth_notebook_operations(self, mcp_client_password, password_notebook):
        """WebSocket collaboration path works with password auth.

        This is the most critical test — it exercises the Cookie header that
        NbModelClient injects into the WebSocket handshake via additional_headers.
        It drives a full round-trip over the collaboration WebSocket: insert and
        execute a cell, then read its output back, verifying actual content
        rather than merely a non-null read.
        """
        factor_a, factor_b = 13577, 24683
        expected_product = str(factor_a * factor_b)
        async with mcp_client_password:
            # Connect to the notebook (triggers WebSocket collaboration)
            use_result = await mcp_client_password.use_notebook(
                notebook_name="password_test",
                notebook_path=password_notebook,
                mode="connect",
            )
            assert isinstance(use_result, str)
            assert "error" not in use_result.lower(), f"use_notebook returned an error: {use_result}"

            # Insert + execute a cell over the WebSocket collaboration path...
            await mcp_client_password.insert_execute_code_cell(0, f"{factor_a} * {factor_b}")

            # ...and read it back to confirm the round-trip produced the right output.
            cell = await _read_cell_until(mcp_client_password, 0, expected_product)
            assert cell is not None
            assert expected_product in str(cell), (
                f"expected product {expected_product} not found in cell: {cell}"
            )


# ---------------------------------------------------------------------------
# Session-expiry / re-login tests
# ---------------------------------------------------------------------------


class TestSessionExpiry:
    """Tests that verify behaviour when a password-auth session cookie expires.

    ``jupyter_server_short_cookie`` starts a Jupyter server whose session cookie
    is configured to expire after a very short TTL (``_COOKIE_TTL_SECONDS``).
    """

    def test_expired_cookie_causes_auth_failure(self, jupyter_server_short_cookie):
        """After the cookie TTL elapses, GET /api/status returns 401 or 403.

        This is the red test that proves expiry actually breaks the session —
        a prerequisite for any re-login logic being meaningful.
        """
        import time
        from tests.conftest import JUPYTER_PASSWORD, _COOKIE_TTL_SECONDS

        auth = JupyterPasswordAuth(jupyter_server_short_cookie, JUPYTER_PASSWORD)
        auth.login()

        # Sanity-check: session works immediately after login.
        initial = auth._session.get(f"{jupyter_server_short_cookie}/api/status")
        assert initial.status_code == 200, (
            f"Expected 200 right after login, got {initial.status_code}"
        )

        # Wait for the cookie to expire.
        time.sleep(_COOKIE_TTL_SECONDS + 1)

        # The session cookie has expired; the request should now be rejected.
        expired = auth._session.get(f"{jupyter_server_short_cookie}/api/status")
        assert expired.status_code in (401, 403), (
            f"Expected 401/403 after cookie expiry, got {expired.status_code}"
        )

        auth.close()

    def test_relogin_restores_session_after_expiry(self, jupyter_server_short_cookie):
        """relogin() obtains a fresh session and subsequent requests succeed."""
        import time
        from tests.conftest import JUPYTER_PASSWORD, _COOKIE_TTL_SECONDS

        auth = JupyterPasswordAuth(jupyter_server_short_cookie, JUPYTER_PASSWORD)
        auth.login()

        time.sleep(_COOKIE_TTL_SECONDS + 1)

        # Confirm the session is stale.
        assert auth._session.get(
            f"{jupyter_server_short_cookie}/api/status"
        ).status_code in (401, 403)

        # Re-login and verify the session is working again.
        auth.relogin()
        restored = auth._session.get(f"{jupyter_server_short_cookie}/api/status")
        assert restored.status_code == 200, (
            f"Expected 200 after relogin, got {restored.status_code}"
        )

        auth.close()

    @pytest.mark.asyncio
    async def test_notebook_operations_recover_after_session_expiry(
        self, jupyter_server_short_cookie, jupyter_short_cookie_root_dir
    ):
        """Notebook collaboration operations succeed even after the session cookie
        expires, because NotebookConnection auto-relogs on 401/403.

        The MCP server is started fresh against the short-cookie Jupyter server so
        it logs in at startup, then the test waits for the cookie to expire before
        attempting a notebook operation.
        """
        import time
        import uuid
        import nbformat
        from tests.conftest import (
            _find_free_port,
            _start_server,
            JUPYTER_PASSWORD,
            _COOKIE_TTL_SECONDS,
        )
        from tests.test_common import MCPClient

        factor_a, factor_b = 47293, 81637
        expected_product = str(factor_a * factor_b)
        notebook_name = f"relogin_test_{uuid.uuid4().hex[:8]}.ipynb"
        notebook_path = jupyter_short_cookie_root_dir / notebook_name
        nbformat.write(nbformat.v4.new_notebook(), str(notebook_path))

        host = "localhost"
        port = _find_free_port()
        for mcp_url in _start_server(
            name="MCP (relogin test)",
            host=host,
            port=port,
            command=[
                "python", "-m", "jupyter_mcp_server",
                "--transport", "streamable-http",
                "--document-url", jupyter_server_short_cookie,
                "--document-id", notebook_name,
                "--runtime-url", jupyter_server_short_cookie,
                "--start-new-runtime", "True",
                "--jupyter-password", JUPYTER_PASSWORD,
                "--insecure-mcp-noauth",
                "--port", str(port),
            ],
            readiness_endpoint="/api/healthz",
        ):
            # Wait for the session cookie to expire before making notebook calls.
            time.sleep(_COOKIE_TTL_SECONDS + 1)

            async with MCPClient(mcp_url, token=None) as client:
                use_result = await client.use_notebook(
                    notebook_name="relogin_test",
                    notebook_path=notebook_name,
                    mode="connect",
                )
                assert "error" not in str(use_result).lower(), (
                    f"use_notebook failed after session expiry: {use_result}"
                )
                await client.insert_execute_code_cell(0, f"{factor_a} * {factor_b}")
                cell = await client.read_cell(cell_index=0)
                assert expected_product in str(cell), (
                    f"Expected product {expected_product} not found in cell: {cell}"
                )
        notebook_path.unlink(missing_ok=True)
