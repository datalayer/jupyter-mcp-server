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
    _password_auth = None
    _initialized = False
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the singleton instance. Use this when config changes."""
        if cls._instance is not None:
            cls._instance._initialized = False
            cls._instance._mode = None
            cls._instance._contents_manager = None
            cls._instance._kernel_manager = None
            cls._instance._kernel_spec_manager = None
            cls._instance._session_manager = None
            cls._instance._server_client = None
            cls._instance._kernel_client = None
            cls._instance._password_auth = None
    
    def _init_mcp_server_mode(self):
        """Initialize MCP_SERVER mode with HTTP client and optional password auth."""
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

        # Password auth takes precedence over token auth
        if config.runtime_password:
            from jupyter_mcp_server.auth import JupyterPasswordAuth
            self._password_auth = JupyterPasswordAuth(runtime_url, config.runtime_password)
            self._password_auth.login()
            if config.runtime_token:
                logger.warning("Both runtime_password and runtime_token are set. Password auth takes precedence.")
            self._server_client = JupyterServerClient(base_url=runtime_url, token=None)
            self._password_auth.inject_into_session(self._server_client.http_client.session)
        else:
            self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)

    def initialize(self):
        """Initialize context once."""
        if self._initialized:
            return

        try:
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            context = get_server_context()

            if context.is_local_document() and context.get_contents_manager() is not None:
                self._mode = ServerMode.JUPYTER_SERVER
                self._contents_manager = context.get_contents_manager()
                self._kernel_manager = context.get_kernel_manager()
                self._kernel_spec_manager = context.get_kernel_spec_manager() if hasattr(context, 'get_kernel_spec_manager') else None
                self._session_manager = context.get_session_manager() if hasattr(context, 'get_session_manager') else None
            else:
                self._init_mcp_server_mode()
        except (ImportError, Exception) as e:
            if not isinstance(e, (ValueError, RuntimeError)):
                self._init_mcp_server_mode()
            else:
                raise

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
    def auth_headers(self) -> dict[str, str]:
        """Get auth headers for password-based auth (empty dict if using token auth).

        When password auth is active, reads the latest cookies from the
        JupyterServerClient session (which may have been refreshed by the
        server) rather than using the stale login-time snapshot.
        """
        if not self._initialized:
            self.initialize()
        if self._password_auth is not None and self._server_client is not None:
            session = self._server_client.http_client.session
            cookies = dict(session.cookies)
            if cookies:
                cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())
                headers = {"Cookie": cookie_header}
                xsrf = cookies.get("_xsrf", "")
                if xsrf:
                    headers["X-XSRFToken"] = xsrf
                return headers
            # Fall back to login-time headers if session has no cookies
            return self._password_auth.get_headers()
        return {}
    
    def is_jupyterlab_mode(self) -> bool:
        """Check if JupyterLab mode is enabled."""
        from jupyter_mcp_server.config import get_config
        config = get_config()
        return config.is_jupyterlab_mode()