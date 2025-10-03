# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Base handler classes for the Jupyter-to-MCP adapter."""

import json
import logging
from typing import Any, Dict, Optional

import tornado
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.extension.handler import ExtensionHandlerMixin

from jupyter_mcp_server.jupyter_to_mcp.adapter import MCPAdapter
from jupyter_mcp_server.jupyter_to_mcp.utils import extract_session_id_from_headers, format_error_response

logger = logging.getLogger(__name__)


class MCPBaseHandler(ExtensionHandlerMixin, JupyterHandler):
    """Base handler for MCP HTTP endpoints."""
    
    def initialize(self, **kwargs):
        """Initialize the handler with an MCP adapter."""
        super().initialize(**kwargs)
        self.adapter = kwargs.get('adapter')
        
    def data_received(self, chunk):
        """Handle streaming data - not used in this implementation."""
        pass
    
    def get_session_id(self) -> str:
        """Get or create session ID from headers."""
        return extract_session_id_from_headers(self.request.headers)
    
    def set_cors_headers(self):
        """Set CORS headers for cross-origin requests."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Session-ID")
    
    def set_default_headers(self):
        """Set default headers including CORS."""
        super().set_default_headers()
        self.set_cors_headers()
        self.set_header("Content-Type", "application/json")
    
    @tornado.web.authenticated
    async def options(self):
        """Handle CORS preflight requests."""
        self.set_status(200)
        self.finish()
    
    def write_error(self, status_code: int, **kwargs):
        """Write error response in MCP format."""
        self.set_header("Content-Type", "application/json")
        
        exc_info = kwargs.get("exc_info")
        if exc_info:
            _, exc_value, _ = exc_info
            message = str(exc_value)
        else:
            message = f"HTTP {status_code} error"
        
        error_response = format_error_response(message, status_code)
        self.write(json.dumps(error_response))
        self.finish()
    
    async def handle_request_exception(self, exception: Exception) -> Dict[str, Any]:
        """Handle exceptions and convert to error response."""
        logger.error("Handler exception: %s", exception)
        
        # Map common exceptions to appropriate HTTP status codes
        if isinstance(exception, (ValueError, TypeError)):
            status_code = 400
        elif isinstance(exception, FileNotFoundError):
            status_code = 404
        elif isinstance(exception, PermissionError):
            status_code = 403
        else:
            status_code = 500
        
        return format_error_response(str(exception), status_code)
    
    def get_json_body(self) -> Dict[str, Any]:
        """Get and parse JSON request body."""
        try:
            if hasattr(self.request, 'body') and self.request.body:
                return json.loads(self.request.body.decode('utf-8'))
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON in request body: {e}") from e
    
    def get_query_argument_safe(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Safely get query argument."""
        try:
            return self.get_query_argument(name, default)
        except tornado.web.MissingArgumentError:
            return default
