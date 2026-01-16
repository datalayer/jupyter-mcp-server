# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tool for dynamically connecting to Jupyter server with URL and token."""

import logging
from typing import Any, Optional

from jupyter_mcp_server.config import set_config, reset_config
from jupyter_mcp_server.tools._base import BaseTool, ServerMode

logger = logging.getLogger(__name__)


class ConnectJupyterTool(BaseTool):
    """Connect to a Jupyter server with dynamic URL and token."""
    
    async def execute(
        self,
        mode: ServerMode,
        jupyter_url: str,
        jupyter_token: Optional[str] = None,
        provider: str = "jupyter",
        **kwargs
    ) -> str:
        """Execute the connect to Jupyter server operation.
        
        Args:
            mode: ServerMode indicating MCP_SERVER or JUPYTER_SERVER
            jupyter_url: The Jupyter server URL to connect to
            jupyter_token: The Jupyter server token for authentication
            provider: Provider type (default: "jupyter")
            **kwargs: Additional keyword arguments
            
        Returns:
            Success message with connection information
        """
        
        logger.info(
            f"Connecting to Jupyter server - URL: {jupyter_url}, "
            f"Token: {'***' if jupyter_token else 'None'}"
        )
        
        try:
            # Update configuration with new connection parameters
            set_config(
                provider=provider,
                runtime_url=jupyter_url,
                runtime_token=jupyter_token,
                document_url=jupyter_url,
                document_token=jupyter_token,
            )
            
            # Reset ServerContext to pick up new configuration
            # Import here to avoid circular import issues
            from jupyter_mcp_server.server_context import ServerContext
            ServerContext.reset()
            
            # Build connection info message
            connection_info = [
                f"Successfully connected to Jupyter server: {jupyter_url}",
                f"Provider: {provider}",
            ]
            
            if jupyter_token:
                connection_info.append("Authentication: Token-based")
            else:
                connection_info.append("Authentication: None (anonymous)")
            
            return "\n".join(connection_info)
            
        except Exception as e:
            error_msg = f"Failed to connect to Jupyter server {jupyter_url}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)