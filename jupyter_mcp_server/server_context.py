# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Singleton to cache server mode and context managers.
"""

from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.log import logger
from jupyter_mcp_server.tools import ServerMode
from jupyter_server_api import JupyterServerClient


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
                self._mode = ServerMode.MCP_SERVER
                # Initialize HTTP clients for MCP_SERVER mode
                config = get_config()
                
                # Validate that runtime_url is set and not None/empty
                # Note: String "None" values should have been normalized by start_command()
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
                self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)
                # kernel_client will be created lazily when needed
        except (ImportError, Exception) as e:
            # If not in Jupyter context, use MCP_SERVER mode
            if not isinstance(e, ValueError):
                self._mode = ServerMode.MCP_SERVER
                # Initialize HTTP clients for MCP_SERVER mode
                config = get_config()
                
                # Validate that runtime_url is set and not None/empty
                # Note: String "None" values should have been normalized by start_command()
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
                self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)
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