# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Delete cell tool implementation."""

from typing import Any, Optional
from pathlib import Path
import nbformat
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context


class DeleteCellTool(BaseTool):
    """Tool to delete a specific cell from a notebook."""
    
    @property
    def name(self) -> str:
        return "delete_cell"
    
    @property
    def description(self) -> str:
        return """Delete a specific cell from the Jupyter notebook.
    
Args:
    cell_index: Index of the cell to delete (0-based)
    
Returns:
    str: Success message"""
    
    async def _get_jupyter_ydoc(self, serverapp: Any, file_id: str):
        """Get the YNotebook document if it's currently open in a collaborative session.
        
        This follows the jupyter_ai_tools pattern of accessing YDoc through the
        yroom_manager when the notebook is actively being edited.
        
        Args:
            serverapp: The Jupyter ServerApp instance
            file_id: The file ID for the document
            
        Returns:
            YNotebook instance or None if not in a collaborative session
        """
        try:
            yroom_manager = serverapp.web_app.settings.get("yroom_manager")
            if yroom_manager is None:
                return None
                
            room_id = f"json:notebook:{file_id}"
            
            if yroom_manager.has_room(room_id):
                yroom = yroom_manager.get_room(room_id)
                notebook = await yroom.get_jupyter_ydoc()
                return notebook
        except Exception:
            # YDoc not available, will fall back to file operations
            pass
        
        return None
    
    def _get_cell_index_from_id(self, ydoc, cell_id: str) -> Optional[int]:
        """Find cell index by cell ID in YDoc."""
        for i, ycell in enumerate(ydoc.ycells):
            if ycell.get("id") == cell_id:
                return i
        return None
    
    async def _delete_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int
    ) -> str:
        """Delete cell using YDoc (collaborative editing mode).
        
        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_index: Index of cell to delete
            
        Returns:
            Success message
        """
        # Get file_id from file_id_manager
        file_id_manager = serverapp.web_app.settings.get("file_id_manager")
        if file_id_manager is None:
            raise RuntimeError("file_id_manager not available in serverapp")
        
        file_id = file_id_manager.get_id(notebook_path)
        
        # Try to get YDoc
        ydoc = await self._get_jupyter_ydoc(serverapp, file_id)
        
        if ydoc:
            # Notebook is open in collaborative mode, use YDoc
            if cell_index < 0 or cell_index >= len(ydoc.ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc.ycells)} cells."
                )
            
            cell_type = ydoc.ycells[cell_index].get("cell_type", "unknown")
            
            # Delete the cell from YDoc
            del ydoc.ycells[cell_index]
            
            return f"Cell {cell_index} ({cell_type}) deleted successfully."
        else:
            # YDoc not available, use file operations
            return await self._delete_cell_file(notebook_path, cell_index)
    
    async def _delete_cell_file(
        self,
        notebook_path: str,
        cell_index: int
    ) -> str:
        """Delete cell using file operations (non-collaborative mode).
        
        Args:
            notebook_path: Absolute path to the notebook
            cell_index: Index of cell to delete
            
        Returns:
            Success message
        """
        # Read notebook file as version 4 for consistency
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        
        # Clean transient fields from outputs
        from jupyter_mcp_server.utils import _clean_notebook_outputs
        _clean_notebook_outputs(notebook)
        
        # Validate index
        if cell_index < 0 or cell_index >= len(notebook.cells):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(notebook.cells)} cells."
            )
        
        cell_type = notebook.cells[cell_index].cell_type
        
        # Delete the cell
        notebook.cells.pop(cell_index)
        
        # Write back to file
        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)
        
        return f"Cell {cell_index} ({cell_type}) deleted successfully."
    
    async def _delete_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int
    ) -> str:
        """Delete cell using WebSocket connection (MCP_SERVER mode).
        
        Args:
            notebook_manager: Notebook manager instance
            cell_index: Index of cell to delete
            
        Returns:
            Success message
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            cell_type = ydoc._ycells[cell_index].get("cell_type", "unknown")

            # Delete the cell
            del ydoc._ycells[cell_index]

            return f"Cell {cell_index} ({cell_type}) deleted successfully."
    
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
        cell_index: int = None,
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
                return await self._delete_cell_ydoc(serverapp, notebook_path, cell_index)
            else:
                # Fall back to file operations
                return await self._delete_cell_file(notebook_path, cell_index)
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            return await self._delete_cell_websocket(notebook_manager, cell_index)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
