# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tornado Handlers for MCP Protocol

These handlers expose MCP protocol endpoints via Jupyter Server's Tornado web application.
"""

import json
import logging
from typing import Any
import asyncio
import tornado.web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.extension.handler import ExtensionHandlerMixin

from jupyter_mcp_server.jupyter_to_mcp.context import get_server_context
from jupyter_mcp_server.jupyter_to_mcp.backends.local_backend import LocalBackend
from jupyter_mcp_server.jupyter_to_mcp.backends.remote_backend import RemoteBackend


logger = logging.getLogger(__name__)


class MCPASGIHandler(tornado.web.RequestHandler):
    """
    Handler that wraps a Starlette ASGI application.
    
    This handler allows mounting the FastMCP Starlette app within Tornado.
    """
    
    def initialize(self, asgi_app):
        """Initialize with the ASGI application."""
        self.asgi_app = asgi_app
    
    async def _execute_asgi(self):
        """Execute the ASGI application."""
        # Build ASGI scope
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": self.request.version,
            "method": self.request.method,
            "scheme": "https" if self.request.protocol == "https" else "http",
            "path": self.request.path,
            "query_string": self.request.query.encode("latin1") if self.request.query else b"",
            "root_path": "",
            "headers": [
                (name.lower().encode("latin1"), value.encode("latin1"))
                for name, value in self.request.headers.get_all()
            ],
            "server": (self.request.host.split(":")[0], 
                      int(self.request.host.split(":")[1]) if ":" in self.request.host else 80),
        }
        
        # Create receive/send callables
        request_complete = False
        
        async def receive():
            nonlocal request_complete
            if not request_complete:
                request_complete = True
                return {
                    "type": "http.request",
                    "body": self.request.body,
                    "more_body": False,
                }
            # Should not be called again
            await asyncio.sleep(0.1)
            return {"type": "http.disconnect"}
        
        response_started = False
        
        async def send(message):
            nonlocal response_started
            
            if message["type"] == "http.response.start":
                response_started = True
                self.set_status(message["status"])
                for header_name, header_value in message.get("headers", []):
                    self.set_header(
                        header_name.decode("latin1"),
                        header_value.decode("latin1")
                    )
            
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    self.write(body)
                
                # If this is the final chunk, finish the response
                if not message.get("more_body", False):
                    self.finish()
        
        # Execute the ASGI app
        try:
            await self.asgi_app(scope, receive, send)
        except Exception as e:
            logger.error(f"ASGI app error: {e}", exc_info=True)
            if not response_started:
                self.set_status(500)
                self.write(json.dumps({"error": str(e)}))
                self.finish()
    
    async def get(self):
        """Handle GET requests."""
        await self._execute_asgi()
    
    async def post(self):
        """Handle POST requests."""
        await self._execute_asgi()
    
    async def put(self):
        """Handle PUT requests."""
        await self._execute_asgi()
    
    async def delete(self):
        """Handle DELETE requests."""
        await self._execute_asgi()
    
    async def patch(self):
        """Handle PATCH requests."""
        await self._execute_asgi()
    
    async def options(self):
        """Handle OPTIONS requests."""
        await self._execute_asgi()


class MCPHandler(ExtensionHandlerMixin, JupyterHandler):
    """Base handler for MCP endpoints with common functionality."""
    
    def get_backend(self):
        """
        Get the appropriate backend based on configuration.
        
        Returns:
            Backend instance (LocalBackend or RemoteBackend)
        """
        context = get_server_context()
        
        # Check if we should use local backend
        if context.is_local_document() or context.is_local_runtime():
            return LocalBackend(context.serverapp)
        else:
            # Use remote backend
            document_url = self.settings.get("mcp_document_url")
            document_token = self.settings.get("mcp_document_token", "")
            runtime_url = self.settings.get("mcp_runtime_url")
            runtime_token = self.settings.get("mcp_runtime_token", "")
            
            return RemoteBackend(
                document_url=document_url,
                document_token=document_token,
                runtime_url=runtime_url,
                runtime_token=runtime_token
            )
    
    def set_default_headers(self):
        """Set CORS headers for MCP clients."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    
    def options(self, *args, **kwargs):
        """Handle OPTIONS requests for CORS preflight."""
        self.set_status(204)
        self.finish()


class MCPHealthHandler(MCPHandler):
    """
    Health check endpoint.
    
    GET /mcp/healthz
    """
    
    @tornado.web.authenticated
    def get(self):
        """Handle health check request."""
        context = get_server_context()
        
        health_info = {
            "status": "healthy",
            "context_type": context.context_type,
            "document_url": context.document_url or self.settings.get("mcp_document_url"),
            "runtime_url": context.runtime_url or self.settings.get("mcp_runtime_url"),
            "extension": "jupyter_mcp_server",
            "version": "0.14.0"
        }
        
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(health_info))
        self.finish()


class MCPToolsListHandler(MCPHandler):
    """
    List available MCP tools.
    
    GET /mcp/tools/list
    """
    
    @tornado.web.authenticated
    def get(self):
        """Return list of available tools."""
        tools = [
            {
                "name": "connect_notebook",
                "description": "Connect to a notebook file or create a new one",
                "parameters": ["notebook_name", "notebook_path", "mode", "kernel_id"]
            },
            {
                "name": "list_notebook",
                "description": "List all notebooks in the Jupyter server",
                "parameters": []
            },
            {
                "name": "disconnect_notebook",
                "description": "Disconnect from a notebook",
                "parameters": ["notebook_name"]
            },
            {
                "name": "restart_notebook",
                "description": "Restart the kernel for a specific notebook",
                "parameters": ["notebook_name"]
            },
            {
                "name": "switch_notebook",
                "description": "Switch the currently active notebook",
                "parameters": ["notebook_name"]
            },
            {
                "name": "read_cells",
                "description": "Read cells from the current notebook",
                "parameters": ["start_index", "end_index"]
            },
            {
                "name": "insert_cell",
                "description": "Insert a cell at specified position",
                "parameters": ["cell_index", "cell_type", "cell_source"]
            },
            {
                "name": "delete_cell",
                "description": "Delete a cell from the notebook",
                "parameters": ["cell_index"]
            },
            {
                "name": "overwrite_cell",
                "description": "Overwrite cell content",
                "parameters": ["cell_index", "new_source"]
            },
            {
                "name": "execute_cell_simple_timeout",
                "description": "Execute a cell with simple timeout",
                "parameters": ["cell_index", "timeout_seconds"]
            },
            {
                "name": "execute_cell_with_progress",
                "description": "Execute a cell with progress monitoring",
                "parameters": ["cell_index", "timeout_seconds"]
            },
        ]
        
        response = {
            "tools": tools,
            "count": len(tools)
        }
        
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(response))
        self.finish()


class MCPToolsCallHandler(MCPHandler):
    """
    Execute an MCP tool.
    
    POST /mcp/tools/call
    Body: {"tool_name": "...", "arguments": {...}}
    """
    
    @tornado.web.authenticated
    async def post(self):
        """Handle tool execution request."""
        try:
            # Parse request body
            body = json.loads(self.request.body.decode('utf-8'))
            tool_name = body.get("tool_name")
            arguments = body.get("arguments", {})
            
            if not tool_name:
                self.set_status(400)
                self.write(json.dumps({"error": "tool_name is required"}))
                self.finish()
                return
            
            logger.info(f"Executing tool: {tool_name} with args: {arguments}")
            
            # Get backend
            backend = self.get_backend()
            
            # Execute tool based on name
            # For now, return a placeholder response
            # TODO: Implement actual tool routing
            result = await self._execute_tool(tool_name, arguments, backend)
            
            response = {
                "success": True,
                "result": result
            }
            
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(response))
            self.finish()
            
        except Exception as e:
            logger.error(f"Error executing tool: {e}", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({
                "success": False,
                "error": str(e)
            }))
            self.finish()
    
    async def _execute_tool(self, tool_name: str, arguments: dict[str, Any], backend):
        """
        Route tool execution to appropriate implementation.
        
        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            backend: Backend instance
            
        Returns:
            Tool execution result
        """
        # TODO: Implement actual tool routing
        # For now, return a simple response
        
        if tool_name == "list_notebook":
            notebooks = await backend.list_notebooks()
            return {"notebooks": notebooks}
        
        # Placeholder for other tools
        return f"Tool {tool_name} executed with backend {type(backend).__name__}"
