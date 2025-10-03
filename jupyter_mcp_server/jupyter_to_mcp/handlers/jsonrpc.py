# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""JSON-RPC handler for direct MCP client connections."""

import json
import logging
from typing import Any, Dict

from tornado.web import RequestHandler

from .base import MCPBaseHandler

logger = logging.getLogger(__name__)


class JSONRPCHandler(MCPBaseHandler):
    """Handler for JSON-RPC requests from MCP clients."""
    
    def check_xsrf_cookie(self):
        """Override XSRF check for MCP client compatibility."""
        pass
    
    async def post(self):
        """Handle JSON-RPC POST requests."""
        try:
            # Parse JSON-RPC request
            body = self.request.body.decode('utf-8')
            logger.info("Received JSON-RPC request: %s", body)
            
            request_data = json.loads(body)
            
            # Validate JSON-RPC structure
            if not isinstance(request_data, dict):
                return self._send_jsonrpc_error(-32600, "Invalid Request", None)
            
            jsonrpc = request_data.get("jsonrpc")
            method = request_data.get("method")
            params = request_data.get("params", {})
            request_id = request_data.get("id")
            
            if jsonrpc != "2.0":
                return self._send_jsonrpc_error(-32600, "Invalid Request - jsonrpc must be 2.0", request_id)
            
            if not method:
                return self._send_jsonrpc_error(-32600, "Invalid Request - method required", request_id)
            
            # Route to appropriate method
            if method == "initialize":
                result = await self._handle_initialize(params)
            elif method == "tools/list":
                result = await self._handle_tools_list(params)
            elif method == "tools/call":
                result = await self._handle_tools_call(params)
            elif method == "capabilities":
                result = await self._handle_capabilities(params)
            else:
                return self._send_jsonrpc_error(-32601, f"Method not found: {method}", request_id)
            
            # Send successful response
            response = {
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id
            }
            
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(response))
            
        except json.JSONDecodeError as e:
            logger.error("JSON decode error: %s", e)
            return self._send_jsonrpc_error(-32700, "Parse error", None)
        except Exception as e:
            logger.error("Error handling JSON-RPC request: %s", e)
            return self._send_jsonrpc_error(-32603, f"Internal error: {str(e)}", request_data.get("id") if 'request_data' in locals() else None)
    
    def _send_jsonrpc_error(self, code: int, message: str, request_id: Any):
        """Send JSON-RPC error response."""
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message
            },
            "id": request_id
        }
        
        self.set_header("Content-Type", "application/json")
        self.set_status(200)  # JSON-RPC errors use HTTP 200
        self.write(json.dumps(error_response))
    
    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize method."""
        logger.info("Handling initialize with params: %s", params)
        
        # Initialize MCP session if needed
        session_id = await self.adapter.initialize_session()
        
        # Get server info and capabilities
        server_info = await self.adapter.get_server_info(session_id)
        
        # Return initialization response
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": server_info.get("capabilities", {}),
            "serverInfo": {
                "name": "jupyter-mcp-server",
                "version": "0.14.0"
            }
        }
    
    async def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list method."""
        logger.info("Handling tools/list with params: %s", params)
        
        session_id = await self.adapter.get_or_create_session()
        tools, cursor = await self.adapter.list_tools(session_id)
        
        # Convert Tool objects to dicts for JSON serialization
        tools_list = []
        for tool in tools:
            tool_dict = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema
            }
            if tool.annotations:
                tool_dict["annotations"] = tool.annotations
            tools_list.append(tool_dict)
        
        result = {"tools": tools_list}
        if cursor:
            result["nextCursor"] = cursor
            
        return result
    
    async def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call method."""
        logger.info("Handling tools/call with params: %s", params)
        
        # Extract tool call parameters
        name = params.get("name")
        arguments = params.get("arguments", {})
        
        if not name:
            raise ValueError("Tool name is required")
        
        session_id = await self.adapter.get_or_create_session()
        result = await self.adapter.call_tool(session_id, name, arguments)
        
        # Convert ToolCallResponse to JSON-serializable format
        if hasattr(result, 'content'):
            # Convert to MCP-style response
            content_list = []
            for item in result.content:
                if hasattr(item, 'type') and hasattr(item, 'text'):
                    content_list.append({
                        "type": item.type,
                        "text": item.text
                    })
                elif hasattr(item, 'type') and hasattr(item, 'data'):
                    content_list.append({
                        "type": item.type,
                        "data": item.data,
                        "mimeType": getattr(item, 'mimeType', None)
                    })
            return {
                "content": content_list,
                "isError": getattr(result, 'isError', False)
            }
        else:
            return result
    
    async def _handle_capabilities(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle capabilities method."""
        logger.info("Handling capabilities with params: %s", params)
        
        session_id = await self.adapter.get_or_create_session()
        capabilities = await self.adapter.get_capabilities(session_id)
        
        return capabilities
