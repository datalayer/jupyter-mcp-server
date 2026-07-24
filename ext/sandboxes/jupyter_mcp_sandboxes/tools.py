# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Sandbox lifecycle tools.

These tools are designed to be used as an alternative to notebook/kernel-based
execution by launching and selecting code-sandboxes runtimes explicitly.
"""

from __future__ import annotations

from typing import Any

from jupyter_mcp_server.tools._base import BaseTool, ServerMode


class LaunchSandboxTool(BaseTool):
    """Launch a sandbox runtime and register it for later use."""

    async def execute(
        self,
        mode: ServerMode,
        sandbox_runtime_manager=None,
        sandbox_name: str | None = None,
        variant: str = "eval",
        timeout: int = 60,
        environment: str | None = None,
        gpu: str | None = None,
        server_url: str | None = None,
        kernel_id: str | None = None,
        proxy_token: str | None = None,
        channels_url: str | None = None,
        use_browser_bridge: bool = False,
        token: str | None = None,
        run_url: str | None = None,
        python_version: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        if sandbox_runtime_manager is None:
            raise ValueError("sandbox_runtime_manager is required")
        if not sandbox_name:
            raise ValueError("sandbox_name is required")

        sandbox_info = sandbox_runtime_manager.launch(
            sandbox_name=sandbox_name,
            variant=variant,
            timeout=float(timeout),
            environment=environment,
            gpu=gpu,
            server_url=server_url,
            kernel_id=kernel_id,
            proxy_token=proxy_token,
            channels_url=channels_url,
            use_browser_bridge=use_browser_bridge,
            token=token,
            run_url=run_url,
            python_version=python_version,
        )

        return {
            "message": (
                "Sandbox launched successfully. Use 'use_sandbox' to route 'execute_code' "
                "to this sandbox instead of a Jupyter kernel."
            ),
            "sandbox": sandbox_info,
        }


class ListSandboxesTool(BaseTool):
    """List all launched sandboxes."""

    async def execute(self, mode: ServerMode, sandbox_runtime_manager=None, **kwargs) -> list[dict[str, Any]]:
        if sandbox_runtime_manager is None:
            raise ValueError("sandbox_runtime_manager is required")
        return sandbox_runtime_manager.list()


class TerminateSandboxTool(BaseTool):
    """Terminate one launched sandbox."""

    async def execute(
        self,
        mode: ServerMode,
        sandbox_runtime_manager=None,
        sandbox_name: str | None = None,
        **kwargs,
    ) -> str:
        if sandbox_runtime_manager is None:
            raise ValueError("sandbox_runtime_manager is required")
        if not sandbox_name:
            raise ValueError("sandbox_name is required")

        if sandbox_runtime_manager.terminate(sandbox_name):
            return f"Sandbox '{sandbox_name}' terminated."
        return f"Sandbox '{sandbox_name}' not found."


class UseSandboxTool(BaseTool):
    """Select or clear the active sandbox used by execute_code."""

    async def execute(
        self,
        mode: ServerMode,
        sandbox_runtime_manager=None,
        sandbox_name: str | None = None,
        **kwargs,
    ) -> str:
        if sandbox_runtime_manager is None:
            raise ValueError("sandbox_runtime_manager is required")

        active_name = sandbox_runtime_manager.use(sandbox_name)
        if active_name is None:
            return (
                "Sandbox routing disabled. 'execute_code' now uses Jupyter kernels again "
                "based on the active notebook/kernel context."
            )
        return (
            f"Sandbox '{active_name}' is now active. 'execute_code' will run on this sandbox "
            "instead of a Jupyter kernel until you switch or clear it."
        )
