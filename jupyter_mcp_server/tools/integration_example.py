# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Example integration of the new tool architecture into server.py.

This demonstrates how to:
1. Register tool instances with the registry
2. Wrap them with @mcp.tool() decorators
3. Determine the server mode and call tool.execute()
"""

from typing import Optional
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools._registry import get_tool_registry, register_tool
from jupyter_mcp_server.tools.list_notebook_tool import ListNotebookTool
from jupyter_mcp_server.tools.connect_notebook import ConnectNotebookTool
from jupyter_mcp_server.config import get_config


# Initialize and register tools
def initialize_tools():
    """Register all tool instances."""
    register_tool(ListNotebookTool())
    register_tool(ConnectNotebookTool())
    # ... register other tools as they are created
    

# Example of how to wrap a tool with @mcp.tool() decorator
def register_mcp_tools(mcp, notebook_manager):
    """Register tools with FastMCP server.
    
    Args:
        mcp: FastMCP instance
        notebook_manager: NotebookManager instance
    """
    registry = get_tool_registry()
    registry.set_notebook_manager(notebook_manager)
    
    @mcp.tool()
    async def list_notebook() -> str:
        """List all notebooks in the Jupyter server (including subdirectories) and show which ones are managed.
        
        To interact with a notebook, it has to be "managed". If a notebook is not managed, you can connect to it using the `connect_notebook` tool.
        
        Returns:
            str: TSV formatted table with notebook information including management status
        """
        # Determine server mode
        mode = _get_server_mode()
        
        # Execute the tool
        return await registry.execute_tool(
            "list_notebook",
            mode=mode
        )
    
    @mcp.tool()
    async def connect_notebook(
        notebook_name: str,
        notebook_path: str,
        mode: str = "connect",  # Renamed parameter to avoid conflict
        kernel_id: Optional[str] = None,
    ) -> str:
        """Connect to a notebook file or create a new one.
        
        Args:
            notebook_name: Unique identifier for the notebook
            notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb")
            mode: "connect" to connect to existing, "create" to create new
            kernel_id: Specific kernel ID to use (optional, will create new if not provided)
            
        Returns:
            str: Success message with notebook information
        """
        # Determine server mode
        server_mode = _get_server_mode()
        
        # Execute the tool
        return await registry.execute_tool(
            "connect_notebook",
            mode=server_mode,
            notebook_name=notebook_name,
            notebook_path=notebook_path,
            operation_mode=mode,  # Map to tool's parameter name
            kernel_id=kernel_id
        )
    
    # ... register other tools similarly


def _get_server_mode() -> ServerMode:
    """Determine which server mode we're running in.
    
    Returns:
        ServerMode.JUPYTER_SERVER if running as Jupyter extension with local access
        ServerMode.MCP_SERVER if running standalone with HTTP clients
    """
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        context = get_server_context()
        
        # Check if we're in Jupyter server mode with local access
        if (context.context_type == "JUPYTER_SERVER" and 
            context.is_local_document() and 
            context.get_contents_manager() is not None):
            return ServerMode.JUPYTER_SERVER
    except ImportError:
        # Context module not available, must be MCP_SERVER mode
        pass
    except Exception:
        # Any error checking context, default to MCP_SERVER
        pass
    
    return ServerMode.MCP_SERVER


# Example usage in server.py:
# 
# # After creating mcp and notebook_manager instances:
# initialize_tools()
# register_mcp_tools(mcp, notebook_manager)
