# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Clear cell output tool implementation."""

from pathlib import Path
from typing import Any

import nbformat
from jupyter_server_client import JupyterServerClient

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.utils import (
    clean_notebook_outputs,
    get_current_notebook_context,
    get_notebook_model,
)


class ClearCellOutputTool(BaseTool):
    """Tool to clear the outputs and execution count of a single code cell."""

    def _clear_notebook_model_cell(self, nb: Any, cell_index: int) -> int:
        """Clear outputs/execution_count on a NotebookModel-backed cell.

        Used for both the local YDoc (JUPYTER_SERVER) and remote WebSocket
        (MCP_SERVER) modes: NbModelClient subclasses NotebookModel and shares
        this same sequence protocol. NotebookModel exposes no dedicated
        clear-output method, so this reads the cell via __getitem__, mutates
        the two fields, and writes it back via __setitem__, which performs
        the update inside NotebookModel's own lock and YDoc transaction.

        Returns:
            Number of outputs that were cleared.
        """
        if cell_index < 0 or cell_index >= len(nb):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(nb)} cells."
            )

        cell = nb[cell_index]
        if cell.get("cell_type") != "code":
            raise ValueError(f"Cell {cell_index} is not a code cell, cannot clear output.")

        cleared_count = len(cell.get("outputs") or [])
        cell["outputs"] = []
        cell["execution_count"] = None
        nb[cell_index] = cell
        return cleared_count

    async def _clear_cell_output_ydoc(
        self, serverapp: Any, notebook_path: str, cell_index: int
    ) -> int:
        """Clear cell output using YDoc (collaborative editing mode).

        Args:
            serverapp: Jupyter ServerApp instance
            notebook_path: Path to the notebook
            cell_index: Index of the cell to clear (0-based)

        Returns:
            Number of outputs that were cleared.
        """
        nb = await get_notebook_model(serverapp, notebook_path)
        if nb:
            return self._clear_notebook_model_cell(nb, cell_index)
        else:
            # YDoc not available, use file operations
            return await self._clear_cell_output_file(notebook_path, cell_index)

    async def _clear_cell_output_file(self, notebook_path: str, cell_index: int) -> int:
        """Clear cell output using file operations (non-collaborative mode).

        Args:
            notebook_path: Absolute path to the notebook
            cell_index: Index of the cell to clear (0-based)

        Returns:
            Number of outputs that were cleared.

        Raises:
            ValueError: When cell_index is out of range or the cell is not code.
        """
        with open(notebook_path, encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        clean_notebook_outputs(notebook)

        if cell_index < 0 or cell_index >= len(notebook.cells):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(notebook.cells)} cells."
            )

        cell = notebook.cells[cell_index]
        if cell.cell_type != "code":
            raise ValueError(f"Cell {cell_index} is not a code cell, cannot clear output.")

        cleared_count = len(cell.outputs)
        cell.outputs = []
        cell.execution_count = None

        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)

        return cleared_count

    async def _clear_cell_output_websocket(
        self, notebook_manager: NotebookManager, cell_index: int
    ) -> int:
        """Clear cell output using WebSocket connection (MCP_SERVER mode).

        Args:
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to clear (0-based)

        Returns:
            Number of outputs that were cleared.
        """
        async with notebook_manager.get_current_connection() as notebook:
            return self._clear_notebook_model_cell(notebook, cell_index)

    async def execute(
        self,
        mode: ServerMode,
        server_client: JupyterServerClient | None = None,
        kernel_client: Any | None = None,
        contents_manager: Any | None = None,
        kernel_manager: Any | None = None,
        kernel_spec_manager: Any | None = None,
        notebook_manager: NotebookManager | None = None,
        # Tool-specific parameters
        cell_index: int = None,
        **kwargs,
    ) -> str:
        """Execute the clear_cell_output tool.

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
            cell_index: Index of the code cell to clear (0-based)
            **kwargs: Additional parameters

        Returns:
            Success message

        Raises:
            ValueError: When mode is invalid, cell_index is out of range, or the
                cell is not a code cell.
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
                cleared_count = await self._clear_cell_output_ydoc(
                    serverapp, notebook_path, cell_index
                )
            else:
                # Fall back to file operations
                cleared_count = await self._clear_cell_output_file(notebook_path, cell_index)

        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            cleared_count = await self._clear_cell_output_websocket(notebook_manager, cell_index)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")

        if cleared_count == 0:
            return f"Cell {cell_index} had no output to clear."
        return f"Cell {cell_index} output cleared successfully ({cleared_count} output(s) removed)."
