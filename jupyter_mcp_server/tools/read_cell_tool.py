# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Read cell tool implementation."""

from typing import Any, Optional, Dict, Union, List
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import CellInfo
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import get_jupyter_ydoc
from mcp.types import ImageContent


class ReadCellTool(BaseTool):
    """Tool to read a specific cell from a notebook."""

    async def _read_cell_local(self, serverapp: Any, contents_manager: Any, path: str, cell_index: int) -> Dict[str, Any]:
        """Read a specific cell using local contents_manager (JUPYTER_SERVER mode).

        First tries to read from YDoc (RTC mode) if notebook is open, otherwise falls back to file mode.
        """
        # Get file_id for YDoc lookup
        file_id_manager = serverapp.web_app.settings.get("file_id_manager")
        file_id = file_id_manager.get_id(path) if file_id_manager else None
        if file_id is None and file_id_manager:
            file_id = file_id_manager.index(path)

        # Try to get YDoc if notebook is open (RTC mode)
        if file_id:
            ydoc = await get_jupyter_ydoc(serverapp, file_id)
            if ydoc:
                # Notebook is open - read from YDoc (live data)
                cells = ydoc.ycells

                # Handle negative indices
                if cell_index < 0:
                    cell_index = len(cells) + cell_index

                if cell_index < 0 or cell_index >= len(cells):
                    raise ValueError(
                        f"Cell index {cell_index} is out of range. Notebook has {len(cells)} cells."
                    )

                cell = cells[cell_index]
                cell_info = CellInfo.from_cell(cell_index=cell_index, cell=cell)
                return cell_info.model_dump(exclude_none=True)

        # Fall back to file mode if notebook not open
        model = await contents_manager.get(path, content=True, type='notebook')

        if 'content' not in model:
            raise ValueError(f"Could not read notebook content from {path}")

        notebook_content = model['content']
        cells = notebook_content.get('cells', [])

        # Handle negative indices
        if cell_index < 0:
            cell_index = len(cells) + cell_index

        if cell_index < 0 or cell_index >= len(cells):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(cells)} cells."
            )

        cell = cells[cell_index]

        # Use CellInfo.from_cell to normalize the structure (ensures "type" field not "cell_type")
        cell_info = CellInfo.from_cell(cell_index=cell_index, cell=cell)

        return cell_info.model_dump(exclude_none=True)
    
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
    ) -> Dict[str, Union[str, int, List[Union[str, ImageContent]]]]:
        """Execute the read_cell tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to read (0-based)
            **kwargs: Additional parameters
            
        Returns:
            Cell information dictionary
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Use local contents_manager to read the notebook
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            from pathlib import Path
            
            context = get_server_context()
            serverapp = context.serverapp
            
            notebook_path = None
            if notebook_manager:
                notebook_path = notebook_manager.get_current_notebook_path()
            if not notebook_path:
                config = get_config()
                notebook_path = config.document_id
            
            # contents_manager expects path relative to serverapp.root_dir
            # If we have an absolute path, convert it to relative
            if serverapp and Path(notebook_path).is_absolute():
                root_dir = Path(serverapp.root_dir)
                abs_path = Path(notebook_path)
                try:
                    notebook_path = str(abs_path.relative_to(root_dir))
                except ValueError:
                    # Path is not under root_dir, use as-is
                    pass
            
            return await self._read_cell_local(serverapp, contents_manager, notebook_path, cell_index)
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_current_connection() as notebook:
                if cell_index < 0 or cell_index >= len(notebook):
                    raise ValueError(f"Cell index {cell_index} out of range")

                cell = notebook[cell_index]
                return CellInfo.from_cell(cell_index=cell_index, cell=cell).model_dump(exclude_none=True)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
