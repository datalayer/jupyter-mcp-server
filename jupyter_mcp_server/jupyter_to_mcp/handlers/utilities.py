# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Utility endpoint handlers for the Jupyter-to-MCP adapter."""

import json
import logging

from .base import MCPBaseHandler
from jupyter_mcp_server.__version__ import __version__

logger = logging.getLogger(__name__)


class HealthHandler(MCPBaseHandler):
    """Handler for health check endpoint."""
    
    async def get(self):
        """Health check endpoint."""
        try:
            # Test MCP server connectivity
            session_id = self.get_session_id()
            
            try:
                # Try to get capabilities to test MCP connectivity
                await self.adapter.get_capabilities(session_id)
                mcp_status = "connected"
            except Exception as e:
                logger.warning("MCP server not reachable: %s", e)
                mcp_status = "disconnected"
            
            response = {
                "status": "healthy",
                "version": __version__,
                "capabilities": ["tools", "initialization", "health"],
                "mcp_server_status": mcp_status,
                "protocol_version": "2025-03-26"
            }
            
            if mcp_status == "disconnected":
                self.set_status(503)  # Service Unavailable
                response["status"] = "degraded"
            
            self.write(json.dumps(response))
            
        except Exception as e:
            logger.error("Health check failed: %s", e)
            error_response = {
                "status": "unhealthy",
                "version": __version__,
                "error": str(e)
            }
            self.set_status(500)
            self.write(json.dumps(error_response))
