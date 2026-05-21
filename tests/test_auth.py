# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for password-based authentication support."""

from unittest.mock import patch, MagicMock

import pytest
import requests
from requests.cookies import RequestsCookieJar

from jupyter_mcp_server.auth import JupyterPasswordAuth
from jupyter_mcp_server.config import reset_config, set_config, get_config
from jupyter_mcp_server.server_context import ServerContext


def _patch_session(mock_session_cls):
    """Wire mock_session_cls so `with requests.Session() as session:` yields the mock.

    Returns the inner session mock that test code should configure.
    """
    session = MagicMock()
    mock_session_cls.return_value = session
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


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
        """Successful login extracts cookies from session and authenticates."""
        session = _patch_session(mock_session_cls)
        # Real cookie jar so dict(session.cookies) works naturally
        jar = RequestsCookieJar()
        jar.set("_xsrf", "2|abc123")
        jar.set("username-localhost", "user123")
        session.cookies = jar

        # GET /login (no-op) → POST /login → GET /api/status → 200
        session.get.side_effect = [MagicMock(), MagicMock(status_code=200)]
        session.post.return_value = MagicMock(status_code=302)

        auth = self._make_auth()
        auth.login()

        assert auth._authenticated is True
        assert auth._cookies == {"_xsrf": "2|abc123", "username-localhost": "user123"}
        assert auth._xsrf_token == "2|abc123"

        # POST /login must have included the _xsrf from the initial GET
        post_call = session.post.call_args
        assert post_call.kwargs["data"]["password"] == "secret"
        assert post_call.kwargs["data"]["_xsrf"] == "2|abc123"
        assert post_call.kwargs["allow_redirects"] is False

        headers = auth.get_headers()
        assert headers["X-XSRFToken"] == "2|abc123"
        assert "_xsrf=2|abc123" in headers["Cookie"]
        assert "username-localhost=user123" in headers["Cookie"]

    # -- get_headers ---------------------------------------------------------

    def test_get_headers_not_authenticated(self):
        """get_headers returns empty dict when not authenticated."""
        auth = self._make_auth()
        assert auth.get_headers() == {}

    def test_get_headers_with_xsrf(self):
        """get_headers includes Cookie and X-XSRFToken."""
        auth = self._make_auth()
        auth._authenticated = True
        auth._cookies = {"_xsrf": "token123", "session": "abc"}
        auth._xsrf_token = "token123"

        headers = auth.get_headers()
        assert headers["X-XSRFToken"] == "token123"
        assert "_xsrf=token123" in headers["Cookie"]
        assert "session=abc" in headers["Cookie"]

    def test_get_headers_without_xsrf(self):
        """get_headers omits X-XSRFToken when _xsrf cookie is empty."""
        auth = self._make_auth()
        auth._authenticated = True
        auth._cookies = {"session": "abc"}
        auth._xsrf_token = ""

        headers = auth.get_headers()
        assert "Cookie" in headers
        assert "X-XSRFToken" not in headers

    # -- cookie_header -------------------------------------------------------

    def test_cookie_header_format(self):
        """cookie_header formats cookies correctly."""
        auth = self._make_auth()
        auth._cookies = {"a": "1", "b": "2"}
        assert "a=1" in auth.cookie_header
        assert "b=2" in auth.cookie_header
        assert "; " in auth.cookie_header

    # -- inject_into_session -------------------------------------------------

    def test_inject_into_session(self):
        """inject_into_session sets cookies and X-XSRFToken header."""
        auth = self._make_auth()
        auth._authenticated = True
        auth._cookies = {"_xsrf": "token123", "session": "abc"}
        auth._xsrf_token = "token123"

        session = requests.Session()
        auth.inject_into_session(session)

        assert session.cookies.get("_xsrf") == "token123"
        assert session.cookies.get("session") == "abc"
        assert session.headers.get("X-XSRFToken") == "token123"

    def test_inject_into_session_not_authenticated(self):
        """inject_into_session is a no-op when not authenticated."""
        auth = self._make_auth()
        session = requests.Session()
        original_cookies = dict(session.cookies)

        auth.inject_into_session(session)

        assert dict(session.cookies) == original_cookies

    # -- login error cases ---------------------------------------------------

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_error(self, mock_session_cls):
        """login raises RuntimeError on connection failure."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.side_effect = requests.exceptions.ConnectionError("refused")

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Cannot connect"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_connection_timeout(self, mock_session_cls):
        """login raises RuntimeError on timeout during GET /login."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.side_effect = requests.exceptions.Timeout("slow")

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="Timed out connecting"):
            auth.login(timeout=0.5)

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_server_error_5xx(self, mock_session_cls):
        """5xx from /login surfaces a 'server is failing' message, not an auth message."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.return_value = MagicMock()
        session.post.return_value = MagicMock(status_code=503)

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match=r"503.*server is failing"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_bad_status(self, mock_session_cls):
        """Non-200/302 status from /login is treated as a login failure."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.return_value = MagicMock()
        session.post.return_value = MagicMock(status_code=400)

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="login failed with status 400"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_wrong_password_403(self, mock_session_cls):
        """403 from /api/status verify means cookies didn't authenticate."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.side_effect = [
            MagicMock(),                    # GET /login
            MagicMock(status_code=403),     # GET /api/status → forbidden
        ]
        session.post.return_value = MagicMock(status_code=302)

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="password may be incorrect"):
            auth.login()

    @patch("jupyter_mcp_server.auth.requests.Session")
    def test_login_wrong_password_401(self, mock_session_cls):
        """401 from /api/status verify is also treated as auth failure (not just 403)."""
        session = _patch_session(mock_session_cls)
        session.cookies = RequestsCookieJar()
        session.get.side_effect = [
            MagicMock(),                    # GET /login
            MagicMock(status_code=401),     # GET /api/status → unauthorized
        ]
        session.post.return_value = MagicMock(status_code=302)

        auth = self._make_auth()
        with pytest.raises(RuntimeError, match="password may be incorrect"):
            auth.login()


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

    @pytest.mark.asyncio
    async def test_ws_connect_patched_with_auth_headers(self):
        """When auth_headers present, websocket connect is patched with Cookie header,
        and the original connect is restored after __aenter__ returns."""
        import jupyter_nbmodel_client.client as nbmodel_client_module
        from jupyter_mcp_server.notebook_manager import NotebookConnection

        original_connect = nbmodel_client_module.connect

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
        mock_auth.get_headers.return_value = {
            "Cookie": "_xsrf=tok; session=abc",
            "X-XSRFToken": "tok",
        }
        context._runtime_password_auth = mock_auth
        # Share runtime auth with document since URLs match in this test
        context._document_password_auth = mock_auth
        context._server_client = MagicMock()
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()
        mock_session.cookies.set("_xsrf", "tok")
        mock_session.cookies.set("session", "abc")
        context._server_client.http_client.session = mock_session

        connection = NotebookConnection(
            notebook_info={
                "server_url": "http://localhost:8888",
                "token": None,
                "path": "test.ipynb",
            }
        )

        captured = {}

        # When NbModelClient.__aenter__ is invoked, simulate what the real client
        # does: call the (potentially patched) connect from the nbmodel module.
        async def fake_aenter(self_):
            connect_fn = nbmodel_client_module.connect
            # Call it with no kwargs to verify the wrapper injects additional_headers
            connect_fn("ws://example/socket")
            captured["connect_during_aenter"] = connect_fn
            return self_

        async def fake_aexit(self_, *args):
            return None

        captured_connect_kwargs = {}

        def fake_original_connect(uri, **kwargs):
            captured_connect_kwargs["uri"] = uri
            captured_connect_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "jupyter_mcp_server.notebook_manager.nbmodel_fetch"
        ) as mock_fetch, patch(
            "jupyter_mcp_server.notebook_manager.NbModelClient"
        ) as MockClient, patch(
            "websockets.asyncio.client.connect", side_effect=fake_original_connect
        ):
            mock_fetch.return_value = MagicMock(
                json=MagicMock(return_value={
                    "format": "json",
                    "type": "notebook",
                    "fileId": "abc-123",
                    "sessionId": "sess-456",
                }),
                raise_for_status=MagicMock(),
            )
            mock_notebook = MagicMock()
            mock_notebook.__aenter__ = fake_aenter
            mock_notebook.__aexit__ = fake_aexit
            MockClient.return_value = mock_notebook

            await connection.__aenter__()

        # The connect function used inside __aenter__ should be the wrapper,
        # NOT whatever nbmodel_client_module.connect was before
        assert captured["connect_during_aenter"] is not original_connect
        # The wrapper must inject Cookie via additional_headers
        assert "additional_headers" in captured_connect_kwargs
        assert captured_connect_kwargs["additional_headers"]["Cookie"] == "_xsrf=tok; session=abc"
        # And the wrapper must have been removed after __aenter__ returned
        # (i.e., nbmodel_client_module.connect is no longer the captured wrapper)
        assert nbmodel_client_module.connect is not captured["connect_during_aenter"]

        # Restore manually in case the production code's "restore" target diverged
        # from what was there at test start (it imports connect fresh from websockets,
        # which our patches intercepted).
        nbmodel_client_module.connect = original_connect

    def test_collaboration_session_called_with_auth_headers(self):
        """The PUT /api/collaboration/session request includes Cookie and X-XSRFToken."""
        from jupyter_mcp_server.notebook_manager import _get_jupyter_notebook_ws_url_with_auth

        auth_headers = {
            "Cookie": "_xsrf=mytoken; session=abc",
            "X-XSRFToken": "mytoken",
        }

        with patch("jupyter_mcp_server.notebook_manager.nbmodel_fetch") as mock_fetch:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "format": "json",
                "type": "notebook",
                "fileId": "file-id-123",
                "sessionId": "session-id-456",
            }
            mock_response.raise_for_status = MagicMock()
            mock_fetch.return_value = mock_response

            ws_url = _get_jupyter_notebook_ws_url_with_auth(
                server_url="http://localhost:8888",
                path="test.ipynb",
                auth_headers=auth_headers,
            )

            # Verify fetch was called with merged headers
            mock_fetch.assert_called_once()
            call_kwargs = mock_fetch.call_args
            headers = call_kwargs.kwargs["headers"]
            assert headers["X-XSRFToken"] == "mytoken"
            assert headers["Cookie"] == "_xsrf=mytoken; session=abc"
            assert headers["Accept"] == "application/json"
            assert headers["Content-Type"] == "application/json"
            assert call_kwargs.kwargs["method"] == "PUT"
            assert "token" in call_kwargs.args or call_kwargs.kwargs.get("token") is None

            # Verify the returned WebSocket URL
            assert ws_url.startswith("ws://localhost:8888/api/collaboration/room/")
            assert "sessionId=session-id-456" in ws_url
            assert "json:notebook:file-id-123" in ws_url


# ---------------------------------------------------------------------------
# End-to-end tests against a real password-protected Jupyter server
# ---------------------------------------------------------------------------


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
        async with mcp_client_password:
            result = await mcp_client_password.execute_code("2 + 2")
        assert result is not None
        assert "result" in result
        outputs = result["result"]
        assert any("4" in str(output) for output in outputs)

    @pytest.mark.asyncio
    async def test_password_auth_notebook_operations(self, mcp_client_password):
        """WebSocket collaboration path works with password auth.

        This is the most critical test — it exercises the monkey-patched
        websocket connect that injects Cookie headers into NbModelClient.
        """
        async with mcp_client_password:
            # Connect to the notebook (triggers WebSocket collaboration)
            use_result = await mcp_client_password.use_notebook(
                notebook_name="password_test",
                notebook_path="notebook.ipynb",
                mode="connect",
            )
            assert use_result is not None
            assert "error" not in use_result.lower() if isinstance(use_result, str) else True

            # Read a cell to verify the notebook connection is working
            cell = await mcp_client_password.read_cell(cell_index=0)
            assert cell is not None
