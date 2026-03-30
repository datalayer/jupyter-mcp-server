# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Move cell tool implementation."""

from typing import Any, Optional
from pathlib import Path
import nbformat
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_notebook_model, clean_notebook_outputs
from jupyter_mcp_server.models import Notebook


class MoveCellTool(BaseTool):
    """Tool to move a cell from one position to another within a notebook."""

    def _validate_move(self, source_index: int, target_index: int, total_cells: int) -> None:
        """Validate move parameters.

        Args:
            source_index: Index of the cell to move (0-based)
            target_index: Destination index (0-based)
            total_cells: Total number of cells in the notebook

        Raises:
            IndexError: When source_index or target_index is out of range
        """
        if total_cells == 0:
            raise IndexError("Notebook has no cells.")
        if source_index < 0 or source_index >= total_cells:
            raise IndexError(
                f"Source index {source_index} is out of range. "
                f"Notebook has {total_cells} cells (valid: 0-{total_cells - 1})."
            )
        if target_index < 0 or target_index >= total_cells:
            raise IndexError(
                f"Target index {target_index} is out of range. "
                f"Notebook has {total_cells} cells (valid: 0-{total_cells - 1})."
            )

    @staticmethod
    def _apply_move(cells: list, source_index: int, target_index: int) -> list:
        """Reorder a list by moving an element from source to target index.

        Does not mutate the input list.

        Args:
            cells: List of cells (or any items)
            source_index: Index of the element to move
            target_index: Destination index

        Returns:
            A new list with the element moved.
        """
        if source_index == target_index:
            return list(cells)
        result = list(cells)
        cell = result.pop(source_index)
        result.insert(target_index, cell)
        return result

    async def _move_cell_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        source_index: int,
        target_index: int,
    ) -> tuple[Notebook, dict]:
        """Move cell using YDoc (collaborative editing mode).

        Returns:
            Tuple of (notebook, moved_cell_info)
        """
        nb = await get_notebook_model(serverapp, notebook_path)
        if nb:
            self._validate_move(source_index, target_index, len(nb))
            if source_index == target_index:
                cell_source = nb.get_cell_source(source_index)
                nb_dict = nb.as_dict()
                cell_type = nb_dict["cells"][source_index].get("cell_type", "code")
                return Notebook(**nb_dict), {"cell_type": cell_type, "source": cell_source}

            deleted = nb.delete_cell(source_index)
            cell_type = deleted.get("cell_type", "code")
            cell_source = deleted.get("source", "")
            if isinstance(cell_source, list):
                cell_source = "".join(cell_source)
            nb.insert_cell(target_index, cell_source, cell_type)
            return Notebook(**nb.as_dict()), {"cell_type": cell_type, "source": cell_source}
        else:
            return await self._move_cell_file(notebook_path, source_index, target_index)

    async def _move_cell_file(
        self,
        notebook_path: str,
        source_index: int,
        target_index: int,
    ) -> tuple[Notebook, dict]:
        """Move cell using file operations (non-collaborative mode).

        Returns:
            Tuple of (notebook, moved_cell_info)
        """
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        clean_notebook_outputs(notebook)
        self._validate_move(source_index, target_index, len(notebook.cells))

        moved_cell = notebook.cells[source_index]
        cell_info = {
            "cell_type": moved_cell.cell_type,
            "source": moved_cell.source if isinstance(moved_cell.source, str)
            else "".join(moved_cell.source),
        }

        if source_index != target_index:
            notebook.cells = self._apply_move(notebook.cells, source_index, target_index)
            with open(notebook_path, "w", encoding="utf-8") as f:
                nbformat.write(notebook, f)

        return Notebook(**notebook), cell_info

    async def _move_cell_websocket(
        self,
        notebook_manager: NotebookManager,
        source_index: int,
        target_index: int,
    ) -> tuple[Notebook, dict]:
        """Move cell using WebSocket connection (MCP_SERVER mode).

        Returns:
            Tuple of (notebook, moved_cell_info)
        """
        async with notebook_manager.get_current_connection() as notebook:
            self._validate_move(source_index, target_index, len(notebook))

            if source_index == target_index:
                cell_source = notebook.get_cell_source(source_index)
                nb_dict = notebook.as_dict()
                cell_type = nb_dict["cells"][source_index].get("cell_type", "code")
                return Notebook(**nb_dict), {"cell_type": cell_type, "source": cell_source}

            deleted = notebook.delete_cell(source_index)
            cell_type = deleted.get("cell_type", "code")
            cell_source = deleted.get("source", "")
            if isinstance(cell_source, list):
                cell_source = "".join(cell_source)
            notebook.insert_cell(target_index, cell_source, cell_type)
            return Notebook(**notebook.as_dict()), {"cell_type": cell_type, "source": cell_source}

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
        source_index: int = None,
        target_index: int = None,
        **kwargs,
    ) -> str:
        """Execute the move_cell tool.

        Supports three modes:
        1. JUPYTER_SERVER + YDoc: Collaborative real-time editing
        2. JUPYTER_SERVER + File: Direct nbformat file operations
        3. MCP_SERVER + WebSocket: Remote notebook via NbModelClient

        Returns:
            Success message with moved cell info and surrounding context.
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            from jupyter_mcp_server.jupyter_extension.context import get_server_context

            context = get_server_context()
            serverapp = context.serverapp
            notebook_path, _ = get_current_notebook_context(notebook_manager)

            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)

            if serverapp:
                nb, cell_info = await self._move_cell_ydoc(
                    serverapp, notebook_path, source_index, target_index
                )
            else:
                nb, cell_info = await self._move_cell_file(
                    notebook_path, source_index, target_index
                )

        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            nb, cell_info = await self._move_cell_websocket(
                notebook_manager, source_index, target_index
            )
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")

        info_list = [
            f"Cell moved successfully from index {source_index} to {target_index} "
            f"({cell_info['cell_type']})."
        ]
        info_list.append(f"Notebook has {len(nb)} cells, showing surrounding cells:")
        start_index = max(0, target_index - 3)
        info_list.append(nb.format_output(response_format="brief", start_index=start_index, limit=7))
        return "\n".join(info_list)
