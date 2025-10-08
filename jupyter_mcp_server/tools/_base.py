# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Base classes and enums for MCP tools."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from jupyter_server_api import JupyterServerClient
from jupyter_kernel_client import KernelClient


class ServerMode(str, Enum):
    """Enum to indicate which server mode the tool is running in."""
    MCP_SERVER = "mcp_server"
    JUPYTER_SERVER = "jupyter_server"


class BaseTool(ABC):
    """Abstract base class for all MCP tools.
    
    Each tool must implement the execute method which handles both
    MCP_SERVER mode (using HTTP clients) and JUPYTER_SERVER mode
    (using direct API access to serverapp managers).
    """
    
    def __init__(self):
        """Initialize the tool."""
        pass
    
    @abstractmethod
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[KernelClient] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        **kwargs
    ) -> Any:
        """Execute the tool logic.
        
        Args:
            mode: ServerMode indicating MCP_SERVER or JUPYTER_SERVER
            server_client: JupyterServerClient for HTTP access (MCP_SERVER mode)
            kernel_client: KernelClient for kernel HTTP access (MCP_SERVER mode)
            contents_manager: Direct access to contents manager (JUPYTER_SERVER mode)
            kernel_manager: Direct access to kernel manager (JUPYTER_SERVER mode)
            kernel_spec_manager: Direct access to kernel spec manager (JUPYTER_SERVER mode)
            **kwargs: Tool-specific parameters
            
        Returns:
            Tool execution result (type varies by tool)
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the tool name."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Return the tool description."""
        pass
