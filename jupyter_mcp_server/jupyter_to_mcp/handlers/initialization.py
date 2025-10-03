# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Initialization endpoint handlers for the Jupyter-to-MCP adapter."""

import json
import logging

import tornado

from .base import MCPBaseHandler

logger = logging.getLogger(__name__)


class InitializeHandler(MCPBaseHandler):
    """Handler for MCP session initialization."""
    
    @tornado.web.authenticated
    async def post(self):
        """Initialize MCP session.
        
        Request body:
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {...},
            "clientInfo": {...}
        }
        """
        try:
            session_id = self.get_session_id()
            request_data = self.get_json_body()
            
            client_info = request_data.get("clientInfo", {})
            
            # Initialize session
            init_response = await self.adapter.initialize(session_id, client_info)
            
            # Set session header for client to use
            self.set_header("X-Session-ID", session_id)
            
            self.write(json.dumps(init_response.model_dump()))
            
        except Exception as e:
            logger.error("Error initializing session: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(error_response["status_code"])
            self.write(json.dumps(error_response))
    
    @tornado.web.authenticated
    async def get(self):
        """Get initialization information (capabilities negotiation)."""
        try:
            session_id = self.get_session_id()
            
            # Get capabilities without full initialization
            capabilities = await self.adapter.get_capabilities(session_id)
            
            response = {
                "protocolVersion": "2025-03-26",
                "capabilities": capabilities.model_dump(),
                "serverInfo": {
                    "name": "jupyter-mcp-server-http-adapter",
                    "version": "1.0.0",
                    "description": "HTTP adapter for Jupyter MCP Server"
                }
            }
            
            self.write(json.dumps(response))
            
        except Exception as e:
            logger.error("Error getting initialization info: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(error_response["status_code"])
            self.write(json.dumps(error_response))


class CapabilitiesHandler(MCPBaseHandler):
    """Handler for getting server capabilities."""
    
    @tornado.web.authenticated
    async def get(self):
        """Get server capabilities."""
        try:
            session_id = self.get_session_id()
            capabilities = await self.adapter.get_capabilities(session_id)
            
            self.write(json.dumps(capabilities.model_dump()))
            
        except Exception as e:
            logger.error("Error getting capabilities: %s", e)
            error_response = await self.handle_request_exception(e)
            self.set_status(error_response["status_code"])
            self.write(json.dumps(error_response))
