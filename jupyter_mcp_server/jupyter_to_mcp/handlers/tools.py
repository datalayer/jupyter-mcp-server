# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Tools endpoint handlers for the Jupyter-to-MCP adapter."""

import json
import logging

import tornado

from .base import MCPBaseHandler
from jupyter_mcp_server.jupyter_to_mcp.utils import clean_tool_name, validate_tool_arguments

logger = logging.getLogger(__name__)


class ToolsHandler(MCPBaseHandler):
    """Handler for listing available MCP tools."""
    
    @tornado.web.authenticated
    async def get(self):
        """List available MCP tools.
        
        Query parameters:
        - cursor: Optional cursor for pagination
        """
        try:
            session_id = self.get_session_id()
            cursor = self.get_query_argument_safe("cursor")
            
            tools, next_cursor = await self.adapter.list_tools(session_id, cursor)
            
            response = {
                "tools": [tool.model_dump() for tool in tools],
                "nextCursor": next_cursor
            }
            
            self.write(json.dumps(response))
            
        except Exception as e:
            logger.error("Error listing tools: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(error_response["status_code"])
            self.write(json.dumps(error_response))


class ToolCallHandler(MCPBaseHandler):
    """Handler for calling MCP tools."""
    
    @tornado.web.authenticated
    async def post(self):
        """Call an MCP tool.
        
        Request body:
        {
            "name": "tool_name",
            "arguments": {
                "param1": "value1",
                ...
            }
        }
        """
        try:
            session_id = self.get_session_id()
            request_data = self.get_json_body()
            
            # Validate request
            tool_name = request_data.get("name")
            if not tool_name:
                raise ValueError("Tool name is required")
            
            # Clean and validate tool name
            tool_name = clean_tool_name(tool_name)
            
            # Get arguments
            arguments = request_data.get("arguments", {})
            if not validate_tool_arguments(arguments):
                raise ValueError("Invalid tool arguments format")
            
            # Call the tool
            result = await self.adapter.call_tool(session_id, tool_name, arguments)
            
            response = {
                "content": [item.model_dump() for item in result.content],
                "isError": result.isError
            }
            
            if result.isError:
                self.set_status(409)  # Conflict - tool execution error
            
            self.write(json.dumps(response))
            
        except ValueError as e:
            logger.warning("Invalid tool call request: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(400)
            self.write(json.dumps(error_response))
            
        except Exception as e:
            logger.error("Error calling tool: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(error_response["status_code"])
            self.write(json.dumps(error_response))
