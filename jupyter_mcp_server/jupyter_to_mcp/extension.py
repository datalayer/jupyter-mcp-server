# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Main extension class for the Jupyter-to-MCP adapter."""

import logging
import asyncio
import subprocess
import time
import os
from pathlib import Path

from jupyter_server.extension.application import ExtensionApp
from traitlets import Unicode, Bool, Integer

from .adapter import MCPAdapter, EmbeddedMCPAdapter
from .handlers import (
    ToolsHandler,
    ToolCallHandler,
    InitializeHandler,
    CapabilitiesHandler,
    HealthHandler,
    JSONRPCHandler
)

logger = logging.getLogger(__name__)

# Add this to see if the module is being imported
print("=== JUPYTER_TO_MCP EXTENSION MODULE LOADED ===")
logger.info("=== JUPYTER_TO_MCP EXTENSION MODULE LOADED ===")


class JupyterToMCPExtension(ExtensionApp):
    """Jupyter server extension that provides HTTP REST API for MCP tools."""
    
    # Extension metadata
    name = "jupyter_to_mcp"
    app_name = "Jupyter to MCP Adapter"
    description = "HTTP REST API adapter for Jupyter MCP Server tools"
    extension_url = "/mcp"
    
    # Configuration traits
    mcp_server_url = Unicode(
        help="URL of the MCP server to connect to (auto-generated from mcp_server_port if not set)"
    ).tag(config=True)
    
    @property
    def _mcp_server_url(self):
        """Get the effective MCP server URL."""
        if self.mcp_server_url:
            return self.mcp_server_url
        return f"http://localhost:{self.mcp_server_port}"
    
    base_path = Unicode(
        "/mcp",
        help="Base URL path for MCP endpoints"
    ).tag(config=True)
    
    enabled = Bool(
        True,
        help="Enable/disable the MCP adapter extension"
    ).tag(config=True)
    
    session_timeout = Integer(
        3600,
        help="Session timeout in seconds"
    ).tag(config=True)
    
    auto_start_mcp_server = Bool(
        False,  # Changed to False since we'll embed MCP directly
        help="Automatically start the MCP server when extension loads"
    ).tag(config=True)
    
    mcp_server_port = Integer(
        4040,
        help="Port for the MCP server to run on (not used when embedded)"
    ).tag(config=True)
    
    def __init__(self, **kwargs):
        """Initialize the extension app."""
        super().__init__(**kwargs)
        self.adapter = None
        self.mcp_server_process = None
    
    def start_mcp_server(self):
        """Start the MCP server process."""
        if not self.auto_start_mcp_server:
            logger.info("Auto-start MCP server is disabled")
            return
        
        logger.info("Attempting to start MCP server on port %d", self.mcp_server_port)
        
        try:
            # Check if MCP server is already running
            import requests
            response = requests.get(f"http://localhost:{self.mcp_server_port}/api/healthz", timeout=2)
            if response.status_code == 200:
                logger.info("MCP server already running on port %d", self.mcp_server_port)
                return
        except requests.RequestException as e:
            # Server not running, we'll start it
            logger.info("MCP server not running (expected), will start it: %s", e)
        
        # Get the current Jupyter server info
        server_url = getattr(self.serverapp, 'base_url', 'http://localhost:8888')
        if hasattr(self.serverapp, 'port'):
            server_url = f"http://localhost:{self.serverapp.port}"
        elif hasattr(self.serverapp, 'ip') and hasattr(self.serverapp, 'port'):
            server_url = f"http://{self.serverapp.ip}:{self.serverapp.port}"
        else:
            # Fallback - try to get from config
            server_url = "http://localhost:8888"
        
        # Get token from server app
        token = getattr(self.serverapp, 'token', 'MY_TOKEN')
        
        # Start MCP server
        logger.info("Starting MCP server on port %d", self.mcp_server_port)
        
        # Use the same command structure as the Makefile
        cmd = [
            "jupyter-mcp-server", "start",
            "--transport", "streamable-http",
            "--document-url", server_url,
            "--document-id", "notebook.ipynb",
            "--document-token", token,
            "--runtime-url", server_url,
            "--start-new-runtime", "true",
            "--runtime-token", token,
            "--port", str(self.mcp_server_port)
        ]
        
        logger.info("Starting MCP server with command: %s", ' '.join(cmd))
        
        try:
            self.mcp_server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy()
            )
            
            # Wait a moment for server to start
            time.sleep(2)
            
            # Check if it's running
            if self.mcp_server_process.poll() is None:
                logger.info("MCP server started successfully (PID: %d)", self.mcp_server_process.pid)
            else:
                stdout, stderr = self.mcp_server_process.communicate()
                logger.error("MCP server failed to start. stdout: %s, stderr: %s", 
                           stdout.decode(), stderr.decode())
                self.mcp_server_process = None
                
        except Exception as e:
            logger.error("Failed to start MCP server: %s", e)
            self.mcp_server_process = None

    def initialize_settings(self):
        """Initialize extension settings."""
        logger.info("=== INITIALIZE_SETTINGS CALLED ===")
        super().initialize_settings()
        
    def initialize_handlers(self):
        """Initialize HTTP request handlers."""
        logger.info("=== INITIALIZE_HANDLERS CALLED ===")
        
        if not self.enabled:
            logger.info("Extension disabled, not initializing handlers")
            return
        
        # Don't start external MCP server - we're using embedded version
        # self.start_mcp_server()  # Commented out
        
        # Initialize MCP adapter - use embedded version instead of external
        logger.info("Creating embedded MCP adapter (no external server needed)")
        self.adapter = EmbeddedMCPAdapter(jupyter_server_app=self.serverapp)
        
        # Define handler routes
        handlers = [
            # JSON-RPC endpoint for MCP clients (must be first to match /mcp exactly)
            (rf"{self.base_path}$", JSONRPCHandler, {"adapter": self.adapter}),
            
            # REST API endpoints
            (rf"{self.base_path}/initialize", InitializeHandler, {"adapter": self.adapter}),
            (rf"{self.base_path}/capabilities", CapabilitiesHandler, {"adapter": self.adapter}),
            (rf"{self.base_path}/tools", ToolsHandler, {"adapter": self.adapter}),
            (rf"{self.base_path}/tools/call", ToolCallHandler, {"adapter": self.adapter}),
            (rf"{self.base_path}/health", HealthHandler, {"adapter": self.adapter}),
        ]
        
        # Add handlers to the extension
        self.handlers.extend(handlers)
        
        logger.info("Registered %d MCP HTTP endpoints under %s", len(handlers), self.base_path)
        
    def initialize(self):
        """Initialize the extension."""
        logger.info("=== JUPYTER-TO-MCP EXTENSION INITIALIZE CALLED ===")
        
        if not self.enabled:
            logger.info("Jupyter-to-MCP extension is disabled")
            return
        
        logger.info("Initializing Jupyter-to-MCP extension")
        
        # Call parent initialize
        super().initialize()
        
        logger.info("Jupyter-to-MCP extension initialization complete")
    

    
    async def stop_extension(self):
        """Clean up when extension stops."""
        if hasattr(self, 'adapter') and self.adapter:
            logger.info("Cleaning up MCP adapter sessions")
            # Clean up any active sessions
            # This would require implementing a cleanup method in MCPAdapter
        
        # Stop MCP server if we started it
        if self.mcp_server_process:
            logger.info("Stopping MCP server (PID: %d)", self.mcp_server_process.pid)
            try:
                self.mcp_server_process.terminate()
                # Give it a few seconds to shutdown gracefully
                try:
                    self.mcp_server_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't stop
                    self.mcp_server_process.kill()
                    self.mcp_server_process.wait()
                logger.info("MCP server stopped")
            except Exception as e:
                logger.error("Error stopping MCP server: %s", e)


# For backward compatibility with older extension loading
def load_jupyter_server_extension(serverapp):
    """Load the extension (backward compatibility)."""
    logger.info("=== LOAD_JUPYTER_SERVER_EXTENSION CALLED ===")
    
    extension = JupyterToMCPExtension()
    extension.serverapp = serverapp
    
    # Initialize the extension 
    extension.initialize()
    extension.initialize_settings()
    extension.initialize_handlers()
    
    logger.info("Extension handlers: %s", extension.handlers)
    
    # Add handlers to the web application
    web_app = serverapp.web_app
    host_pattern = ".*$"
    web_app.add_handlers(host_pattern, extension.handlers)
    
    logger.info("=== EXTENSION LOADING COMPLETE ===")
    logger.info("Registered %d MCP endpoints", len(extension.handlers))


# Reference for Jupyter Server compatibility
_load_jupyter_server_extension = load_jupyter_server_extension
