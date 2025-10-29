# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Delete cell tool implementation."""

from typing import Any, Optional
from pathlib import Path
import nbformat
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_notebook_model, clean_notebook_outputs


class DeleteCellTool(BaseTool):
    """Tool to delete specific cells from a notebook."""

    def _get_cell_source(self, cell: Any) -> str:
        """Get the cell source from the cell"""
        cell_source = cell.get("source", "")
        if isinstance(cell_source, list):
            return "".join(cell_source)
        else:
            return str(cell_source)

    async def _delete_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_indices: list[int]
    ) -> list:
        """Delete cell using YDoc (collaborative editing mode).
        
        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_indices: List of indices of cells to delete
            
        Returns:
            NotebookNode
        """
        nb = await get_notebook_model(serverapp, notebook_path)
        if nb:
            if max(cell_indices) >= len(nb):
                raise ValueError(
                    f"Cell index {max(cell_indices)} is out of range. Notebook has {len(nb)} cells."
                )
            
            cells = nb.delete_many_cells(cell_indices)
            return cells
        else:
            # YDoc not available, use file operations
            return await self._delete_cell_file(notebook_path, cell_indices)
    
    async def _delete_cell_file(
        self,
        notebook_path: str,
        cell_indices: list[int]
    ) -> list:
        """Delete cell using file operations (non-collaborative mode).
        
        Args:
            notebook_path: Absolute path to the notebook
            cell_indices: List of indices of cells to delete
            
        Returns:
            List of deleted cells
        """
        # Read notebook file as version 4 for consistency
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        
        clean_notebook_outputs(notebook)
        
        if max(cell_indices) >= len(notebook.cells):
            raise ValueError(
                f"Cell index {max(cell_indices)} is out of range. Notebook has {len(notebook.cells)} cells."
            )
        
        deleted_cells = []
        for cell_index in cell_indices:
            cell = notebook.cells[cell_index]
            result = {
                "index": cell_index,
                "cell_type": cell.cell_type,
                "source": self._get_cell_source(cell),
            }
            deleted_cells.append(result)
        
        # Delete the cell
        for cell_index in sorted(cell_indices, reverse=True):
            notebook.cells.pop(cell_index)
        
        # Write back to file
        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)
        
        return deleted_cells
    
    async def _delete_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_indices: list[int]
    ) -> list:
        """Delete cell using WebSocket connection (MCP_SERVER mode).
        
        Args:
            notebook_manager: Notebook manager instance
            cell_indices: List of indices of cells to delete
            
        Returns:
            List of deleted cell information
        """
        async with notebook_manager.get_current_connection() as notebook:
            if max(cell_indices) >= len(notebook):
                raise ValueError(
                    f"Cell index {max(cell_indices)} is out of range. Notebook has {len(notebook)} cells."
                )

            cells = notebook.delete_many_cells(cell_indices)
            return cells
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        # Tool-specific parameters
        cell_indices: list[int] = None,
        include_source: bool = True,
        **kwargs
    ) -> str:
        """Execute the delete_cell tool.
        
        This tool supports three modes of operation:
        
        1. JUPYTER_SERVER mode with YDoc (collaborative):
           - Checks if notebook is open in a collaborative session
           - Uses YDoc for real-time collaborative editing
           - Changes are immediately visible to all connected users
           
        2. JUPYTER_SERVER mode without YDoc (file-based):
           - Falls back to direct file operations using nbformat
           - Suitable when notebook is not actively being edited
           
        3. MCP_SERVER mode (WebSocket):
           - Uses WebSocket connection to remote Jupyter server
           - Accesses YDoc through NbModelClient
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to delete (0-based)
            **kwargs: Additional parameters
            
        Returns:
            Success message
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # JUPYTER_SERVER mode: Try YDoc first, fall back to file operations
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            
            context = get_server_context()
            serverapp = context.serverapp
            notebook_path, _ = get_current_notebook_context(notebook_manager)

            # Resolve to absolute path
            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)
            
            if serverapp:
                # Try YDoc approach first
                cells = await self._delete_cell_ydoc(serverapp, notebook_path, cell_indices)
            else:
                # Fall back to file operations
                cells = await self._delete_cell_file(notebook_path, cell_indices)
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            cells = await self._delete_cell_websocket(notebook_manager, cell_indices)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        info_list = []
        for cell_info in cells:
            info_list.append(f"Cell {cell_info['index']} ({cell_info['cell_type']}) deleted successfully.")
            if include_source:
                info_list.append(f"deleted cell source:\n{cell_info['source']}")
                info_list.append("\n---\n")
        
        return "\n".join(info_list)
