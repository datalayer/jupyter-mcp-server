# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert cell tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
import nbformat
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context
from jupyter_mcp_server.utils import get_surrounding_cells_info


class InsertCellTool(BaseTool):
    """Tool to insert a cell at a specified position."""
    
    @property
    def name(self) -> str:
        return "insert_cell"
    
    @property
    def description(self) -> str:
        return """Insert a cell to specified position.

Args:
    cell_index: target index for insertion (0-based). Use -1 to append at end.
    cell_type: Type of cell to insert ("code" or "markdown")
    cell_source: Source content for the cell

Returns:
    str: Success message and the structure of its surrounding cells (up to 5 cells above and 5 cells below)"""
    
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
    
    async def _insert_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> str:
        """Insert cell using YDoc (collaborative editing mode).
        
        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert
            cell_source: Source content for the cell
            
        Returns:
            Success message with surrounding cells info
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
            total_cells = len(ydoc.ycells)
            actual_index = cell_index if cell_index != -1 else total_cells
            
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            # Create the cell
            cell = {
                "cell_type": cell_type,
                "source": "",
            }
            ycell = ydoc.create_ycell(cell)
            
            # Insert at the specified position
            if actual_index >= total_cells:
                ydoc.ycells.append(ycell)
            else:
                ydoc.ycells.insert(actual_index, ycell)
            
            # Write content to the cell collaboratively
            if cell_source:
                # Set the source directly on the ycell
                ycell["source"] = cell_source
            
            # Get surrounding cells info (simplified version for YDoc)
            new_total_cells = len(ydoc.ycells)
            surrounding_info = self._get_surrounding_cells_info_ydoc(ydoc, actual_index, new_total_cells)
            
            return f"Cell inserted successfully at index {actual_index} ({cell_type})!\n\nCurrent Surrounding Cells:\n{surrounding_info}"
        else:
            # YDoc not available, use file operations
            return await self._insert_cell_file(notebook_path, cell_index, cell_type, cell_source)
    
    def _get_surrounding_cells_info_ydoc(self, ydoc, center_index: int, total_cells: int) -> str:
        """Get info about surrounding cells from YDoc."""
        lines = []
        start_index = max(0, center_index - 5)
        end_index = min(total_cells, center_index + 6)
        
        for i in range(start_index, end_index):
            cell = ydoc.ycells[i]
            cell_type = cell.get("cell_type", "unknown")
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            first_line = source.split('\n')[0][:50] if source else "(empty)"
            marker = " <-- NEW" if i == center_index else ""
            lines.append(f"  [{i}] {cell_type}: {first_line}{marker}")
        
        return "\n".join(lines)
    
    async def _insert_cell_file(
        self,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> str:
        """Insert cell using file operations (non-collaborative mode).
        
        Args:
            notebook_path: Absolute path to the notebook
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert
            cell_source: Source content for the cell
            
        Returns:
            Success message with surrounding cells info
        """
        # Read notebook file
        with open(notebook_path, "r", encoding="utf-8") as f:
            # Read as version 4 (latest) to ensure consistency and support for cell IDs
            notebook = nbformat.read(f, as_version=4)
        
        # Clean any transient fields from existing outputs (kernel protocol field not in nbformat schema)
        self._clean_notebook_outputs(notebook)
        
        total_cells = len(notebook.cells)
        actual_index = cell_index if cell_index != -1 else total_cells
        
        if actual_index < 0 or actual_index > total_cells:
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
            )
        
        # Create and insert the cell
        if cell_type == "code":
            new_cell = nbformat.v4.new_code_cell(source=cell_source or "")
        elif cell_type == "markdown":
            new_cell = nbformat.v4.new_markdown_cell(source=cell_source or "")
        else:
            raise ValueError(f"Invalid cell_type: {cell_type}. Must be 'code' or 'markdown'.")
        
        notebook.cells.insert(actual_index, new_cell)
        
        # Write back to file
        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)
        
        # Get surrounding cells info
        new_total_cells = len(notebook.cells)
        surrounding_info = self._get_surrounding_cells_info_file(notebook, actual_index, new_total_cells)
        
        return f"Cell inserted successfully at index {actual_index} ({cell_type})!\n\nCurrent Surrounding Cells:\n{surrounding_info}"
    
    def _clean_notebook_outputs(self, notebook):
        """Remove transient fields from all cell outputs.
        
        The 'transient' field is part of the Jupyter kernel messaging protocol
        but is NOT part of the nbformat schema. This causes validation errors.
        
        Args:
            notebook: nbformat notebook object to clean (modified in place)
        """
        # Clean transient fields from outputs
        for cell in notebook.cells:
            if cell.cell_type == 'code' and hasattr(cell, 'outputs'):
                for output in cell.outputs:
                    if isinstance(output, dict) and 'transient' in output:
                        del output['transient']
    
    def _get_surrounding_cells_info_file(self, notebook, center_index: int, total_cells: int) -> str:
        """Get info about surrounding cells from nbformat notebook."""
        lines = []
        start_index = max(0, center_index - 5)
        end_index = min(total_cells, center_index + 6)
        
        for i in range(start_index, end_index):
            cell = notebook.cells[i]
            cell_type = cell.cell_type
            source = cell.source
            first_line = source.split('\n')[0][:50] if source else "(empty)"
            marker = " <-- NEW" if i == center_index else ""
            lines.append(f"  [{i}] {cell_type}: {first_line}{marker}")
        
        return "\n".join(lines)
    
    async def _insert_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> str:
        """Insert cell using WebSocket connection (MCP_SERVER mode).
        
        Args:
            notebook_manager: Notebook manager instance
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert
            cell_source: Source content for the cell
            
        Returns:
            Success message with surrounding cells info
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            total_cells = len(ydoc._ycells)
            
            actual_index = cell_index if cell_index != -1 else total_cells
                
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            if cell_type == "code":
                if actual_index == total_cells:
                    notebook.add_code_cell(cell_source)
                else:
                    notebook.insert_code_cell(actual_index, cell_source)
            elif cell_type == "markdown":
                if actual_index == total_cells:
                    notebook.add_markdown_cell(cell_source)
                else:
                    notebook.insert_markdown_cell(actual_index, cell_source)
            
            # Get surrounding cells info
            new_total_cells = len(ydoc._ycells)
            surrounding_info = get_surrounding_cells_info(notebook, actual_index, new_total_cells)
            
            return f"Cell inserted successfully at index {actual_index} ({cell_type})!\n\nCurrent Surrounding Cells:\n{surrounding_info}"
    
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
        cell_type: Literal["code", "markdown"] = None,
        cell_source: str = None,
        **kwargs
    ) -> str:
        """Execute the insert_cell tool.
        
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
            cell_index: Target index for insertion (0-based, -1 to append)
            cell_type: Type of cell ("code" or "markdown")
            cell_source: Source content for the cell
            **kwargs: Additional parameters
            
        Returns:
            Success message with surrounding cells info
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
                return await self._insert_cell_ydoc(serverapp, notebook_path, cell_index, cell_type, cell_source)
            else:
                # Fall back to file operations
                return await self._insert_cell_file(notebook_path, cell_index, cell_type, cell_source)
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            return await self._insert_cell_websocket(notebook_manager, cell_index, cell_type, cell_source)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
