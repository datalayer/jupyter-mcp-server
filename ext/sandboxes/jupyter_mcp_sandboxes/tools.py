# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Sandbox lifecycle tools.

These tools are designed to be used as an alternative to notebook/kernel-based
execution by launching and selecting code-sandboxes code sandboxes explicitly.
"""

from __future__ import annotations

from typing import Any

from jupyter_mcp_server.tools._base import BaseTool, ServerMode


class LaunchSandboxTool(BaseTool):
    """Launch a code sandbox and register it for later use."""

    async def execute(
        self,
        mode: ServerMode,
        code_sandbox_manager=None,
        sandbox_name: str | None = None,
        variant: str = "eval",
        timeout: int = 60,
        environment: str | None = None,
        gpu: str | None = None,
        server_url: str | None = None,
        kernel_id: str | None = None,
        proxy_token: str | None = None,
        channels_url: str | None = None,
        token: str | None = None,
        run_url: str | None = None,
        python_version: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        if code_sandbox_manager is None:
            raise ValueError("code_sandbox_manager is required")
        if not sandbox_name:
            raise ValueError("sandbox_name is required")

        sandbox_info = code_sandbox_manager.launch(
            sandbox_name=sandbox_name,
            variant=variant,
            timeout=float(timeout),
            environment=environment,
            gpu=gpu,
            server_url=server_url,
            kernel_id=kernel_id,
            proxy_token=proxy_token,
            channels_url=channels_url,
            token=token,
            run_url=run_url,
            python_version=python_version,
        )

        return {
            "message": (
                "Sandbox launched. Select it with 'use_sandbox': 'execute_code' then runs"
                " on it, and the first 'execute_cell' on a notebook without a backend"
                " attaches it to that notebook — no kernel_id juggling needed."
            ),
            "sandbox": sandbox_info,
        }


class ListSandboxesTool(BaseTool):
    """List all launched sandboxes."""

    async def execute(self, mode: ServerMode, code_sandbox_manager=None, **kwargs) -> list[dict[str, Any]]:
        if code_sandbox_manager is None:
            raise ValueError("code_sandbox_manager is required")
        sandboxes = code_sandbox_manager.list()
        _annotate_attached_notebooks(sandboxes, code_sandbox_manager)
        return sandboxes


def _annotate_attached_notebooks(sandboxes: list[dict[str, Any]], manager) -> None:
    """Add which notebooks run on each sandbox, so the answer is checkable.

    Attachment happens implicitly — the first execution on a notebook binds
    the active sandbox — and a fact established implicitly must be readable
    somewhere, or callers re-derive it by experiment: agents have detached and
    reconnected notebooks purely to find out where their cells run.

    The binding is object identity: the notebook manager holds the very client
    the sandbox manager launched. Imported late because the notebook manager
    lives in the server module, which loads extensions — at call time the
    cycle is long since closed.
    """
    try:
        from jupyter_mcp_server.server import notebook_manager

        by_client = {id(manager._sandboxes[s["name"]]): s for s in sandboxes if s.get("name") in manager._sandboxes}
        for name, _info in notebook_manager:
            client = notebook_manager.get_code_sandbox(name)
            entry = by_client.get(id(client))
            if entry is not None:
                entry.setdefault("attached_notebooks", []).append(name)
    except Exception:  # noqa: BLE001 - the listing is worth more than the extras
        return
    for sandbox in sandboxes:
        sandbox.setdefault("attached_notebooks", [])


class TerminateSandboxTool(BaseTool):
    """Terminate one launched sandbox."""

    async def execute(
        self,
        mode: ServerMode,
        code_sandbox_manager=None,
        sandbox_name: str | None = None,
        **kwargs,
    ) -> str:
        if code_sandbox_manager is None:
            raise ValueError("code_sandbox_manager is required")
        if not sandbox_name:
            raise ValueError("sandbox_name is required")

        if code_sandbox_manager.terminate(sandbox_name):
            return f"Sandbox '{sandbox_name}' terminated."
        return f"Sandbox '{sandbox_name}' not found."


class UseSandboxTool(BaseTool):
    """Select or clear the active sandbox used by execute_code."""

    async def execute(
        self,
        mode: ServerMode,
        code_sandbox_manager=None,
        sandbox_name: str | None = None,
        **kwargs,
    ) -> str:
        if code_sandbox_manager is None:
            raise ValueError("code_sandbox_manager is required")

        active_name = code_sandbox_manager.use(sandbox_name)
        if active_name is None:
            return (
                "Sandbox routing disabled. 'execute_code' now uses Jupyter kernels again "
                "based on the active notebook/kernel context."
            )
        return (
            f"Sandbox '{active_name}' is now active. 'execute_code' runs on it, and the"
            " first 'execute_cell' on a notebook without a backend attaches it to that"
            " notebook — outputs are written into the notebook as usual. Switch or clear"
            " with 'use_sandbox' again."
        )
