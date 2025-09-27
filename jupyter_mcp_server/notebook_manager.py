# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unified Notebook and Kernel Management Module

This module provides centralized management for Jupyter notebooks and kernels,
replacing the scattered global variable approach with a unified architecture.
"""

from typing import Dict, Any, Optional
from types import TracebackType
from contextlib import asynccontextmanager

from jupyter_nbmodel_client import NbModelClient, get_notebook_websocket_url
from jupyter_kernel_client import KernelClient

from .config import get_config


class NotebookConnection:
    """
    Context manager for Notebook connections that handles the lifecycle
    of NbModelClient instances.
    """
    
    def __init__(self, notebook_info: Dict[str, str]):
        self.notebook_info = notebook_info
        self._notebook: Optional[NbModelClient] = None
    
    async def __aenter__(self) -> NbModelClient:
        """Enter context, establish notebook connection."""
        config = get_config()
        ws_url = get_notebook_websocket_url(
            server_url=self.notebook_info.get("server_url", config.document_url),
            token=self.notebook_info.get("token", config.document_token),
            path=self.notebook_info.get("path", config.document_id),
            provider=config.provider
        )
        self._notebook = NbModelClient(ws_url)
        await self._notebook.__aenter__()
        return self._notebook
    
    async def __aexit__(
        self, 
        exc_type: Optional[type], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[TracebackType]
    ) -> None:
        """Exit context, clean up connection."""
        if self._notebook:
            await self._notebook.__aexit__(exc_type, exc_val, exc_tb)


class NotebookManager:
    """
    Centralized manager for multiple notebooks and their corresponding kernels.
    
    This class replaces the global kernel variable approach with a unified
    management system that supports both single and multiple notebook scenarios.
    """
    
    def __init__(self):
        self._notebooks: Dict[str, Dict[str, Any]] = {}
        self._default_notebook_name = "default"
    
    def __contains__(self, name: str) -> bool:
        """Check if a notebook is managed by this instance."""
        return name in self._notebooks
    
    def __iter__(self):
        """Iterate over notebook name, info pairs."""
        return iter(self._notebooks.items())
    
    def add_notebook(
        self, 
        name: str, 
        kernel: KernelClient,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        path: Optional[str] = None
    ) -> None:
        """
        Add a notebook to the manager.
        
        Args:
            name: Unique identifier for the notebook
            kernel: Kernel client instance
            server_url: Jupyter server URL (optional, uses config default)
            token: Authentication token (optional, uses config default)
            path: Notebook file path (optional, uses config default)
        """
        config = get_config()
        self._notebooks[name] = {
            "kernel": kernel,
            "notebook_info": {
                "server_url": server_url or config.document_url,
                "token": token or config.document_token,
                "path": path or config.document_id
            }
        }
    
    def remove_notebook(self, name: str) -> bool:
        """
        Remove a notebook from the manager.
        
        Args:
            name: Notebook identifier
            
        Returns:
            True if removed successfully, False if not found
        """
        if name in self._notebooks:
            try:
                kernel = self._notebooks[name]["kernel"]
                if kernel and hasattr(kernel, 'stop'):
                    kernel.stop()
            except Exception:
                # Ignore errors during kernel cleanup
                pass
            finally:
                del self._notebooks[name]
            return True
        return False
    
    def get_kernel(self, name: str) -> Optional[KernelClient]:
        """
        Get the kernel for a specific notebook.
        
        Args:
            name: Notebook identifier
            
        Returns:
            Kernel client or None if not found
        """
        if name in self._notebooks:
            return self._notebooks[name]["kernel"]
        return None
    
    def get_notebook_connection(self, name: str) -> NotebookConnection:
        """
        Get a context manager for notebook connection.
        
        Args:
            name: Notebook identifier
            
        Returns:
            NotebookConnection context manager
            
        Raises:
            ValueError: If notebook doesn't exist
        """
        if name not in self._notebooks:
            raise ValueError(f"Notebook '{name}' does not exist in manager")
        
        return NotebookConnection(self._notebooks[name]["notebook_info"])
    
    def restart_notebook(self, name: str) -> bool:
        """
        Restart the kernel for a specific notebook.
        
        Args:
            name: Notebook identifier
            
        Returns:
            True if restarted successfully, False otherwise
        """
        if name in self._notebooks:
            try:
                kernel = self._notebooks[name]["kernel"]
                if kernel and hasattr(kernel, 'restart'):
                    kernel.restart()
                return True
            except Exception:
                return False
        return False
    
    def is_empty(self) -> bool:
        """Check if the manager is empty (no notebooks)."""
        return len(self._notebooks) == 0
    
    def ensure_kernel_alive(self, name: str, kernel_factory) -> KernelClient:
        """
        Ensure a kernel is alive, create if necessary.
        
        Args:
            name: Notebook identifier
            kernel_factory: Function to create a new kernel
            
        Returns:
            The alive kernel instance
        """
        kernel = self.get_kernel(name)
        if kernel is None or not hasattr(kernel, 'is_alive') or not kernel.is_alive():
            # Create new kernel
            new_kernel = kernel_factory()
            self.add_notebook(name, new_kernel)
            return new_kernel
        return kernel
