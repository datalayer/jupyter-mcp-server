# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Remote Backend Implementation

This backend uses the existing jupyter_nbmodel_client, jupyter_kernel_client,
and jupyter_server_api packages to connect to remote Jupyter servers.

For MCP_SERVER mode, this maintains 100% backward compatibility with the existing implementation.
"""

from typing import Optional, Any, Union, Literal
from mcp.types import ImageContent
from jupyter_mcp_server.jupyter_extension.backends.base import Backend

# Note: This is a placeholder that delegates to existing server.py logic
# The actual implementation will be refactored from server.py in a later step
# For now, this establishes the pattern


class RemoteBackend(Backend):
    """
    Backend that connects to remote Jupyter servers using HTTP/WebSocket APIs.
    
    Uses:
    - jupyter_nbmodel_client.NbModelClient for notebook operations
    - jupyter_kernel_client.KernelClient for kernel operations  
    - jupyter_server_api.JupyterServerClient for server operations
    """
    
    def __init__(self, document_url: str, document_token: str, runtime_url: str, runtime_token: str):
        """
        Initialize remote backend.
        
        Args:
            document_url: URL of Jupyter server for document operations
            document_token: Authentication token for document server
            runtime_url: URL of Jupyter server for runtime operations
            runtime_token: Authentication token for runtime server
        """
        self.document_url = document_url
        self.document_token = document_token
        self.runtime_url = runtime_url
        self.runtime_token = runtime_token
    
    # Notebook operations
    
    async def get_notebook_content(self, path: str) -> dict[str, Any]:
        """Get notebook content via remote API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
    
    async def list_notebooks(self, path: str = "") -> list[str]:
        """List notebooks via remote API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
    
    async def notebook_exists(self, path: str) -> bool:
        """Check if notebook exists via remote API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
    
    async def create_notebook(self, path: str) -> dict[str, Any]:
        """Create notebook via remote API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
    
    # Cell operations
    
    async def read_cells(
        self, 
        path: str, 
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Read cells via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def append_cell(
        self, 
        path: str, 
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """Append cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def insert_cell(
        self,
        path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """Insert cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def delete_cell(self, path: str, cell_index: int) -> None:
        """Delete cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def overwrite_cell(
        self,
        path: str,
        cell_index: int,
        new_source: Union[str, list[str]]
    ) -> tuple[str, str]:
        """Overwrite cell via nbmodel_client."""
        # TODO: Implement using jupyter_nbmodel_client
        raise NotImplementedError("To be refactored from server.py")
    
    # Kernel operations
    
    async def get_or_create_kernel(self, path: str, kernel_id: Optional[str] = None) -> str:
        """Get or create kernel via kernel_client."""
        # TODO: Implement using jupyter_kernel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def execute_cell(
        self,
        path: str,
        cell_index: int,
        kernel_id: str,
        timeout_seconds: int = 300
    ) -> list[Union[str, ImageContent]]:
        """Execute cell via kernel_client."""
        # TODO: Implement using jupyter_kernel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def interrupt_kernel(self, kernel_id: str) -> None:
        """Interrupt kernel via kernel_client."""
        # TODO: Implement using jupyter_kernel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def restart_kernel(self, kernel_id: str) -> None:
        """Restart kernel via kernel_client."""
        # TODO: Implement using jupyter_kernel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def shutdown_kernel(self, kernel_id: str) -> None:
        """Shutdown kernel via kernel_client."""
        # TODO: Implement using jupyter_kernel_client
        raise NotImplementedError("To be refactored from server.py")
    
    async def list_kernels(self) -> list[dict[str, Any]]:
        """List kernels via server API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
    
    async def kernel_exists(self, kernel_id: str) -> bool:
        """Check if kernel exists via server API."""
        # TODO: Implement using jupyter_server_api
        raise NotImplementedError("To be refactored from server.py")
