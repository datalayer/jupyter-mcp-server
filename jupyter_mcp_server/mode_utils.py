# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Utility functions for detecting and handling server mode."""

from typing import Tuple, Optional, Any
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.config import get_config


def get_server_mode_and_clients() -> Tuple[str, Optional[JupyterServerClient], Optional[Any], Optional[Any], Optional[Any]]:
    """Determine server mode and get appropriate clients/managers.
    
    Returns:
        Tuple of (mode, server_client, contents_manager, kernel_manager, kernel_spec_manager)
        - mode: "local" if using local API, "http" if using HTTP clients
        - server_client: JupyterServerClient or None
        - contents_manager: Local contents manager or None
        - kernel_manager: Local kernel manager or None  
        - kernel_spec_manager: Local kernel spec manager or None
    """
    config = get_config()
    
    # Check if we should use local API
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        context = get_server_context()
        
        if context.is_local_document() and context.get_contents_manager() is not None:
            # JUPYTER_SERVER mode with local API access
            return (
                "local",
                None,
                context.get_contents_manager(),
                context.get_kernel_manager(),
                context.get_kernel_spec_manager()
            )
    except (ImportError, Exception):
        # Context not available or error, fall through to HTTP mode
        pass
    
    # MCP_SERVER mode with HTTP clients
    server_client = JupyterServerClient(
        base_url=config.runtime_url,
        token=config.runtime_token
    )
    
    return ("http", server_client, None, None, None)


def is_local_mode() -> bool:
    """Check if running in local API mode.
    
    Returns:
        True if using local serverapp API, False if using HTTP clients
    """
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        context = get_server_context()
        return context.is_local_document() and context.get_contents_manager() is not None
    except (ImportError, Exception):
        return False
