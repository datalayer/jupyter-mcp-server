# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unified Notebook and Kernel Management Module

This module provides centralized management for Jupyter notebooks and kernels,
replacing the scattered global variable approach with a unified architecture.
"""

from typing import Dict, Any, Optional, Callable, Union
from types import TracebackType

from jupyter_nbmodel_client import NbModelClient, get_notebook_websocket_url
from jupyter_kernel_client import KernelClient

from .config import get_config


class NotebookConnection:
    """
    Context manager for Notebook connections that handles the lifecycle
    of NbModelClient instances.
    
    Note: This is only used in MCP_SERVER mode with remote Jupyter servers that have RTC enabled.
    In JUPYTER_SERVER mode (local), notebook content is accessed directly via contents_manager.
    """
    
    def __init__(self, notebook_info: Dict[str, str], is_local: bool = False):
        self.notebook_info = notebook_info
        self.is_local = is_local
        self._notebook: Optional[NbModelClient] = None
    
    async def __aenter__(self) -> NbModelClient:
        """Enter context, establish notebook connection."""
        if self.is_local:
            raise ValueError(
                "NotebookConnection cannot be used in local/JUPYTER_SERVER mode. "
                "Cell operations in local mode should use contents_manager directly to read notebook JSON files."
            )
        
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
        self._current_notebook: Optional[str] = None  # Currently active notebook
    
    def __contains__(self, name: str) -> bool:
        """Check if a notebook is managed by this instance."""
        return name in self._notebooks
    
    def __iter__(self):
        """Iterate over notebook name, info pairs."""
        return iter(self._notebooks.items())
    
    def add_notebook(
        self, 
        name: str, 
        kernel: Union[KernelClient, Dict[str, Any]],  # Can be KernelClient or dict with kernel metadata
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        path: Optional[str] = None
    ) -> None:
        """
        Add a notebook to the manager.
        
        Args:
            name: Unique identifier for the notebook
            kernel: Kernel client instance (MCP_SERVER mode) or kernel metadata dict (JUPYTER_SERVER mode)
            server_url: Jupyter server URL (optional, uses config default). Use "local" for JUPYTER_SERVER mode.
            token: Authentication token (optional, uses config default)
            path: Notebook file path (optional, uses config default)
        """
        config = get_config()
        
        # Determine if this is local (JUPYTER_SERVER) mode or HTTP (MCP_SERVER) mode
        is_local_mode = server_url == "local"
        
        self._notebooks[name] = {
            "kernel": kernel,
            "is_local": is_local_mode,
            "notebook_info": {
                "server_url": server_url or config.document_url,
                "token": token or config.document_token,
                "path": path or config.document_id
            }
        }
        
        # For backward compatibility: if this is the first notebook or it's "default",
        # set it as the current notebook
        if self._current_notebook is None or name == self._default_notebook_name:
            self._current_notebook = name
    
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
                notebook_data = self._notebooks[name]
                is_local = notebook_data.get("is_local", False)
                kernel = notebook_data["kernel"]
                
                # Only stop kernel if it's an HTTP KernelClient (MCP_SERVER mode)
                # In JUPYTER_SERVER mode, kernel is just metadata, actual kernel managed elsewhere
                if not is_local and kernel and hasattr(kernel, 'stop'):
                    kernel.stop()
            except Exception:
                # Ignore errors during kernel cleanup
                pass
            finally:
                del self._notebooks[name]
                
                # If we removed the current notebook, update the current pointer
                if self._current_notebook == name:
                    # Set to another notebook if available, prefer "default" for compatibility
                    if self._default_notebook_name in self._notebooks:
                        self._current_notebook = self._default_notebook_name
                    elif self._notebooks:
                        # Set to the first available notebook
                        self._current_notebook = next(iter(self._notebooks.keys()))
                    else:
                        # No notebooks left
                        self._current_notebook = None
            return True
        return False
    
    def get_kernel(self, name: str) -> Optional[Union[KernelClient, Dict[str, Any]]]:
        """
        Get the kernel for a specific notebook.
        
        Args:
            name: Notebook identifier
            
        Returns:
            Kernel client (MCP_SERVER mode) or kernel metadata dict (JUPYTER_SERVER mode), or None if not found
        """
        if name in self._notebooks:
            return self._notebooks[name]["kernel"]
        return None
    
    def get_kernel_id(self, name: str) -> Optional[str]:
        """
        Get the kernel ID for a specific notebook.
        
        Args:
            name: Notebook identifier
            
        Returns:
            Kernel ID string or None if not found
        """
        if name in self._notebooks:
            kernel = self._notebooks[name]["kernel"]
            # Handle both KernelClient objects and kernel metadata dicts
            if isinstance(kernel, dict):
                return kernel.get("id")
            elif hasattr(kernel, 'kernel_id'):
                return kernel.kernel_id
        return None
    
    def is_local_notebook(self, name: str) -> bool:
        """
        Check if a notebook is using local (JUPYTER_SERVER) mode.
        
        Args:
            name: Notebook identifier
            
        Returns:
            True if local mode, False otherwise
        """
        if name in self._notebooks:
            return self._notebooks[name].get("is_local", False)
        return False
    
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
    
    def ensure_kernel_alive(self, name: str, kernel_factory: Callable[[], KernelClient]) -> KernelClient:
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
    
    def set_current_notebook(self, name: str) -> bool:
        """
        Set the currently active notebook.
        
        Args:
            name: Notebook identifier
            
        Returns:
            True if set successfully, False if notebook doesn't exist
        """
        if name in self._notebooks:
            self._current_notebook = name
            return True
        return False
    
    def get_current_notebook(self) -> Optional[str]:
        """
        Get the name of the currently active notebook.
        
        Returns:
            Current notebook name or None if no active notebook
        """
        return self._current_notebook
    
    def get_current_connection(self) -> NotebookConnection:
        """
        Get the connection for the currently active notebook.
        For backward compatibility, defaults to "default" if no current notebook is set.
        
        Returns:
            NotebookConnection context manager for the current notebook
            
        Raises:
            ValueError: If no notebooks exist and no default config is available
        """
        current = self._current_notebook or self._default_notebook_name
        
        # For backward compatibility: if the requested notebook doesn't exist but we're 
        # asking for default, create a connection using the default config
        if current not in self._notebooks and current == self._default_notebook_name:
            # Return a connection using default configuration
            config = get_config()
            return NotebookConnection({
                "server_url": config.document_url,
                "token": config.document_token,
                "path": config.document_id
            })
        
        return self.get_notebook_connection(current)
    
    def get_current_notebook_path(self) -> Optional[str]:
        """
        Get the file path of the currently active notebook.
        
        Returns:
            Notebook file path or None if no active notebook
        """
        current = self._current_notebook or self._default_notebook_name
        if current in self._notebooks:
            return self._notebooks[current]["notebook_info"].get("path")
        return None
    
    def list_all_notebooks(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all managed notebooks.
        
        Returns:
            Dictionary with notebook names as keys and their info as values
        """
        result = {}
        for name, notebook_data in self._notebooks.items():
            kernel = notebook_data["kernel"]
            notebook_info = notebook_data["notebook_info"]
            
            # Check kernel status
            kernel_status = "unknown"
            if kernel:
                try:
                    kernel_status = "alive" if hasattr(kernel, 'is_alive') and kernel.is_alive() else "dead"
                except Exception:
                    kernel_status = "error"
            else:
                kernel_status = "not_initialized"
            
            result[name] = {
                "path": notebook_info.get("path", ""),
                "kernel_status": kernel_status,
                "is_current": name == self._current_notebook
            }
        
        return result
