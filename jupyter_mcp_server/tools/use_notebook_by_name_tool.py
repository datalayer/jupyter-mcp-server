# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Use notebook by name tool implementation."""

from typing import Any

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import append_notebook_preview_and_open_ui


class UseNotebookByNameTool(BaseTool):
    """Tool to activate an already-connected notebook by its registered name."""

    async def execute(
        self,
        mode: ServerMode,
        sandbox_server_client: Any | None = None,
        contents_manager: Any | None = None,
        kernel_manager: Any | None = None,
        kernel_spec_manager: Any | None = None,
        notebook_manager: NotebookManager | None = None,
        notebook_name: str | None = None,
        code_sandbox_url: str | None = None,
        code_sandbox_token: str | None = None,
        auth_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Switch the active notebook pointer to an already-registered notebook.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Identifier of the already-connected notebook
            code_sandbox_url: Code sandbox URL for HTTP mode
            code_sandbox_token: Code sandbox token for HTTP mode
            auth_headers: Optional HTTP auth headers
            **kwargs: Additional parameters

        Returns:
            Status and brief preview of the activated notebook, or a refusal message.
        """
        if notebook_manager is None or not notebook_name or notebook_name not in notebook_manager:
            connected = (
                list(notebook_manager.list_all_notebooks().keys())
                if notebook_manager is not None
                else []
            )
            return (
                f"Notebook '{notebook_name}' is not connected. "
                f"All currently connected notebooks: {connected}. "
                "Use 'use_notebook' with a notebook_path first to connect a notebook."
            )

        if notebook_name == notebook_manager.get_current_notebook():
            bound = notebook_manager.get_code_sandbox_id(notebook_name)
            state = (
                f"It runs on execution backend '{bound}'."
                if bound
                else "No execution backend is attached yet; the first execution attaches one"
                " (the active sandbox, if one is selected with 'use_sandbox')."
            )
            return (
                f"Notebook '{notebook_name}' is already active - no need to"
                f" call use_notebook_by_name again. {state}"
            )

        previous = notebook_manager.get_current_notebook()
        notebook_path = notebook_manager.get_notebook_path(notebook_name)
        info_list: list[str] = []
        if previous:
            info_list.append(
                f"[INFO] Reactivating notebook '{notebook_name}' and deactivating '{previous}'."
            )
        else:
            info_list.append(f"[INFO] Successfully activate notebook '{notebook_name}'.")

        notebook_manager.set_current_notebook(notebook_name)

        await HookRegistry.get_instance().fire(
            HookEvent.KERNEL_LIFECYCLE,
            event_type="started",
            kernel_id=notebook_manager.get_code_sandbox_id(notebook_name) or "unknown",
            kernel_name=notebook_name,
        )

        await append_notebook_preview_and_open_ui(
            mode=mode,
            info_list=info_list,
            notebook_path=notebook_path,
            contents_manager=contents_manager,
            notebook_manager=notebook_manager,
            code_sandbox_url=code_sandbox_url,
            code_sandbox_token=code_sandbox_token,
            auth_headers=auth_headers,
        )
        return "\n".join(info_list)
