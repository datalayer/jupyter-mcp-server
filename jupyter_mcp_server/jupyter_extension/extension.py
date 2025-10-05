# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter Server Extension for MCP Protocol

This extension exposes MCP tools directly from a running Jupyter Server,
allowing MCP clients to connect to the Jupyter Server's MCP endpoints.
"""

import logging
from traitlets import Unicode, Bool
from jupyter_server.extension.application import ExtensionApp, ExtensionAppJinjaMixin
from jupyter_server.utils import url_path_join
from tornado.wsgi import WSGIContainer
from tornado.web import FallbackHandler

from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.jupyter_extension.handlers import (
    MCPHealthHandler,
    MCPToolsListHandler,
    MCPToolsCallHandler,
)


logger = logging.getLogger(__name__)

import logging
from typing import Optional
from traitlets import Unicode, Bool
from jupyter_server.extension.application import ExtensionApp, ExtensionAppJinjaMixin
from jupyter_server.utils import url_path_join

from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.jupyter_extension.handlers import (
    MCPHealthHandler,
    MCPToolsListHandler,
    MCPToolsCallHandler,
)


logger = logging.getLogger(__name__)


class JupyterMCPServerExtensionApp(ExtensionAppJinjaMixin, ExtensionApp):
    """
    Jupyter Server Extension for MCP Server.
    
    This extension allows MCP clients to connect to Jupyter Server and use
    MCP tools to interact with notebooks and kernels.
    
    Configuration:
        c.JupyterMCPServerExtensionApp.document_url = "local"  # or http://...
        c.JupyterMCPServerExtensionApp.runtime_url = "local"   # or http://...
        c.JupyterMCPServerExtensionApp.document_id = "notebook.ipynb"
    """
    
    # Extension metadata
    name = "jupyter_mcp_server"
    default_url = "/mcp"
    load_other_extensions = True
    
    # Configuration traits
    document_url = Unicode(
        "local",
        config=True,
        help='Document URL - use "local" for local serverapp access or http://... for remote'
    )
    
    runtime_url = Unicode(
        "local",
        config=True,
        help='Runtime URL - use "local" for local serverapp access or http://... for remote'
    )
    
    document_id = Unicode(
        "notebook.ipynb",
        config=True,
        help='Default document ID (notebook path)'
    )
    
    document_token = Unicode(
        "",
        config=True,
        help='Authentication token for document server (if remote)'
    )
    
    runtime_token = Unicode(
        "",
        config=True,
        help='Authentication token for runtime server (if remote)'
    )
    
    provider = Unicode(
        "jupyter",
        config=True,
        help='Provider type for document/runtime'
    )
    
    def initialize_settings(self):
        """
        Initialize extension settings.
        
        This is called during extension loading to set up configuration
        and update the server context.
        """
        # Reduce noise from httpx logging (used by JupyterLab for PyPI extension discovery)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        
        logger.info(f"Initializing Jupyter MCP Server Extension")
        logger.info(f"  Document URL: {self.document_url}")
        logger.info(f"  Runtime URL: {self.runtime_url}")
        logger.info(f"  Document ID: {self.document_id}")
        
        # Update the global server context
        context = get_server_context()
        context.update(
            context_type="JUPYTER_SERVER",
            serverapp=self.serverapp,
            document_url=self.document_url,
            runtime_url=self.runtime_url
        )
        
        # Store configuration in settings for handlers
        self.settings.update({
            "mcp_document_url": self.document_url,
            "mcp_runtime_url": self.runtime_url,
            "mcp_document_id": self.document_id,
            "mcp_document_token": self.document_token,
            "mcp_runtime_token": self.runtime_token,
            "mcp_provider": self.provider,
            "mcp_serverapp": self.serverapp,
        })
        
        logger.info("Jupyter MCP Server Extension settings initialized")
    
    def initialize_handlers(self):
        """
        Register MCP protocol handlers.
        
        Strategy: Implement MCP protocol directly in Tornado handlers that
        call the MCP tools from server.py. This avoids the complexity of
        wrapping the Starlette ASGI app.
        
        Endpoints:
        - GET/POST /mcp - MCP protocol endpoint (SSE-based)
        - GET /mcp/healthz - Health check (Tornado handler)
        - GET /mcp/tools/list - List available tools (Tornado handler)
        - POST /mcp/tools/call - Execute a tool (Tornado handler)
        """
        base_url = self.serverapp.base_url
        
        # Import here to avoid circular imports
        from jupyter_mcp_server.jupyter_extension.handlers import MCPSSEHandler
        
        # Define handlers
        handlers = [
            # MCP protocol endpoint - SSE-based handler
            # Match /mcp with or without trailing slash
            (url_path_join(base_url, "/mcp/?"), MCPSSEHandler),
            # Utility endpoints (optional, for debugging)
            (url_path_join(base_url, "/mcp/healthz"), MCPHealthHandler),
            (url_path_join(base_url, "/mcp/tools/list"), MCPToolsListHandler),
            (url_path_join(base_url, "/mcp/tools/call"), MCPToolsCallHandler),
        ]
        
        # Register handlers
        self.handlers.extend(handlers)
        
        logger.info(f"Registered MCP handlers at {base_url}/mcp/")
        logger.info(f"  - MCP protocol: {base_url}/mcp (SSE-based)")
        logger.info(f"  - Health check: {base_url}/mcp/healthz")
        logger.info(f"  - List tools: {base_url}/mcp/tools/list")
        logger.info(f"  - Call tool: {base_url}/mcp/tools/call")
    
    def initialize_templates(self):
        """
        Initialize Jinja templates.
        
        Not needed for API-only extension, but included for completeness.
        """
        pass
    
    async def stop_extension(self):
        """
        Clean up when extension stops.
        
        Shutdown any managed kernels and cleanup resources.
        """
        logger.info("Stopping Jupyter MCP Server Extension")
        
        # Reset server context
        context = get_server_context()
        context.reset()
        
        logger.info("Jupyter MCP Server Extension stopped")


# Extension loading functions

def _jupyter_server_extension_points():
    """
    Declare the Jupyter Server extension.
    
    Returns:
        List of extension metadata dictionaries
    """
    return [
        {
            "module": "jupyter_mcp_server.jupyter_extension.extension",
            "app": JupyterMCPServerExtensionApp
        }
    ]


def _load_jupyter_server_extension(serverapp):
    """
    Load the extension (for backward compatibility).
    
    Args:
        serverapp: Jupyter ServerApp instance
    """
    extension = JupyterMCPServerExtensionApp()
    extension.serverapp = serverapp
    extension.initialize_settings()
    extension.initialize_handlers()
    extension.initialize_templates()


# For classic Notebook server compatibility
load_jupyter_server_extension = _load_jupyter_server_extension
