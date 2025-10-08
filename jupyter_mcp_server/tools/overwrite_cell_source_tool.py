# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Overwrite cell source tool implementation."""

import difflib
import nbformat
from pathlib import Path
from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context


class OverwriteCellSourceTool(BaseTool):
    """Tool to overwrite the source of an existing cell."""
    
    @property
    def name(self) -> str:
        return "overwrite_cell_source"
    
    @property
    def description(self) -> str:
        return """Overwrite the source of an existing cell.
Note this does not execute the modified cell by itself.

Args:
    cell_index: Index of the cell to overwrite (0-based)
    cell_source: New cell source - must match existing cell type

Returns:
    str: Success message with diff showing changes made"""
    
    async def _get_jupyter_ydoc(self, serverapp: Any, file_id: str):
        """Get the YNotebook document if it's currently open in a collaborative session."""
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
            pass
        
        return None
    
    def _generate_diff(self, old_source: str, new_source: str) -> str:
        """Generate unified diff between old and new source."""
        old_lines = old_source.splitlines(keepends=False)
        new_lines = new_source.splitlines(keepends=False)
        
        diff_lines = list(difflib.unified_diff(
            old_lines, 
            new_lines, 
            lineterm='',
            n=3  # Number of context lines
        ))
        
        # Remove the first 3 lines (file headers) from unified_diff output
        if len(diff_lines) > 3:
            return '\n'.join(diff_lines[3:])
        return "no changes detected"
    
    async def _overwrite_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell using YDoc (collaborative editing mode)."""
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
            
            # Get original cell content
            old_source_raw = ydoc.ycells[cell_index].get("source", "")
            if isinstance(old_source_raw, list):
                old_source = "".join(old_source_raw)
            else:
                old_source = str(old_source_raw)
            
            # Set new cell source
            ydoc.ycells[cell_index]["source"] = cell_source
            
            # Generate diff
            diff_content = self._generate_diff(old_source, cell_source)
            
            if not diff_content.strip() or diff_content == "no changes detected":
                return f"Cell {cell_index} overwritten successfully - no changes detected"
            
            return f"Cell {cell_index} overwritten successfully!\n\n```diff\n{diff_content}\n```"
        else:
            # YDoc not available, use file operations
            return await self._overwrite_cell_file(notebook_path, cell_index, cell_source)
    
    async def _overwrite_cell_file(
        self,
        notebook_path: str,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell using file operations (non-collaborative mode)."""
        # Read notebook file as version 4 for consistency
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        
        # Clean transient fields from outputs
        from jupyter_mcp_server.utils import _clean_notebook_outputs
        _clean_notebook_outputs(notebook)
        
        if cell_index < 0 or cell_index >= len(notebook.cells):
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
        
        # Generate diff
        diff_content = self._generate_diff(old_source, cell_source)
        
        if not diff_content.strip() or diff_content == "no changes detected":
            return f"Cell {cell_index} overwritten successfully - no changes detected"
        
        return f"Cell {cell_index} overwritten successfully!\n\n```diff\n{diff_content}\n```"
    
    async def _overwrite_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_source: str
    ) -> str:
        """Overwrite cell using WebSocket connection (MCP_SERVER mode)."""
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            
            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )
            
            # Get original cell content
            old_source_raw = ydoc._ycells[cell_index].get("source", "")
            if isinstance(old_source_raw, list):
                old_source = "".join(old_source_raw)
            else:
                old_source = str(old_source_raw)
            
            # Set new cell content
            notebook.set_cell_source(cell_index, cell_source)
            
            # Generate diff
            diff_content = self._generate_diff(old_source, cell_source)
            
            if not diff_content.strip() or diff_content == "no changes detected":
                return f"Cell {cell_index} overwritten successfully - no changes detected"
            
            return f"Cell {cell_index} overwritten successfully!\n\n```diff\n{diff_content}\n```"
    
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
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to overwrite (0-based)
            cell_source: New cell source
            **kwargs: Additional parameters
            
        Returns:
            Success message with diff
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
                return await self._overwrite_cell_ydoc(serverapp, notebook_path, cell_index, cell_source)
            else:
                return await self._overwrite_cell_file(notebook_path, cell_index, cell_source)
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            return await self._overwrite_cell_websocket(notebook_manager, cell_index, cell_source)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
