# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Server Context Management

This module provides a singleton to track the execution context (MCP_SERVER vs JUPYTER_SERVER)
and provide access to Jupyter Server resources when running as an extension.
"""

from typing import Optional, Literal, TYPE_CHECKING
import threading

if TYPE_CHECKING:
    from jupyter_server.serverapp import ServerApp


class ServerContext:
    """
    Singleton managing server execution context.
    
    This class tracks whether tools are running in standalone MCP_SERVER mode
    or embedded JUPYTER_SERVER mode, and provides access to server resources.
    """
    
    _instance: Optional['ServerContext'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._context_type: Literal["MCP_SERVER", "JUPYTER_SERVER"] = "MCP_SERVER"
        self._serverapp: Optional['ServerApp'] = None
        self._document_url: Optional[str] = None
        self._runtime_url: Optional[str] = None
    
    @property
    def context_type(self) -> Literal["MCP_SERVER", "JUPYTER_SERVER"]:
        """Get the current server context type."""
        return self._context_type
    
    @property
    def serverapp(self) -> Optional['ServerApp']:
        """Get the Jupyter ServerApp instance (only available in JUPYTER_SERVER mode)."""
        return self._serverapp
    
    @property
    def document_url(self) -> Optional[str]:
        """Get the configured document URL."""
        return self._document_url
    
    @property
    def runtime_url(self) -> Optional[str]:
        """Get the configured runtime URL."""
        return self._runtime_url
    
    def update(
        self,
        context_type: Literal["MCP_SERVER", "JUPYTER_SERVER"],
        serverapp: Optional['ServerApp'] = None,
        document_url: Optional[str] = None,
        runtime_url: Optional[str] = None
    ):
        """
        Update the server context.
        
        Args:
            context_type: The type of server context
            serverapp: Jupyter ServerApp instance (required for JUPYTER_SERVER mode)
            document_url: Document URL configuration
            runtime_url: Runtime URL configuration
        """
        with self._lock:
            self._context_type = context_type
            self._serverapp = serverapp
            self._document_url = document_url
            self._runtime_url = runtime_url
            
            if context_type == "JUPYTER_SERVER" and serverapp is None:
                raise ValueError("serverapp is required when context_type is JUPYTER_SERVER")
    
    def is_local_document(self) -> bool:
        """Check if document operations should use local serverapp."""
        return (
            self._context_type == "JUPYTER_SERVER" 
            and self._document_url == "local"
        )
    
    def is_local_runtime(self) -> bool:
        """Check if runtime operations should use local serverapp."""
        return (
            self._context_type == "JUPYTER_SERVER" 
            and self._runtime_url == "local"
        )
    
    def get_contents_manager(self):
        """
        Get the Jupyter contents manager (only available in JUPYTER_SERVER mode with local access).
        
        Returns:
            ContentsManager instance or None
        """
        if self._serverapp is not None:
            return self._serverapp.contents_manager
        return None
    
    def get_kernel_manager(self):
        """
        Get the Jupyter kernel manager (only available in JUPYTER_SERVER mode with local access).
        
        Returns:
            KernelManager instance or None
        """
        if self._serverapp is not None:
            return self._serverapp.kernel_manager
        return None
    
    def get_kernel_spec_manager(self):
        """
        Get the Jupyter kernel spec manager (only available in JUPYTER_SERVER mode with local access).
        
        Returns:
            KernelSpecManager instance or None
        """
        if self._serverapp is not None:
            return self._serverapp.kernel_spec_manager
        return None
    
    def get_session_manager(self):
        """
        Get the Jupyter session manager (only available in JUPYTER_SERVER mode with local access).
        
        Returns:
            SessionManager instance or None
        """
        if self._serverapp is not None:
            return self._serverapp.session_manager
        return None
    
    @property
    def session_manager(self):
        """
        Get the Jupyter session manager as a property (only available in JUPYTER_SERVER mode with local access).
        
        Returns:
            SessionManager instance or None
        """
        return self.get_session_manager()
    
    def reset(self):
        """Reset to default MCP_SERVER mode."""
        with self._lock:
            self._context_type = "MCP_SERVER"
            self._serverapp = None
            self._document_url = None
            self._runtime_url = None


# Global accessor
def get_server_context() -> ServerContext:
    """Get the global ServerContext singleton instance."""
    return ServerContext()
