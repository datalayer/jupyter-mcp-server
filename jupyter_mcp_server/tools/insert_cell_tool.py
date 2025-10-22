# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert cell tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
import nbformat
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_jupyter_ydoc, clean_notebook_outputs
from jupyter_mcp_server.models import Notebook


class InsertCellTool(BaseTool):
    """Tool to insert a cell at a specified position."""
    
    async def _insert_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[int, int]:
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
        ydoc = await get_jupyter_ydoc(serverapp, file_id)
        
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
            
            return actual_index, len(ydoc.ycells)
        else:
            # YDoc not available, use file operations
            return await self._insert_cell_file(notebook_path, cell_index, cell_type, cell_source)
    
    async def _insert_cell_file(
        self,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[int, int]:
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
        clean_notebook_outputs(notebook)
        
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
        
        return actual_index, len(notebook.cells)
    
    async def _insert_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[int, Notebook]:
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
            actual_index = cell_index if cell_index != -1 else len(notebook)
            if actual_index < 0 or actual_index > len(notebook):
                raise ValueError(f"Cell index {cell_index} out of range")
            
            notebook.insert_cell(actual_index, cell_source, cell_type)
            
            return actual_index, Notebook(**notebook.as_dict())

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
                actual_index, new_total_cells = await self._insert_cell_ydoc(serverapp, notebook_path, cell_index, cell_type, cell_source)
            else:
                # Fall back to file operations
                actual_index, new_total_cells = await self._insert_cell_file(notebook_path, cell_index, cell_type, cell_source)
            
            # Load notebook using same API
            notebook_path = notebook_manager.get_current_notebook_path()
            model = await contents_manager.get(notebook_path, content=True, type='notebook')
            if 'content' not in model:
                raise ValueError(f"Could not read notebook content from {notebook_path}")
            notebook = Notebook(**model['content'])
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            actual_index, notebook = await self._insert_cell_websocket(notebook_manager, cell_index, cell_type, cell_source)
            new_total_cells = len(notebook)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        info_list = [f"Cell inserted successfully at index {actual_index} ({cell_type})!"]
        info_list.append(f"Notebook now has {new_total_cells} cells, showing surrounding cells:")
        # near to end
        if new_total_cells - actual_index < 5:
            start_index = max(0, new_total_cells - 10)
        else:
            start_index = max(0, actual_index - 5)
        info_list.append(notebook.format_output(response_format="brief", start_index=start_index, limit=10))
        return "\n".join(info_list)
        

