# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Overwrite cell source tool implementation."""

import difflib
import nbformat
from pathlib import Path
from typing import Any, Optional
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_notebook_model, clean_notebook_outputs


class OverwriteCellSourceTool(BaseTool):
    """Tool to overwrite the source of an existing cell."""
    
    def _generate_diff(self, old_source: str, new_source: str) -> str:
        """Generate unified diff between old and new source."""
        old_lines = old_source.splitlines(keepends=False)
        new_lines = new_source.splitlines(keepends=False)
        
        diff_lines = list[str](difflib.unified_diff(
            old_lines, 
            new_lines, 
            lineterm='',
            n=3  # Number of context lines
        ))
        
        if len(diff_lines) > 3:
            return '\n'.join(diff_lines)
        return "no changes detected"
    
    async def _overwrite_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell source using YDoc (collaborative editing mode).
        
        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_index: Index of the cell to overwrite
            cell_source: New cell source content
            
        Returns:
            Diff showing changes made
            
        Raises:
            RuntimeError: When file_id_manager is not available
            ValueError: When cell_index is out of range
        """
        # Get notebook model
        nb = await get_notebook_model(serverapp, notebook_path)

        if nb:
            # Notebook is open in collaborative mode, use YDoc
            if cell_index >= len(nb):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(nb)} cells."
                )
            
            old_source = nb.get_cell_source(cell_index)
            if isinstance(old_source, list):
                old_source = "".join(old_source)
            else:
                old_source = str(old_source)
            nb.set_cell_source(cell_index, cell_source)
            
            return self._generate_diff(old_source, cell_source)
        else:
            # YDoc not available, use file operations
            return await self._overwrite_cell_file(notebook_path, cell_index, cell_source)
    
    async def _overwrite_cell_file(
        self,
        notebook_path: str,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell using file operations (non-collaborative mode).
        
        Args:
            notebook_path: Path to the notebook file
            cell_index: Index of the cell to overwrite
            cell_source: New cell source content
            
        Returns:
            Diff showing changes made
            
        Raises:
            ValueError: When cell_index is out of range
        """
        # Read notebook file as version 4 for consistency
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        clean_notebook_outputs(notebook)
        
        if cell_index >= len(notebook.cells):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(notebook.cells)} cells."
            )
        
        # Get original cell content
        old_source = notebook.cells[cell_index].source
        
        # Set new cell source
        notebook.cells[cell_index].source = cell_source
        
        # Write back to file
        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)
        
        return self._generate_diff(old_source, cell_source)
    
    async def _overwrite_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell using WebSocket connection (MCP_SERVER mode).
        
        Args:
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to overwrite
            cell_source: New cell source content
            
        Returns:
            Diff showing changes made
            
        Raises:
            ValueError: When cell_index is out of range
        """
        async with notebook_manager.get_current_connection() as notebook:
            if cell_index >= len(notebook):
                raise ValueError(f"Cell index {cell_index} out of range")
            
            # Get original cell content
            old_source = notebook.get_cell_source(cell_index)
            if isinstance(old_source, list):
                old_source = "".join(old_source)
            else:
                old_source = str(old_source)
            notebook.set_cell_source(cell_index, cell_source)
            return self._generate_diff(old_source, cell_source)
    
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
        cell_source: str = None,
        **kwargs
    ) -> str:
        """Execute the overwrite_cell_source tool.
        
        This tool supports three modes of operation:
        
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
           - Delegates to remote notebook's set_cell_source method
        
        Thread Safety:
        - YDoc mode: Protected by thread lock + YDoc transaction (atomic)
        - File mode: No synchronization needed (single-threaded file I/O)
        - WebSocket mode: Remote server handles synchronization
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to overwrite (0-based)
            cell_source: New cell source
            **kwargs: Additional parameters
            
        Returns:
            Success message with diff
            
        Raises:
            ValueError: When mode is invalid or required clients are missing
            ValueError: When cell_index is out of range
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
                diff = await self._overwrite_cell_ydoc(serverapp, notebook_path, cell_index, cell_source)
            else:
                # Fall back to file operations
                diff = await self._overwrite_cell_file(notebook_path, cell_index, cell_source)
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection with remote transaction management
            diff = await self._overwrite_cell_websocket(notebook_manager, cell_index, cell_source)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        if not diff.strip() or diff == "no changes detected":
            return f"Cell {cell_index} overwritten successfully - no changes detected"
        else:
            return f"Cell {cell_index} overwritten successfully!\n\n```diff\n{diff}\n```"
