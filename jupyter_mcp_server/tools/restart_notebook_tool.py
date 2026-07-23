# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Restart notebook tool implementation."""

import logging
from typing import Any

from jupyter_server_client import JupyterServerClient

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import BaseTool, ServerMode

logger = logging.getLogger(__name__)


class RestartNotebookTool(BaseTool):
    """Tool to restart the kernel for a specific notebook."""

    async def _reprovision_kernel(
        self,
        kernel_manager: Any,
        notebook_manager: NotebookManager,
        notebook_name: str,
    ) -> str:
        """Start a fresh kernel and rebind it to the notebook (JUPYTER_SERVER mode).

        Used when the notebook's recorded kernel has been culled or lost, so the
        agent can self-heal instead of being stuck with a dead kernel binding.
        """
        try:
            notebook_path = notebook_manager.get_notebook_path(notebook_name)
            new_kernel_id = await kernel_manager.start_kernel(path=notebook_path)
            notebook_manager.add_notebook(
                notebook_name,
                {"id": new_kernel_id},
                server_url="local",
                token=None,
                path=notebook_path,
            )
            logger.info(f"Provisioned fresh kernel {new_kernel_id} for notebook '{notebook_name}'")
            return (
                f"Notebook '{notebook_name}' kernel was no longer available and has been "
                f"reprovisioned (new kernel '{new_kernel_id}'). Memory state and imported "
                f"packages have been cleared."
            )
        except Exception as e:
            logger.error(f"Failed to reprovision kernel for notebook '{notebook_name}': {e}")
            return (
                f"Failed to restart notebook '{notebook_name}': the kernel was no longer "
                f"available and reprovisioning failed: {e}"
            )

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
        notebook_name: str = None,
        **kwargs,
    ) -> str:
        """Execute the restart_notebook tool.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to restart
            **kwargs: Additional parameters

        Returns:
            Success message
        """
        if notebook_name not in notebook_manager:
            return f"Notebook '{notebook_name}' is not connected. All currently connected notebooks: {list(notebook_manager.list_all_notebooks().keys())}"

        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use kernel_manager to restart the kernel
            if kernel_manager is None:
                return f"Failed to restart notebook '{notebook_name}': kernel_manager is required in JUPYTER_SERVER mode."

            # Get kernel ID from notebook_manager
            kernel_id = notebook_manager.get_kernel_id(notebook_name)
            if not kernel_id:
                return f"Failed to restart notebook '{notebook_name}': kernel ID not found."

            # Self-heal a stale binding: if the recorded kernel no longer exists
            # (idle-culled on JupyterHub, or the single-user server was restarted),
            # provision a fresh kernel and rebind it instead of failing on a 404.
            if kernel_id not in kernel_manager:
                logger.info(
                    f"Kernel {kernel_id} for notebook '{notebook_name}' no longer exists; "
                    f"provisioning a fresh kernel."
                )
                return await self._reprovision_kernel(
                    kernel_manager, notebook_manager, notebook_name
                )

            try:
                logger.info(
                    f"Restarting kernel {kernel_id} for notebook '{notebook_name}' in JUPYTER_SERVER mode"
                )
                await kernel_manager.restart_kernel(kernel_id)
                return f"Notebook '{notebook_name}' kernel restarted successfully. Memory state and imported packages have been cleared."
            except Exception as e:
                # The kernel may have been culled between the liveness check and the
                # restart call; treat a now-missing kernel as a reprovision, not a failure.
                if kernel_id not in kernel_manager:
                    logger.info(
                        f"Kernel {kernel_id} for notebook '{notebook_name}' disappeared during "
                        f"restart; provisioning a fresh kernel."
                    )
                    return await self._reprovision_kernel(
                        kernel_manager, notebook_manager, notebook_name
                    )
                logger.error(f"Failed to restart kernel {kernel_id}: {e}")
                return f"Failed to restart notebook '{notebook_name}': {e}"

        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use notebook_manager's restart_notebook method
            success = notebook_manager.restart_notebook(notebook_name)

            if success:
                return f"Notebook '{notebook_name}' kernel restarted successfully. Memory state and imported packages have been cleared."
            else:
                return f"Failed to restart notebook '{notebook_name}'. The kernel may not support restart operation."
        else:
            return f"Invalid mode: {mode}"
