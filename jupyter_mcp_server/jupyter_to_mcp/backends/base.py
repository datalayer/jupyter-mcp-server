# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Abstract Backend Interface

Defines the contract for all backend implementations (Remote and Local).
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Union, Literal
from mcp.types import ImageContent


class Backend(ABC):
    """
    Abstract backend for notebook and kernel operations.
    
    Implementations:
    - RemoteBackend: Uses jupyter_nbmodel_client, jupyter_kernel_client, jupyter_server_api
    - LocalBackend: Uses local serverapp.contents_manager and serverapp.kernel_manager
    """
    
    # Notebook operations
    
    @abstractmethod
    async def get_notebook_content(self, path: str) -> dict[str, Any]:
        """
        Retrieve notebook content.
        
        Args:
            path: Path to the notebook file
            
        Returns:
            Dictionary with notebook content (cells, metadata)
        """
        pass
    
    @abstractmethod
    async def list_notebooks(self, path: str = "") -> list[str]:
        """
        List all notebooks in a directory.
        
        Args:
            path: Directory path (empty string for root)
            
        Returns:
            List of notebook paths
        """
        pass
    
    @abstractmethod
    async def notebook_exists(self, path: str) -> bool:
        """
        Check if a notebook exists.
        
        Args:
            path: Path to the notebook file
            
        Returns:
            True if notebook exists
        """
        pass
    
    @abstractmethod
    async def create_notebook(self, path: str) -> dict[str, Any]:
        """
        Create a new notebook.
        
        Args:
            path: Path for the new notebook
            
        Returns:
            Created notebook content
        """
        pass
    
    # Cell operations (via notebook connection)
    
    @abstractmethod
    async def read_cells(
        self, 
        path: str, 
        start_index: Optional[int] = None,
        end_index: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        Read cells from a notebook.
        
        Args:
            path: Notebook path
            start_index: Start cell index (None for all)
            end_index: End cell index (None for all)
            
        Returns:
            List of cell dictionaries
        """
        pass
    
    @abstractmethod
    async def append_cell(
        self, 
        path: str, 
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """
        Append a cell to notebook.
        
        Args:
            path: Notebook path
            cell_type: Type of cell
            source: Cell source code/markdown
            
        Returns:
            Index of appended cell
        """
        pass
    
    @abstractmethod
    async def insert_cell(
        self,
        path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        source: Union[str, list[str]]
    ) -> int:
        """
        Insert a cell at specific index.
        
        Args:
            path: Notebook path
            cell_index: Where to insert
            cell_type: Type of cell
            source: Cell source
            
        Returns:
            Index of inserted cell
        """
        pass
    
    @abstractmethod
    async def delete_cell(self, path: str, cell_index: int) -> None:
        """
        Delete a cell from notebook.
        
        Args:
            path: Notebook path
            cell_index: Index of cell to delete
        """
        pass
    
    @abstractmethod
    async def overwrite_cell(
        self,
        path: str,
        cell_index: int,
        new_source: Union[str, list[str]]
    ) -> tuple[str, str]:
        """
        Overwrite cell content.
        
        Args:
            path: Notebook path
            cell_index: Index of cell to overwrite
            new_source: New source content
            
        Returns:
            Tuple of (old_source, new_source) for diff generation
        """
        pass
    
    # Kernel operations
    
    @abstractmethod
    async def get_or_create_kernel(self, path: str, kernel_id: Optional[str] = None) -> str:
        """
        Get existing kernel or create new one for a notebook.
        
        Args:
            path: Notebook path
            kernel_id: Specific kernel ID (None to create new)
            
        Returns:
            Kernel ID
        """
        pass
    
    @abstractmethod
    async def execute_cell(
        self,
        path: str,
        cell_index: int,
        kernel_id: str,
        timeout_seconds: int = 300
    ) -> list[Union[str, ImageContent]]:
        """
        Execute a cell and return outputs.
        
        Args:
            path: Notebook path
            cell_index: Index of cell to execute
            kernel_id: Kernel to use
            timeout_seconds: Execution timeout
            
        Returns:
            List of cell outputs
        """
        pass
    
    @abstractmethod
    async def interrupt_kernel(self, kernel_id: str) -> None:
        """
        Interrupt a running kernel.
        
        Args:
            kernel_id: Kernel to interrupt
        """
        pass
    
    @abstractmethod
    async def restart_kernel(self, kernel_id: str) -> None:
        """
        Restart a kernel.
        
        Args:
            kernel_id: Kernel to restart
        """
        pass
    
    @abstractmethod
    async def shutdown_kernel(self, kernel_id: str) -> None:
        """
        Shutdown a kernel.
        
        Args:
            kernel_id: Kernel to shutdown
        """
        pass
    
    @abstractmethod
    async def list_kernels(self) -> list[dict[str, Any]]:
        """
        List all running kernels.
        
        Returns:
            List of kernel information dictionaries
        """
        pass
    
    @abstractmethod
    async def kernel_exists(self, kernel_id: str) -> bool:
        """
        Check if a kernel exists.
        
        Args:
            kernel_id: Kernel ID to check
            
        Returns:
            True if kernel exists
        """
        pass
