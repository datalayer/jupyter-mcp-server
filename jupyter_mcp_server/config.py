# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

from typing import Optional
from pydantic import BaseModel, Field


class JupyterMCPConfig(BaseModel):
    """Singleton configuration object for Jupyter MCP Server."""
    
    # Transport configuration
    transport: str = Field(default="stdio", description="The transport to use for the MCP server")
    
    # Provider configuration  
    provider: str = Field(default="jupyter", description="The provider to use for the document and runtime")
    
    # Runtime configuration
    runtime_url: str = Field(default="http://localhost:8888", description="The runtime URL to use, or 'local' for direct serverapp access")
    start_new_runtime: bool = Field(default=False, description="Start a new runtime or use an existing one")
    runtime_id: Optional[str] = Field(default=None, description="The kernel ID to use")
    runtime_token: Optional[str] = Field(default=None, description="The runtime token to use for authentication")
    
    # Document configuration
    document_url: str = Field(default="http://localhost:8888", description="The document URL to use, or 'local' for direct serverapp access")
    document_id: str = Field(default="notebook.ipynb", description="The document id to use")
    document_token: Optional[str] = Field(default=None, description="The document token to use for authentication")
    
    # Server configuration
    port: int = Field(default=4040, description="The port to use for the Streamable HTTP transport")
    
    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        arbitrary_types_allowed = True
    
    def is_local_document(self) -> bool:
        """Check if document URL is set to local."""
        return self.document_url == "local"
    
    def is_local_runtime(self) -> bool:
        """Check if runtime URL is set to local."""
        return self.runtime_url == "local"


# Singleton instance
_config_instance: Optional[JupyterMCPConfig] = None


def get_config() -> JupyterMCPConfig:
    """Get the singleton configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = JupyterMCPConfig()
    return _config_instance


def set_config(**kwargs) -> JupyterMCPConfig:
    """Set configuration values and return the config instance.
    
    Automatically handles string representations of None by removing them from kwargs,
    allowing defaults to be used instead. This handles cases where environment variables
    or MCP clients pass "None" as a string.
    """
    def should_skip(value):
        """Check if value is a string representation of None that should be skipped."""
        return isinstance(value, str) and value.lower() in ("none", "null", "")
    
    # Filter out string "None" values and let defaults be used instead
    # For optional fields (tokens, runtime_id), convert to actual None
    normalized_kwargs = {}
    for key, value in kwargs.items():
        if should_skip(value):
            # For optional fields, set to None; for required fields, skip (use default)
            if key in ("runtime_token", "document_token", "runtime_id"):
                normalized_kwargs[key] = None
            # For required string fields like runtime_url, document_url, skip the key
            # to let the default value be used
            # Do nothing - skip this key
        else:
            normalized_kwargs[key] = value
    
    global _config_instance
    if _config_instance is None:
        _config_instance = JupyterMCPConfig(**normalized_kwargs)
    else:
        for key, value in normalized_kwargs.items():
            if hasattr(_config_instance, key):
                setattr(_config_instance, key, value)
    return _config_instance


def reset_config() -> JupyterMCPConfig:
    """Reset configuration to defaults."""
    global _config_instance
    _config_instance = JupyterMCPConfig()
    return _config_instance
