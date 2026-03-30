# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Edit cell source tool implementation — surgical find-and-replace within a cell."""

import difflib
import nbformat
from pathlib import Path
from typing import Any, Optional
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, get_notebook_model, clean_notebook_outputs


class EditCellSourceTool(BaseTool):
    """Tool to perform surgical string find-and-replace within a cell's source."""

    @staticmethod
    def _validate_edit(source: str, old_string: str, new_string: str, replace_all: bool) -> None:
        """Validate edit parameters before applying.

        Raises:
            ValueError: If old_string is empty, not found, or ambiguous (multiple
                matches without replace_all).
        """
        if not old_string:
            raise ValueError("old_string must not be empty")

        count = source.count(old_string)
        if count == 0:
            raise ValueError(f"old_string not found in cell source")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_string is not unique in cell source ({count} occurrences). "
                "Use replace_all=True to replace all occurrences."
            )

    @staticmethod
    def _apply_edit(source: str, old_string: str, new_string: str, replace_all: bool) -> str:
        """Apply the string replacement and return the new source.

        Assumes _validate_edit has already been called.
        """
        if replace_all:
            return source.replace(old_string, new_string)
        return source.replace(old_string, new_string, 1)

    def _generate_diff(self, old_source: str, new_source: str) -> str:
        """Generate unified diff between old and new source."""
        old_lines = old_source.splitlines(keepends=False)
        new_lines = new_source.splitlines(keepends=False)

        diff_lines = list[str](difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
            n=3,
        ))

        if len(diff_lines) > 3:
            return '\n'.join(diff_lines)
        return "no changes detected"

    def _edit_source(self, old_source: str, old_string: str, new_string: str, replace_all: bool) -> tuple[str, str]:
        """Validate, apply the edit, and return (new_source, diff).

        Raises ValueError on validation failure.
        """
        self._validate_edit(old_source, old_string, new_string, replace_all)
        new_source = self._apply_edit(old_source, old_string, new_string, replace_all)
        diff = self._generate_diff(old_source, new_source)
        return new_source, diff

    # ----- mode-specific writers -----

    async def _edit_cell_ydoc(
        self, serverapp: Any, notebook_path: str,
        cell_index: int, old_string: str, new_string: str, replace_all: bool,
    ) -> str:
        nb = await get_notebook_model(serverapp, notebook_path)

        if nb:
            if cell_index >= len(nb):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(nb)} cells."
                )

            old_source = nb.get_cell_source(cell_index)
            if isinstance(old_source, list):
                old_source = "".join(old_source)
            else:
                old_source = str(old_source)

            new_source, diff = self._edit_source(old_source, old_string, new_string, replace_all)
            nb.set_cell_source(cell_index, new_source)
            return diff
        else:
            return await self._edit_cell_file(
                notebook_path, cell_index, old_string, new_string, replace_all,
            )

    async def _edit_cell_file(
        self, notebook_path: str, cell_index: int,
        old_string: str, new_string: str, replace_all: bool,
    ) -> str:
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)
        clean_notebook_outputs(notebook)

        if cell_index >= len(notebook.cells):
            raise ValueError(
                f"Cell index {cell_index} is out of range. Notebook has {len(notebook.cells)} cells."
            )

        old_source = notebook.cells[cell_index].source
        new_source, diff = self._edit_source(old_source, old_string, new_string, replace_all)
        notebook.cells[cell_index].source = new_source

        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)

        return diff

    async def _edit_cell_websocket(
        self, notebook_manager: NotebookManager, cell_index: int,
        old_string: str, new_string: str, replace_all: bool,
    ) -> str:
        async with notebook_manager.get_current_connection() as notebook:
            if cell_index >= len(notebook):
                raise ValueError(f"Cell index {cell_index} out of range")

            old_source = notebook.get_cell_source(cell_index)
            if isinstance(old_source, list):
                old_source = "".join(old_source)
            else:
                old_source = str(old_source)

            new_source, diff = self._edit_source(old_source, old_string, new_string, replace_all)
            notebook.set_cell_source(cell_index, new_source)
            return diff

    # ----- main entry point -----

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
        old_string: str = None,
        new_string: str = None,
        replace_all: bool = False,
        **kwargs,
    ) -> str:
        """Execute the edit_cell_source tool.

        Performs a surgical find-and-replace within a single cell's source,
        delegating the actual write to the appropriate backend (YDoc, file, or
        WebSocket) depending on the server mode.
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
                diff = await self._edit_cell_ydoc(
                    serverapp, notebook_path, cell_index,
                    old_string, new_string, replace_all,
                )
            else:
                diff = await self._edit_cell_file(
                    notebook_path, cell_index,
                    old_string, new_string, replace_all,
                )

        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            diff = await self._edit_cell_websocket(
                notebook_manager, cell_index,
                old_string, new_string, replace_all,
            )
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")

        if not diff.strip() or diff == "no changes detected":
            return f"Cell {cell_index} edited successfully - no changes detected"
        else:
            return f"Cell {cell_index} edited successfully!\n\n```diff\n{diff}\n```"
