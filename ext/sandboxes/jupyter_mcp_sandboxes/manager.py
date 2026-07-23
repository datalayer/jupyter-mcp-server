# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Lifecycle manager for code-sandboxes runtimes used by MCP tools.

This manager is intentionally independent from notebook/kernel management so that
agents can run code through sandbox backends as an alternative to Jupyter
kernels.
"""

from __future__ import annotations

from typing import Any

from jupyter_mcp_server.utils import safe_extract_outputs

from jupyter_mcp_sandboxes.kernel import _execution_result_to_reply


class SandboxRuntimeManager:
    """Track launched sandboxes and optional active sandbox selection."""

    def __init__(self):
        self._sandboxes: dict[str, Any] = {}
        self._active_name: str | None = None

    def launch(
        self,
        *,
        sandbox_name: str,
        variant: str,
        timeout: float,
        environment: str | None = None,
        gpu: str | None = None,
        server_url: str | None = None,
        kernel_id: str | None = None,
        proxy_token: str | None = None,
        use_browser_bridge: bool = False,
        token: str | None = None,
        run_url: str | None = None,
        python_version: str | None = None,
    ) -> dict[str, Any]:
        """Launch and register a new sandbox runtime."""
        if sandbox_name in self._sandboxes:
            raise ValueError(f"Sandbox '{sandbox_name}' already exists.")

        from code_sandboxes import Sandbox

        create_kwargs: dict[str, Any] = {
            "variant": variant,
            "timeout": timeout,
        }
        if environment:
            create_kwargs["environment"] = environment
        if gpu:
            create_kwargs["gpu"] = gpu
        if python_version and variant == "modal":
            create_kwargs["python_version"] = python_version

        if variant == "colab":
            if server_url:
                create_kwargs["server_url"] = server_url
            if kernel_id:
                create_kwargs["kernel_id"] = kernel_id
            if proxy_token:
                create_kwargs["proxy_token"] = proxy_token
            if use_browser_bridge:
                create_kwargs["use_browser_bridge"] = True

        if variant == "datalayer":
            if token:
                create_kwargs["token"] = token
            if run_url:
                create_kwargs["run_url"] = run_url

        sandbox = Sandbox.create(**create_kwargs)
        sandbox.start()

        self._sandboxes[sandbox_name] = sandbox
        if self._active_name is None:
            self._active_name = sandbox_name

        return self._serialize(sandbox_name, sandbox)

    def list(self) -> list[dict[str, Any]]:
        """Return all known sandboxes with summary metadata."""
        return [
            self._serialize(name, sandbox)
            for name, sandbox in sorted(self._sandboxes.items(), key=lambda item: item[0])
        ]

    def terminate(self, sandbox_name: str) -> bool:
        """Terminate and unregister a sandbox."""
        sandbox = self._sandboxes.pop(sandbox_name, None)
        if sandbox is None:
            return False

        try:
            sandbox.stop()
        finally:
            if self._active_name == sandbox_name:
                self._active_name = next(iter(self._sandboxes.keys()), None)
        return True

    def terminate_all(self) -> None:
        """Terminate every tracked sandbox."""
        names = list(self._sandboxes.keys())
        for name in names:
            self.terminate(name)

    def use(self, sandbox_name: str | None) -> str | None:
        """Set active sandbox name. Passing None disables sandbox routing."""
        if sandbox_name is None or sandbox_name == "":
            self._active_name = None
            return None
        if sandbox_name not in self._sandboxes:
            raise ValueError(f"Sandbox '{sandbox_name}' not found.")
        self._active_name = sandbox_name
        return sandbox_name

    def get_active_name(self) -> str | None:
        return self._active_name

    def execute_on_active(self, code: str, timeout: int) -> list[str | Any]:
        """Execute code on the active sandbox and return display-ready outputs."""
        if not self._active_name or self._active_name not in self._sandboxes:
            raise ValueError("No active sandbox selected.")

        sandbox = self._sandboxes[self._active_name]
        result = sandbox.run_code(code, timeout=timeout)
        reply = _execution_result_to_reply(result)
        return safe_extract_outputs(reply.get("outputs", []))

    def _serialize(self, name: str, sandbox: Any) -> dict[str, Any]:
        info = getattr(sandbox, "info", None)
        config = getattr(sandbox, "config", None)
        return {
            "name": name,
            "active": name == self._active_name,
            "sandbox_id": getattr(sandbox, "sandbox_id", None),
            "variant": getattr(info, "variant", None),
            "status": getattr(info, "status", None),
            "environment": getattr(config, "environment", None) if config else None,
            "gpu": getattr(config, "gpu", None) if config else None,
        }
