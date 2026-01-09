# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tornado request handlers for the Jupyter MCP Server extension.

This module provides handlers that bridge between Tornado (Jupyter Server) and
FastMCP, managing the MCP protocol lifecycle and request proxying.
"""

import json
import logging
from typing import Any
from tornado.web import RequestHandler
from jupyter_server.base.handlers import JupyterHandler

from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.jupyter_extension.backends.local_backend import LocalBackend
from jupyter_mcp_server.jupyter_extension.backends.remote_backend import RemoteBackend
from jupyter_mcp_server.utils import clean_mcp_response, clean_mcp_response_content


logger = logging.getLogger(__name__)


class MCPSSEHandler(RequestHandler):
    """
    Server-Sent Events (SSE) handler for MCP protocol.
    
    This handler implements the MCP SSE transport by directly calling
    the registered MCP tools instead of trying to wrap the Starlette app.
    
    The MCP protocol uses SSE for streaming responses from the server to the client.
    """
    
    # Cache of jupyter_mcp_tools tool names for routing decisions
    _jupyter_tool_names = set()
    
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
                            "tools": {},
                            "prompts": {},
                            "resources": {}
                        },
                        "serverInfo": {
                            "name": "Jupyter MCP Server",
                            "version": "0.20.0"
                        }
                    }
                }
                logger.info(f"Sending initialize response: {response}")
            elif method == "tools/list":
                # List available tools from FastMCP and jupyter_mcp_tools
                from jupyter_mcp_server.server import mcp
                
                logger.info("Listing tools from FastMCP and jupyter_mcp_tools...")
                
                try:
                    # Get FastMCP tools first
                    tools_list = await mcp.list_tools()
                    logger.info(f"Got {len(tools_list)} tools from FastMCP")
                    
                    # Track jupyter_mcp_tools tool names
                    jupyter_tool_names = set()
                    
                    # Get tools from jupyter_mcp_tools extension first to identify duplicates
                    jupyter_tools_data = []
                    try:
                        from jupyter_mcp_tools import get_tools
                        from jupyter_mcp_server.tool_cache import get_tool_cache
                        
                        # Get the server's base URL dynamically from ServerApp
                        context = get_server_context()
                        if context.serverapp is not None:
                            base_url = context.serverapp.connection_url
                            token = context.serverapp.token
                            logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                        else:
                            # Fallback to hardcoded localhost (should not happen in JUPYTER_SERVER mode)
                            port = self.settings.get('port', 8888)
                            base_url = f"http://localhost:{port}"
                            token = self.settings.get('token', None)
                            logger.warning(f"ServerApp not available, using fallback: {base_url}")
                        
                        logger.info(f"Querying jupyter_mcp_tools at {base_url}")
                        
                        # Check if JupyterLab mode is enabled before loading jupyter-mcp-tools
                        context = ServerContext.get_instance()
                        jupyterlab_enabled = context.is_jupyterlab_mode()
                        logger.info(f"JupyterLab mode check: enabled={jupyterlab_enabled}")
                        
                        if jupyterlab_enabled:
                            # Define specific tools we want to load from jupyter-mcp-tools
                            # (https://github.com/datalayer/jupyter-mcp-tools)
                            # jupyter-mcp-tools exposes JupyterLab commands as MCP tools.
                            # Only tools listed here will be available to MCP clients.
                            # To add new tools, also update the list in server.py and
                            # see docs/docs/reference/tools-additional/index.mdx for documentation.
                            from jupyter_mcp_server.config import get_config
                            config = get_config()
                            allowed_jupyter_mcp_tools = config.get_allowed_jupyter_mcp_tools()
                            
                            logger.info(f"Looking for specific jupyter-mcp-tools: {allowed_jupyter_mcp_tools}")
                            
                            # Try querying with caching to avoid expensive repeated calls
                            try:
                                search_query = ",".join(allowed_jupyter_mcp_tools)
                                logger.info(f"Searching jupyter-mcp-tools with query: '{search_query}' (allowed_tools: {allowed_jupyter_mcp_tools})")
                                
                                # Use cached get_tools to avoid expensive repeated calls
                                tool_cache = get_tool_cache()
                                
                                # Create wrapper function that matches the expected signature
                                async def get_tools_wrapper(**kwargs):
                                    # Add wait_timeout for handlers.py compatibility
                                    return await get_tools(
                                        wait_timeout=5,  # Shorter timeout - if frontend isn't loaded, don't wait long
                                        **kwargs
                                    )
                                
                                jupyter_tools_data = await tool_cache.get_tools(
                                    base_url=base_url,
                                    token=token,
                                    query=search_query,
                                    enabled_only=False,
                                    ttl_seconds=180,  # 3 minutes for handlers (shorter than server.py)
                                    fetch_func=get_tools_wrapper  # Use wrapper that includes wait_timeout
                                )
                                logger.info(f"Query returned {len(jupyter_tools_data)} tools (from cache or fresh)")
                                
                                # Use the tools directly since query should return only what we want
                                for tool in jupyter_tools_data:
                                    logger.info(f"Found tool: {tool.get('id', '')}")
                            except Exception as e:
                                logger.warning(f"Failed to load jupyter-mcp-tools (this is normal if JupyterLab frontend is not loaded): {e}")
                                jupyter_tools_data = []
                            
                            logger.info(f"Successfully loaded {len(jupyter_tools_data)} specific jupyter-mcp-tools (requires JupyterLab frontend)")
                        else:
                            # JupyterLab mode disabled, don't load any jupyter-mcp-tools
                            jupyter_tools_data = []
                            logger.info("JupyterLab mode disabled, skipping jupyter-mcp-tools")
                        
                        # Build set of jupyter tool names and cache it for routing decisions
                        jupyter_tool_names = {tool_data.get('id', '') for tool_data in jupyter_tools_data}
                        MCPSSEHandler._jupyter_tool_names = jupyter_tool_names
                        logger.info(f"Cached {len(jupyter_tool_names)} jupyter_mcp_tools names for routing: {jupyter_tool_names}")
                    
                    except Exception as jupyter_error:
                        # Log but don't fail - just return FastMCP tools
                        logger.warning(f"Could not fetch tools from jupyter_mcp_tools: {jupyter_error}")
                    
                    # Convert FastMCP tools to MCP protocol format
                    tools = []
                    for tool in tools_list:
                        tools.append({
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema
                        })
                    
                    # Now add jupyter_mcp_tools
                    for tool_data in jupyter_tools_data:
                        # Only include MCP protocol fields (exclude internal fields like commandId)
                        tool_dict = {
                            "name": tool_data.get('id', ''),
                            "description": tool_data.get('caption', tool_data.get('label', '')),
                        }
                        
                        # Convert parameters to inputSchema
                        # The parameters field contains the JSON Schema for the tool's arguments
                        params = tool_data.get('parameters', {})
                        if params and isinstance(params, dict) and params.get('properties'):
                            # Tool has parameters - use them as inputSchema
                            tool_dict["inputSchema"] = params
                            logger.debug(f"Tool {tool_dict['name']} has parameters: {list(params.get('properties', {}).keys())}")
                        else:
                            # Tool has no parameters - use empty schema
                            tool_dict["inputSchema"] = {
                                "type": "object",
                                "properties": {},
                                "description": tool_data.get('usage', '')
                            }
                        
                        tools.append(tool_dict)
                    
                    logger.info(f"Added {len(jupyter_tools_data)} tool(s) from jupyter_mcp_tools")

                    
                    logger.info(f"Returning total of {len(tools)} tools")
                    
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
                
                logger.info(f"Calling tool: {tool_name}")
                
                try:
                    # Check if this is a jupyter_mcp_tools tool
                    # Use the cached set of jupyter tool names from tools/list
                    if tool_name in MCPSSEHandler._jupyter_tool_names:
                        # Route to jupyter_mcp_tools extension via HTTP execute endpoint
                        logger.info(f"Routing {tool_name} to jupyter_mcp_tools extension (recognized from cache)")
                        
                        # Get server configuration from ServerApp
                        context = get_server_context()
                        if context.serverapp is not None:
                            base_url = context.serverapp.connection_url
                            token = context.serverapp.token
                            logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                        else:
                            # Fallback to hardcoded localhost (should not happen in JUPYTER_SERVER mode)
                            port = self.settings.get('port', 8888)
                            base_url = f"http://localhost:{port}"
                            token = self.settings.get('token', None)
                            logger.warning(f"ServerApp not available, using fallback: {base_url}")
                        
                        # Use the MCPToolsClient to execute the tool
                        from jupyter_mcp_tools.client import MCPToolsClient
                        
                        try:
                            async with MCPToolsClient(base_url=base_url, token=token) as client:
                                execution_result = await client.execute_tool(
                                    tool_id=tool_name,
                                    parameters=tool_arguments
                                )
                                
                                if execution_result.get('success'):
                                    result_data = execution_result.get('result', {})
                                    result_text = str(result_data) if result_data else "Tool executed successfully"
                                    result_dict = {
                                        "content": [{
                                            "type": "text",
                                            "text": result_text
                                        }]
                                    }
                                else:
                                    error_msg = execution_result.get('error', 'Unknown error')
                                    result_dict = {
                                        "content": [{
                                            "type": "text",
                                            "text": f"Error executing tool: {error_msg}"
                                        }],
                                        "isError": True
                                    }
                        except Exception as exec_error:
                            logger.error(f"Error executing {tool_name}: {exec_error}")
                            result_dict = {
                                "content": [{
                                    "type": "text",
                                    "text": f"Failed to execute tool: {str(exec_error)}"
                                }],
                                "isError": True
                            }
                    else:
                        # Use FastMCP's call_tool method for regular tools
                        logger.info(f"Routing {tool_name} to FastMCP (not in jupyter_mcp_tools cache)")
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
                                        serialized_item = clean_mcp_response_content(item.model_dump())
                                        serialized_content.append(serialized_item)
                                    elif hasattr(item, 'dict'):
                                        serialized_item = clean_mcp_response_content(item.dict())
                                        serialized_content.append(serialized_item)
                                    elif isinstance(item, dict):
                                        serialized_item = clean_mcp_response_content(item)
                                        serialized_content.append(serialized_item)
                                    else:
                                        serialized_content.append({"type": "text", "text": str(item)})
                                result_dict = {"content": serialized_content}
                            else:
                                result_dict = {"content": [{"type": "text", "text": str(result)}]}
                        # Convert result to dict - it's a CallToolResult with content list
                        elif hasattr(result, 'model_dump'):
                            result_dict = clean_mcp_response(result.model_dump())
                        elif hasattr(result, 'dict'):
                            result_dict = clean_mcp_response(result.dict())
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
            elif method == "prompts/list":
                # List available prompts - return empty list if no prompts defined
                logger.info("Listing prompts...")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "prompts": []
                    }
                }
            elif method == "resources/list":
                # List available resources - return empty list if no resources defined  
                logger.info("Listing resources...")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "resources": []
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


class MCPHandler(JupyterHandler):
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
    
    def get(self):
        """Handle health check request."""
        context = get_server_context()
        
        health_info = {
            "status": "healthy",
            "context_type": context.context_type,
            "document_url": context.document_url or self.settings.get("mcp_document_url"),
            "runtime_url": context.runtime_url or self.settings.get("mcp_runtime_url"),
            "extension": "jupyter_mcp_server",
            "version": "0.20.0"
        }
        
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(health_info))
        self.finish()


class MCPToolsListHandler(MCPHandler):
    """
    List available MCP tools.
    
    GET /mcp/tools/list
    """
    
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
