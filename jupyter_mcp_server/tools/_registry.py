# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Tool registry and integration module."""

from typing import Dict, Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.config import get_config


class ToolRegistry:
    """Registry for managing and executing MCP tools."""
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._notebook_manager: Optional[NotebookManager] = None
    
    def register(self, tool: BaseTool):
        """Register a tool instance."""
        self._tools[tool.name] = tool
    
    def set_notebook_manager(self, notebook_manager: NotebookManager):
        """Set the notebook manager instance."""
        self._notebook_manager = notebook_manager
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self):
        """List all registered tools."""
        return list(self._tools.values())
    
    async def execute_tool(
        self,
        tool_name: str,
        mode: ServerMode,
        **kwargs
    ) -> Any:
        """Execute a tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            **kwargs: Tool-specific parameters
            
        Returns:
            Tool execution result
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found")
        
        # Prepare common parameters based on mode
        config = get_config()
        
        if mode == ServerMode.MCP_SERVER:
            # Create HTTP clients for remote access
            server_client = JupyterServerClient(
                base_url=config.runtime_url,
                token=config.runtime_token
            )
            kernel_client = KernelClient(
                server_url=config.runtime_url,
                token=config.runtime_token,
                kernel_id=config.runtime_id
            )
            
            return await tool.execute(
                mode=mode,
                server_client=server_client,
                kernel_client=kernel_client,
                contents_manager=None,
                kernel_manager=None,
                kernel_spec_manager=None,
                notebook_manager=self._notebook_manager,
                server_url=config.runtime_url,
                token=config.runtime_token,
                **kwargs
            )
        
        else:  # JUPYTER_SERVER mode
            # Get managers from ServerContext
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            context = get_server_context()
            
            contents_manager = context.get_contents_manager()
            kernel_manager = context.get_kernel_manager()
            kernel_spec_manager = context.get_kernel_spec_manager()
            
            return await tool.execute(
                mode=mode,
                server_client=None,
                kernel_client=None,
                contents_manager=contents_manager,
                kernel_manager=kernel_manager,
                kernel_spec_manager=kernel_spec_manager,
                notebook_manager=self._notebook_manager,
                server_url=config.runtime_url,
                token=config.runtime_token,
                **kwargs
            )


# Global registry instance
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry instance."""
    return _registry


def register_tool(tool: BaseTool):
    """Register a tool with the global registry."""
    _registry.register(tool)
