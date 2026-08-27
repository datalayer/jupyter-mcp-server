# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter Server Extension for MCP Protocol

This extension exposes MCP tools directly from a running Jupyter Server,
allowing MCP clients to connect to the Jupyter Server's MCP endpoints.
"""

import logging

from jupyter_server.extension.application import ExtensionApp, ExtensionAppJinjaMixin
from jupyter_server.utils import url_path_join
from traitlets import Bool, Unicode

from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.jupyter_extension.handlers import (
    MCPHealthHandler,
    MCPToolsCallHandler,
    MCPToolsListHandler,
)

logger = logging.getLogger(__name__)


class JupyterMCPServerExtensionApp(ExtensionAppJinjaMixin, ExtensionApp):
    """
    Jupyter Server Extension for MCP Server.

    This extension allows MCP clients to connect to Jupyter Server and use
    MCP tools to interact with notebooks and kernels.

    Configuration:
        c.JupyterMCPServerExtensionApp.document_url = "local"  # or http://...
        c.JupyterMCPServerExtensionApp.code_sandbox_url = "local"   # or http://...
        c.JupyterMCPServerExtensionApp.document_id = "notebook.ipynb"
        c.JupyterMCPServerExtensionApp.start_new_code_sandbox = True  # Start new kernel
        c.JupyterMCPServerExtensionApp.code_sandbox_id = "kernel-id"  # Or connect to existing
    """

    # Extension metadata
    name = "jupyter_mcp_server"
    default_url = "/mcp"
    load_other_extensions = True

    # Configuration traits
    document_url = Unicode(
        "local",
        config=True,
        help='Document URL - use "local" for local serverapp access or http://... for remote',
    )

    code_sandbox_url = Unicode(
        "local",
        config=True,
        help='Runtime URL - use "local" for local serverapp access or http://... for remote',
    )

    document_id = Unicode("notebook.ipynb", config=True, help="Default document ID (notebook path)")

    start_new_code_sandbox = Bool(
        False, config=True, help="Whether to start a new kernel code sandbox on initialization"
    )

    code_sandbox_id = Unicode(
        "", config=True, help="Existing kernel ID to connect to (if not starting new code sandbox)"
    )

    document_token = Unicode(
        "", config=True, help="Authentication token for document server (if remote)"
    )

    code_sandbox_token = Unicode(
        "", config=True, help="Authentication token for code sandbox server (if remote)"
    )

    document_provider = Unicode(
        "jupyter",
        config=True,
        help="Which backend holds the notebook documents: 'jupyter' or 'datalayer'",
    )

    jupyterlab = Bool(True, config=True, help="Enable JupyterLab mode (defaults to True)")

    open_notebook_in_ui = Bool(
        False,
        config=True,
        help="Open the notebook in the JupyterLab UI when using it, which activates its tab (defaults to False)",
    )

    allowed_jupyter_mcp_tools = Unicode(
        "notebook_run-all-cells,notebook_get-selected-cell",
        config=True,
        help="Comma-separated list of jupyter-mcp-tools to enable",
    )
    otel_file = Unicode(
        "",
        config=True,
        help="Path to JSONL file for OpenTelemetry span export. "
        "Falls back to JUPYTER_MCP_OTEL_FILE env var when empty.",
    )

    def initialize_settings(self):
        """
        Initialize extension settings.

        This is called during extension loading to set up configuration
        and update the server context.
        """
        # Reduce noise from httpx logging (used by JupyterLab for PyPI extension discovery)
        logging.getLogger("httpx").setLevel(logging.WARNING)

        # Auto-register OTel hook handler if configured (traitlet → env var fallback)
        from jupyter_mcp_server.otel_hook import maybe_register_otel

        logger.info(f"  OTel file (traitlet): {self.otel_file!r}")
        maybe_register_otel(self.otel_file or None)

        logger.info("Initializing Jupyter MCP Server Extension")
        logger.info(f"  Document URL: {self.document_url}")
        logger.info(f"  Runtime URL: {self.code_sandbox_url}")
        logger.info(f"  Document ID: {self.document_id}")
        logger.info(f"  Start New Runtime: {self.start_new_code_sandbox}")
        logger.info(f"  JupyterLab Mode: {self.jupyterlab}")
        logger.info(f"  Open Notebook in UI: {self.open_notebook_in_ui}")
        if self.code_sandbox_id:
            logger.info(f"  Runtime ID: {self.code_sandbox_id}")

        # Update the global server context
        context = get_server_context()
        context.update(
            context_type="JUPYTER_SERVER",
            serverapp=self.serverapp,
            document_url=self.document_url,
            code_sandbox_url=self.code_sandbox_url,
            jupyterlab=self.jupyterlab,
        )

        # Update global MCP configuration
        from jupyter_mcp_server.config import get_config

        config = get_config()
        config.document_url = self.document_url
        config.code_sandbox_url = self.code_sandbox_url
        config.document_id = self.document_id
        config.document_token = self.document_token if self.document_token else None
        config.code_sandbox_token = self.code_sandbox_token if self.code_sandbox_token else None
        config.start_new_code_sandbox = self.start_new_code_sandbox
        config.code_sandbox_id = self.code_sandbox_id if self.code_sandbox_id else None
        config.document_provider = self.document_provider
        config.jupyterlab = self.jupyterlab
        config.open_notebook_in_ui = self.open_notebook_in_ui
        config.allowed_jupyter_mcp_tools = self.allowed_jupyter_mcp_tools

        # Store configuration in settings for handlers
        self.settings.update(
            {
                "mcp_document_url": self.document_url,
                "mcp_code_sandbox_url": self.code_sandbox_url,
                "mcp_document_id": self.document_id,
                "mcp_document_token": self.document_token,
                "mcp_code_sandbox_token": self.code_sandbox_token,
                "mcp_start_new_code_sandbox": self.start_new_code_sandbox,
                "mcp_code_sandbox_id": self.code_sandbox_id,
                "mcp_provider": self.document_provider,
                "mcp_jupyterlab": self.jupyterlab,
                "mcp_open_notebook_in_ui": self.open_notebook_in_ui,
                "mcp_allowed_jupyter_mcp_tools": self.allowed_jupyter_mcp_tools,
                "mcp_serverapp": self.serverapp,
            }
        )

        # Trigger auto-enrollment if document_id is configured
        # Note: Auto-enrollment supports 3 modes:
        # 1. With existing kernel (code_sandbox_id set)
        # 2. With new kernel (start_new_code_sandbox=True)
        # 3. Without kernel - notebook-only mode (both False/None)
        if self.document_id:
            from jupyter_mcp_server.server import notebook_manager

            if "default" not in notebook_manager:
                notebook_manager.add_notebook(
                    "default",
                    None,
                    server_url=self.document_url,
                    token=self.document_token,
                    path=self.document_id,
                )
                notebook_manager.set_current_notebook("default")
                logger.info(f"Auto-enrolled document '{self.document_id}' as 'default'")

        # Extensions register their tools here rather than at import, so
        # they see this server's configuration when they are asked what it
        # is pointed at. Idempotent, so it does not matter whether the CLI
        # already did it.
        from jupyter_mcp_server.server import register_extension_tools

        register_extension_tools()

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
            (url_path_join("mcp/?"), MCPSSEHandler),
            # Utility endpoints (optional, for debugging)
            (url_path_join("mcp/healthz"), MCPHealthHandler),
            (url_path_join("mcp/tools/list"), MCPToolsListHandler),
            (url_path_join("mcp/tools/call"), MCPToolsCallHandler),
        ]

        # Register handlers
        self.handlers.extend(handlers)

        # Log registered endpoints using url_path_join for consistent formatting
        logger.info(f"Registered MCP handlers at {url_path_join(base_url, 'mcp/')}")
        logger.info(f"  - MCP protocol: {url_path_join(base_url, 'mcp')} (SSE-based)")
        logger.info(f"  - Health check: {url_path_join(base_url, 'mcp/healthz')}")
        logger.info(f"  - List tools: {url_path_join(base_url, 'mcp/tools/list')}")
        logger.info(f"  - Call tool: {url_path_join(base_url, 'mcp/tools/call')}")

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
            "app": JupyterMCPServerExtensionApp,
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
