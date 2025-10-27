# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert cell tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
import nbformat
import threading
from uuid import uuid4
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_jupyter_ydoc, clean_notebook_outputs
from jupyter_mcp_server.models import Notebook

from nbformat import current_nbformat, versions
current_api = versions[current_nbformat]


class InsertCellTool(BaseTool):
    """Tool to insert a cell at a specified position."""
    
    def __init__(self):
        """Initialize the InsertCellTool with thread safety support."""
        super().__init__()
        self._lock = threading.Lock()
        """Lock to prevent updating the YDoc in multiple threads simultaneously.
        
        That may induce a Panic error; see:
        https://github.com/datalayer/jupyter-nbmodel-client/issues/12
        """
        self._changes_origin = hash(
            uuid4().hex
        )  # Hashed ID for doc modification origin - pycrdt uses hashed origin
    
    def _validate_cell_insertion_params(
        self,
        cell_index: int,
        total_cells: int,
        cell_type: str
    ) -> int:
        """Validate and normalize cell insertion parameters.
        
        Args:
            cell_index: Target index for insertion (-1 for append)
            total_cells: Total number of cells in the notebook
            cell_type: Type of cell to insert
            
        Returns:
            Normalized actual_index for insertion
            
        Raises:
            IndexError: When cell_index is out of valid range
            ValueError: When cell_type is invalid
        """
        if cell_index < -1 or cell_index > total_cells:
            raise IndexError(
                f"Index {cell_index} is outside valid range [-1, {total_cells}]. "
                f"Use -1 to append at end."
            )
        if cell_type not in ["code", "markdown", "raw"]:
            raise ValueError(
                f"Invalid cell type: {cell_type}. Must be one of: 'code', 'markdown', 'raw'."
            )
        
        # Normalize -1 to append position
        actual_index = cell_index if cell_index != -1 else total_cells
        return actual_index
    
    def _create_cell(
        self,
        cell_type: Literal["code", "markdown"],
        cell_source: str,
        **kwargs
    ) -> dict[str, Any]:
        """Create a new cell of the specified type using nbformat API.
        
        Args:
            cell_type: Type of cell ("code", "markdown")
            cell_source: Source content for the cell
            **kwargs: Additional parameters to pass to cell creation
            
        Returns:
            Cell dictionary compatible with nbformat
        """
        source = cell_source or ""
        
        if cell_type == "code":
            return current_api.new_code_cell(source=source, **kwargs)
        elif cell_type == "markdown":
            return current_api.new_markdown_cell(source=source, **kwargs)
    
    async def _insert_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[Notebook, int, int]:
        """Insert cell using YDoc (collaborative editing mode).
        
        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert ("code", "markdown")
            cell_source: Source content for the cell
            
        Returns:
            Tuple of (notebook, actual_index, total_cells_after_insertion)
            
        Raises:
            RuntimeError: When file_id_manager is not available
            IndexError: When cell_index is out of range
            ValueError: When cell_type is invalid
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
            
            # Validate insertion parameters
            actual_index = self._validate_cell_insertion_params(
                cell_index, total_cells, cell_type
            )
            
            # Create cell using unified method
            cell = self._create_cell(cell_type, cell_source)
            ycell = ydoc.create_ycell(cell)
            
            # Insert at the specified position with thread safety and transaction support
            with self._lock:
                with ydoc._ydoc.transaction(origin=self._changes_origin):
                    # Insert at the specified position
                    if actual_index >= total_cells:
                        ydoc.ycells.append(ycell)
                    else:
                        ydoc.ycells.insert(actual_index, ycell)
                
                notebook = Notebook(**ydoc.source)
            
            return notebook, actual_index, len(ydoc.ycells)
        else:
            # YDoc not available, use file operations
            return await self._insert_cell_file(notebook_path, cell_index, cell_type, cell_source)
    
    async def _insert_cell_file(
        self,
        notebook_path: str,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[Notebook, int, int]:
        """Insert cell using file operations (non-collaborative mode).
                
        Args:
            notebook_path: Absolute path to the notebook
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert ("code", "markdown")
            cell_source: Source content for the cell
            
        Returns:
            Tuple of (notebook, actual_index, total_cells_after_insertion)
            
        Raises:
            IndexError: When cell_index is out of range
            ValueError: When cell_type is invalid
        """
        # Read notebook file
        with open(notebook_path, "r", encoding="utf-8") as f:
            # Read as version 4 (latest) to ensure consistency and support for cell IDs
            notebook = nbformat.read(f, as_version=4)
        
        # Clean any transient fields from existing outputs (kernel protocol field not in nbformat schema)
        clean_notebook_outputs(notebook)
        
        total_cells = len(notebook.cells)
        
        # Validate insertion parameters
        actual_index = self._validate_cell_insertion_params(
            cell_index, total_cells, cell_type
        )
        
        # Create and insert the cell using unified method
        new_cell = self._create_cell(cell_type, cell_source)
        notebook.cells.insert(actual_index, new_cell)
        
        # Write back to file
        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)
        
        notebook = Notebook(**notebook)
        
        return notebook, actual_index, len(notebook.cells)
    
    async def _insert_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_type: Literal["code", "markdown"],
        cell_source: str
    ) -> tuple[Notebook, int, int]:
        """Insert cell using WebSocket connection (MCP_SERVER mode).
        
        Args:
            notebook_manager: Notebook manager instance
            cell_index: Index to insert at (-1 for append)
            cell_type: Type of cell to insert ("code", "markdown")
            cell_source: Source content for the cell
            
        Returns:
            Tuple of (notebook, actual_index, total_cells_after_insertion)
            
        Raises:
            IndexError: When cell_index is out of range
            ValueError: When cell_type is invalid
        """
        async with notebook_manager.get_current_connection() as notebook:
            total_cells = len(notebook)
            
            # Validate insertion parameters
            actual_index = self._validate_cell_insertion_params(
                cell_index, total_cells, cell_type
            )
            
            # Use the unified insert_cell method pattern
            # The remote notebook should have: insert_cell(index, source, cell_type)
            notebook.insert_cell(actual_index, cell_source, cell_type)
            
            return Notebook(**notebook.as_dict()), actual_index, len(notebook)

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
        
        This tool supports three modes of operation following a unified insertion pattern:
        
        1. JUPYTER_SERVER mode with YDoc (collaborative):
           - Checks if notebook is open in a collaborative session
           - Uses YDoc for real-time collaborative editing
           - Changes are immediately visible to all connected users
           - Operations protected by thread locks and YDoc transactions
           
        2. JUPYTER_SERVER mode without YDoc (file-based):
           - Falls back to direct file operations using nbformat
           - Suitable when notebook is not actively being edited
           
        3. MCP_SERVER mode (WebSocket):
           - Uses WebSocket connection to remote Jupyter server
           - Delegates to remote notebook's unified insert_cell method
        
        Thread Safety:
        - YDoc mode: Protected by thread lock + YDoc transaction (atomic)
        - File mode: No synchronization needed (single-threaded file I/O)
        - WebSocket mode: Remote server handles synchronization
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Target index for insertion (0-based, -1 to append)
            cell_type: Type of cell ("code", "markdown")
            cell_source: Source content for the cell
            **kwargs: Additional parameters
            
        Returns:
            Success message with surrounding cells info
            
        Raises:
            ValueError: When mode is invalid or required clients are missing
            IndexError: When cell_index is out of range
            ValueError: When cell_type is invalid
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
                # Try YDoc approach first (with thread safety and transactions)
                notebook, actual_index, new_total_cells = await self._insert_cell_ydoc(
                    serverapp, notebook_path, cell_index, cell_type, cell_source
                )
            else:
                # Fall back to file operations
                notebook, actual_index, new_total_cells = await self._insert_cell_file(
                    notebook_path, cell_index, cell_type, cell_source
                )
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection with unified insert_cell pattern
            notebook, actual_index, new_total_cells = await self._insert_cell_websocket(
                notebook_manager, cell_index, cell_type, cell_source
            )
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        info_list = [f"Cell inserted successfully at index {actual_index} ({cell_type})!"]
        info_list.append(f"Notebook now has {new_total_cells} cells, showing surrounding cells:")
        # Show context near the insertion
        if new_total_cells - actual_index < 5:
            start_index = max(0, new_total_cells - 10)
        else:
            start_index = max(0, actual_index - 5)
        info_list.append(notebook.format_output(response_format="brief", start_index=start_index, limit=10))
        return "\n".join(info_list)
        

