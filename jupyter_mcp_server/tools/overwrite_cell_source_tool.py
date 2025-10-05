# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Overwrite cell source tool implementation."""

import difflib
from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


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
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to overwrite (0-based)
            cell_source: New cell source
            **kwargs: Additional parameters
            
        Returns:
            Success message with diff
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            
            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )
            
            # Get original cell content
            old_source_raw = ydoc._ycells[cell_index].get("source", "")
            
            # Convert source to string if it's a list (which is common in notebooks)
            if isinstance(old_source_raw, list):
                old_source = "".join(old_source_raw)
            else:
                old_source = str(old_source_raw)
            
            # Set new cell content
            notebook.set_cell_source(cell_index, cell_source)
            
            # Generate diff
            old_lines = old_source.splitlines(keepends=False)
            new_lines = cell_source.splitlines(keepends=False)
            
            diff_lines = list(difflib.unified_diff(
                old_lines, 
                new_lines, 
                lineterm='',
                n=3  # Number of context lines
            ))
            
            # Remove the first 3 lines (file headers) from unified_diff output
            if len(diff_lines) > 3:
                diff_content = '\n'.join(diff_lines[3:])
            else:
                diff_content = "no changes detected"
            
            if not diff_content.strip():
                return f"Cell {cell_index} overwritten successfully - no changes detected"
            
            return f"Cell {cell_index} overwritten successfully!\n\n```diff\n{diff_content}\n```"
