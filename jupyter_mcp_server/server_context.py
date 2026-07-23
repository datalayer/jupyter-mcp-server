# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Singleton to cache server mode and context managers.
"""

from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.log import logger
from jupyter_mcp_server.tools import ServerMode
from jupyter_server_client import JupyterServerClient


class ServerContext:
    """Singleton to cache server mode and context managers."""
    _instance = None
    _mode = None
    _contents_manager = None
    _kernel_manager = None
    _kernel_spec_manager = None
    _session_manager = None
    _server_client = None
    _kernel_client = None
    _runtime_password_auth = None
    _document_password_auth = None
    _initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton instance. Use this when config changes.

        Closes any active password-auth sessions so their connection pools
        are released rather than waiting for GC.
        """
        if cls._instance is not None:
            cls._instance._close_auth()
            cls._instance._initialized = False
            cls._instance._mode = None
            cls._instance._contents_manager = None
            cls._instance._kernel_manager = None
            cls._instance._kernel_spec_manager = None
            cls._instance._session_manager = None
            cls._instance._server_client = None
            cls._instance._kernel_client = None

    def _close_auth(self):
        """Close auth sessions if present; safe to call multiple times.

        Document auth may be the same instance as runtime auth (shared session
        when URLs match), so guard against double-close.
        """
        runtime = self._runtime_password_auth
        document = self._document_password_auth
        self._runtime_password_auth = None
        self._document_password_auth = None
        if runtime is not None:
            runtime.close()
        if document is not None and document is not runtime:
            document.close()

    def _init_mcp_server_mode(self):
        """Initialize MCP_SERVER mode with HTTP client and optional password auth.

        Sets up up to two password-auth sessions:
        - `_runtime_password_auth` for the runtime server (kernel ops).
        - `_document_password_auth` for the document server (collaboration API).
        When runtime and document URLs point to the same server, the runtime
        auth is reused for document operations to avoid a redundant login.

        On any failure partway through, closes whatever auth sessions were
        created so we don't leak.
        """
        self._mode = ServerMode.MCP_SERVER
        config = get_config()

        runtime_url = config.runtime_url
        if not runtime_url or runtime_url in ("None", "none", "null", ""):
            raise ValueError(
                f"runtime_url is not configured (current value: {repr(runtime_url)}). "
                "Please check:\n"
                "1. RUNTIME_URL environment variable is set correctly (not the string 'None')\n"
                "2. --runtime-url argument is provided when starting the server\n"
                "3. The MCP client configuration passes runtime_url correctly"
            )

        logger.info(f"Initializing MCP_SERVER mode with runtime_url: {runtime_url}")

        from jupyter_mcp_server.auth import JupyterPasswordAuth

        try:
            # Runtime auth — password takes precedence over token
            if config.runtime_password:
                self._runtime_password_auth = JupyterPasswordAuth(runtime_url, config.runtime_password)
                self._runtime_password_auth.login()
                if config.runtime_token:
                    logger.warning("Both runtime_password and runtime_token are set. Password auth takes precedence.")
                self._server_client = JupyterServerClient(base_url=runtime_url, token=None)
                self._runtime_password_auth.inject_into_session(self._server_client.http_client.session)
            else:
                self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)

            # Document auth — only needed when the document server is explicitly
            # different from the runtime server. When URLs match (or document_url
            # is unset/falsy and would default to runtime), reuse the runtime auth.
            document_url = config.document_url
            urls_match = (not document_url) or (document_url == runtime_url)
            if urls_match:
                self._document_password_auth = self._runtime_password_auth
            elif config.document_password:
                self._document_password_auth = JupyterPasswordAuth(document_url, config.document_password)
                self._document_password_auth.login()
                if config.document_token:
                    logger.warning("Both document_password and document_token are set. Password auth takes precedence.")
            elif config.runtime_password and not config.document_token:
                # Document server is genuinely different but only runtime_password is set —
                # the runtime cookies won't authenticate there.
                logger.warning(
                    "document_url (%s) differs from runtime_url (%s) but no document_password "
                    "is configured. Collaboration API requests will not be authenticated. "
                    "Set --document-password (or DOCUMENT_PASSWORD), or --document-token.",
                    document_url, runtime_url,
                )
        except BaseException:
            self._close_auth()
            raise

    def initialize(self):
        """Initialize context once.

        Tries to detect a Jupyter-extension context (JUPYTER_SERVER mode).
        Falls back to MCP_SERVER mode ONLY when the extension's context module
        cannot be imported — any other exception during mode setup (config
        errors, login failures, etc.) propagates to the caller.
        """
        if self._initialized:
            return

        try:
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
        except ImportError:
            # Not running under jupyter-extension — fall back to MCP_SERVER mode.
            self._init_mcp_server_mode()
        else:
            context = get_server_context()
            if context.is_local_document() and context.get_contents_manager() is not None:
                self._mode = ServerMode.JUPYTER_SERVER
                self._contents_manager = context.get_contents_manager()
                self._kernel_manager = context.get_kernel_manager()
                self._kernel_spec_manager = context.get_kernel_spec_manager() if hasattr(context, 'get_kernel_spec_manager') else None
                self._session_manager = context.get_session_manager() if hasattr(context, 'get_session_manager') else None
            else:
                self._init_mcp_server_mode()

        self._initialized = True
        logger.info(f"Server mode initialized: {self._mode}")
    
    @property
    def mode(self):
        if not self._initialized:
            self.initialize()
        return self._mode
    
    @property
    def contents_manager(self):
        if not self._initialized:
            self.initialize()
        return self._contents_manager
    
    @property
    def kernel_manager(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_manager
    
    @property
    def kernel_spec_manager(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_spec_manager
    
    @property
    def session_manager(self):
        if not self._initialized:
            self.initialize()
        return self._session_manager
    
    @property
    def server_client(self):
        if not self._initialized:
            self.initialize()
        return self._server_client
    
    @property
    def kernel_client(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_client

    @property
    def runtime_auth_headers(self) -> dict[str, str]:
        """Auth headers for the runtime server (kernel operations).

        Empty dict when no runtime password auth is configured. When password
        auth is active, reads the latest cookies from the JupyterServerClient
        session (which the server may have refreshed) rather than the stale
        login-time snapshot.
        """
        if not self._initialized:
            self.initialize()
        if self._runtime_password_auth is None:
            return {}
        if self._server_client is not None:
            session = self._server_client.http_client.session
            cookies = dict(session.cookies)
            if cookies:
                cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())
                headers = {"Cookie": cookie_header}
                xsrf = cookies.get("_xsrf", "")
                if xsrf:
                    headers["X-XSRFToken"] = xsrf
                return headers
        # Fall back to login-time headers
        return self._runtime_password_auth.get_headers()

    @property
    def document_auth_headers(self) -> dict[str, str]:
        """Auth headers for the document server (collaboration API).

        When runtime_url == document_url, this returns the same fresh headers
        as `runtime_auth_headers` (single shared session). When the document
        server is separate, returns the login-time headers from the dedicated
        document auth.
        """
        if not self._initialized:
            self.initialize()
        if self._document_password_auth is None:
            return {}
        # Shared session with runtime — read fresh cookies from the runtime client
        if self._document_password_auth is self._runtime_password_auth:
            return self.runtime_auth_headers
        return self._document_password_auth.get_headers()

    def relogin_runtime(self, timeout: float = 10.0) -> None:
        """Re-authenticate the runtime server session after cookie expiry.

        Calls `relogin()` on the runtime auth instance and re-injects the fresh
        cookies into the JupyterServerClient session so subsequent HTTP requests
        (kernel management, etc.) carry valid credentials.

        No-op when no runtime password auth is configured.
        """
        if self._runtime_password_auth is None:
            return
        self._runtime_password_auth.relogin(timeout=timeout)
        if self._server_client is not None:
            self._runtime_password_auth.inject_into_session(
                self._server_client.http_client.session
            )
        logger.info("Runtime session re-authenticated after cookie expiry.")

    def relogin_document(self, timeout: float = 10.0) -> None:
        """Re-authenticate the document server session after cookie expiry.

        When runtime and document auth are shared (same URL), delegates to
        `relogin_runtime()` so the shared session is only re-established once.
        For a separate document auth instance, re-logins independently.

        No-op when no document password auth is configured.
        """
        if self._document_password_auth is None:
            return
        if self._document_password_auth is self._runtime_password_auth:
            self.relogin_runtime(timeout=timeout)
            return
        self._document_password_auth.relogin(timeout=timeout)
        logger.info("Document session re-authenticated after cookie expiry.")

    @property
    def auth_headers(self) -> dict[str, str]:
        """Backwards-compatible alias for runtime_auth_headers.

        Prefer `runtime_auth_headers` or `document_auth_headers` explicitly.
        """
        return self.runtime_auth_headers
    
    def is_jupyterlab_mode(self) -> bool:
        """Check if JupyterLab mode is enabled."""
        from jupyter_mcp_server.config import get_config
        config = get_config()
        return config.is_jupyterlab_mode()