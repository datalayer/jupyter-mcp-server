# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tornado request handlers for the Jupyter MCP Server extension.

This module provides handlers that bridge between Tornado (Jupyter Server) and
FastMCP, managing the MCP protocol lifecycle and request proxying.
"""

import json
import logging
import tornado.web
from typing import Any
from tornado.web import RequestHandler
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.extension.handler import ExtensionHandlerMixin

from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.jupyter_extension.backends.local_backend import LocalBackend
from jupyter_mcp_server.jupyter_extension.backends.remote_backend import RemoteBackend

logger = logging.getLogger(__name__)


class MCPSSEHandler(RequestHandler):
    """
    Server-Sent Events (SSE) handler for MCP protocol.
    
    This handler implements the MCP SSE transport by directly calling
    the registered MCP tools instead of trying to wrap the Starlette app.
    
    The MCP protocol uses SSE for streaming responses from the server to the client.
    """
    
    def check_xsrf_cookie(self):
        """Disable XSRF checking for MCP protocol requests."""
        pass
    
    def set_default_headers(self):
        """Set headers for SSE and CORS."""
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    
    async def options(self, *args, **kwargs):
        """Handle CORS preflight requests."""
        self.set_status(204)
        self.finish()
    
    async def get(self):
        """Handle SSE connection establishment."""
        # Import here to avoid circular dependency
        from jupyter_mcp_server.server import mcp
        
        # For now, just acknowledge the connection
        # The actual MCP protocol would be handled via POST
        self.write("event: connected\ndata: {}\n\n")
        await self.flush()
    
    async def post(self):
        """Handle MCP protocol messages."""
        # Import here to avoid circular dependency
        from jupyter_mcp_server.server import mcp
        
        try:
            # Parse the JSON-RPC request
            body = json.loads(self.request.body.decode('utf-8'))
            method = body.get("method")
            params = body.get("params", {})
            request_id = body.get("id")
            
            logger.info(f"MCP request: method={method}, id={request_id}")
            
            # Handle notifications (id is None) - these don't require a response per JSON-RPC 2.0
            # But in HTTP transport, we need to acknowledge the request
            if request_id is None:
                logger.info(f"Received notification: {method} - acknowledging without result")
                # Return empty response - the client should handle notifications without expecting a result
                # Some clients may send this as POST and expect HTTP 200 with no JSON-RPC response
                self.set_status(200)
                self.finish()
                return
            
            # Handle different MCP methods
            if method == "initialize":
                # Return server capabilities
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "Jupyter MCP Server",
                            "version": "0.14.0"
                        }
                    }
                }
                logger.info(f"Sending initialize response: {response}")
            elif method == "tools/list":
                # List available tools from FastMCP
                from jupyter_mcp_server.server import mcp
                
                logger.info("Calling mcp.list_tools()...")
                
                try:
                    # Use FastMCP's list_tools method - returns list of Tool objects
                    tools_list = await mcp.list_tools()
                    logger.info(f"Got {len(tools_list)} tools from FastMCP")
                    
                    # Convert to MCP protocol format
                    tools = []
                    for tool in tools_list:
                        tools.append({
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema
                        })
                    
                    logger.info(f"Converted {len(tools)} tools to MCP format")
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "tools": tools
                        }
                    }
                except Exception as e:
                    logger.error(f"Error listing tools: {e}", exc_info=True)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error listing tools: {str(e)}"
                        }
                    }
            elif method == "tools/call":
                # Execute a tool
                from jupyter_mcp_server.server import mcp
                
                tool_name = params.get("name")
                tool_arguments = params.get("arguments", {})
                
                logger.info(f"Calling tool: {tool_name} with args: {tool_arguments}")
                
                try:
                    # Use FastMCP's call_tool method
                    result = await mcp.call_tool(tool_name, tool_arguments)
                    
                    # Handle tuple results from FastMCP
                    if isinstance(result, tuple) and len(result) >= 1:
                        # FastMCP returns (content_list, metadata_dict)
                        content_list = result[0]
                        if isinstance(content_list, list):
                            # Serialize TextContent objects to dicts
                            serialized_content = []
                            for item in content_list:
                                if hasattr(item, 'model_dump'):
                                    serialized_content.append(item.model_dump())
                                elif hasattr(item, 'dict'):
                                    serialized_content.append(item.dict())
                                elif isinstance(item, dict):
                                    serialized_content.append(item)
                                else:
                                    serialized_content.append({"type": "text", "text": str(item)})
                            result_dict = {"content": serialized_content}
                        else:
                            result_dict = {"content": [{"type": "text", "text": str(result)}]}
                    # Convert result to dict - it's a CallToolResult with content list
                    elif hasattr(result, 'model_dump'):
                        result_dict = result.model_dump()
                    elif hasattr(result, 'dict'):
                        result_dict = result.dict()
                    elif hasattr(result, 'content'):
                        # Extract content directly if it has a content attribute
                        result_dict = {"content": result.content}
                    else:
                        # Last resort: check if it's already a string
                        if isinstance(result, str):
                            result_dict = {"content": [{"type": "text", "text": result}]}
                        else:
                            # If it's some other type, try to serialize it
                            result_dict = {"content": [{"type": "text", "text": str(result)}]}
                            logger.warning(f"Used fallback str() conversion for type {type(result)}")
                    
                    logger.info(f"Converted result to dict")

                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result_dict
                    }
                except Exception as e:
                    logger.error(f"Error calling tool: {e}", exc_info=True)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error calling tool: {str(e)}"
                        }
                    }
            else:
                # Method not supported
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
            
            # Send response
            self.set_header("Content-Type", "application/json")
            logger.info(f"Sending response: {json.dumps(response)[:200]}...")
            self.write(json.dumps(response))
            self.finish()
            
        except Exception as e:
            logger.error(f"Error handling MCP request: {e}", exc_info=True)
            self.set_status(500)
            self.write(json.dumps({
                "jsonrpc": "2.0",
                "id": body.get("id") if 'body' in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }))
            self.finish()


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
    async def get(self):
        """Return list of available tools dynamically from the tool registry."""
        # Import here to avoid circular dependency
        from jupyter_mcp_server.server import get_registered_tools
        
        # Get tools dynamically from the MCP server registry
        tools = await get_registered_tools()
        
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
        
        if tool_name == "list_notebooks":
            notebooks = await backend.list_notebooks()
            return {"notebooks": notebooks}
        
        # Placeholder for other tools
        return f"Tool {tool_name} executed with backend {type(backend).__name__}"
