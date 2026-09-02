# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Lifecycle manager for code-sandboxes code sandboxes used by MCP tools.

This manager is intentionally independent from notebook/kernel management so that
agents can run code through sandbox backends as an alternative to Jupyter
kernels.
"""

from __future__ import annotations

from typing import Any

from code_sandboxes import CodeSandboxClient, normalize_variant
from jupyter_mcp_server.config import JUPYTER_SERVER_VARIANT
from jupyter_mcp_server.utils import safe_extract_outputs


class CodeSandboxManager:
    """Track launched sandboxes and optional active sandbox selection."""

    def __init__(self):
        self._sandboxes: dict[str, CodeSandboxClient] = {}
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
        channels_url: str | None = None,
        token: str | None = None,
        run_url: str | None = None,
        python_version: str | None = None,
        snapshot_name: str | None = None,
    ) -> dict[str, Any]:
        """Launch and register a new code sandbox."""
        if sandbox_name in self._sandboxes:
            raise ValueError(f"Sandbox '{sandbox_name}' already exists.")

        # Read the way `code_sandboxes` reads it, so that a caller naming a
        # variant with an underscore or in capitals lands on the same branch
        # below as one naming it canonically.
        variant = normalize_variant(variant)
        create_kwargs: dict[str, Any] = {
            "variant": variant,
            "timeout": timeout,
            # The name the caller gave this sandbox, so the platform records
            # it too. Without it a sandbox is `welcome-sbx` here and
            # `sandbox-d786c04d` in the runtimes table, and nothing connects
            # the two — the same object appearing to be two.
            "name": sandbox_name,
        }
        if environment:
            create_kwargs["environment"] = environment
        if gpu:
            create_kwargs["gpu"] = gpu
        if python_version and variant == "modal":
            create_kwargs["python_version"] = python_version

        if variant == "google-colab":
            if server_url:
                create_kwargs["server_url"] = server_url
            if kernel_id:
                create_kwargs["kernel_id"] = kernel_id
            if proxy_token:
                create_kwargs["proxy_token"] = proxy_token
            if channels_url:
                create_kwargs["channels_url"] = channels_url

        if variant == "kaggle":
            if server_url:
                create_kwargs["server_url"] = server_url
            if kernel_id:
                create_kwargs["kernel_id"] = kernel_id
            if channels_url:
                create_kwargs["channels_url"] = channels_url
            if token:
                create_kwargs["token"] = token

        if variant == JUPYTER_SERVER_VARIANT:
            if server_url:
                create_kwargs["server_url"] = server_url
            if kernel_id:
                create_kwargs["kernel_id"] = kernel_id
            if token:
                create_kwargs["token"] = token
            # Align with core behavior: creating through extension tools should
            # not silently reuse arbitrary existing kernels.
            create_kwargs["reuse_kernel"] = False

        if variant == "datalayer":
            if token:
                create_kwargs["token"] = token
            if run_url:
                create_kwargs["run_url"] = run_url
            # Start from a saved state rather than an empty one. Named per
            # variant rather than passed for all of them because a variant
            # that does not know the argument would take it as an unexpected
            # keyword and fail the launch — a caller who asked for a snapshot
            # on a backend without them should be told that, not handed a
            # TypeError from a constructor.
            if snapshot_name:
                create_kwargs["snapshot_name"] = snapshot_name

        if snapshot_name and variant != "datalayer":
            raise ValueError(
                f"Sandbox variant '{variant}' cannot start from a snapshot; "
                "only 'datalayer' can."
            )

        sandbox = CodeSandboxClient.create(**create_kwargs)
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

    def get_active(self):
        """The active sandbox's client, or ``None`` when none is selected."""
        if not self._active_name:
            return None
        return self._sandboxes.get(self._active_name)

    def execute_on_active(self, code: str, timeout: int) -> list[str | Any]:
        """Execute code on the active sandbox and return display-ready outputs."""
        if not self._active_name or self._active_name not in self._sandboxes:
            raise ValueError("No active sandbox selected.")

        sandbox = self._sandboxes[self._active_name]

        # Prefer streaming when available to surface provider progress updates
        # (for example Kaggle batch status transitions).
        outputs: list[dict[str, Any]] = []
        for event in sandbox.execute_code_streaming(code, timeout=timeout):
            if hasattr(event, "line"):
                outputs.append(
                    {
                        "output_type": "stream",
                        "name": "stderr" if bool(getattr(event, "error", False)) else "stdout",
                        "text": f"{getattr(event, 'line', '')}\n",
                    }
                )
            elif hasattr(event, "data"):
                outputs.append(
                    {
                        "output_type": "execute_result"
                        if bool(getattr(event, "is_main_result", False))
                        else "display_data",
                        "data": getattr(event, "data", {}) or {},
                        "metadata": getattr(event, "extra", {}) or {},
                    }
                )
            elif hasattr(event, "name") and hasattr(event, "value"):
                traceback = (getattr(event, "traceback", "") or "").split("\n")
                if traceback == [""]:
                    traceback = []
                outputs.append(
                    {
                        "output_type": "error",
                        "ename": getattr(event, "name", "Error"),
                        "evalue": getattr(event, "value", ""),
                        "traceback": traceback,
                    }
                )

        if outputs:
            return safe_extract_outputs(outputs)

        reply = sandbox.execute(code, timeout=timeout)
        return safe_extract_outputs(reply.get("outputs", []))

    def _serialize(self, name: str, sandbox: CodeSandboxClient) -> dict[str, Any]:
        info = sandbox.info
        config = sandbox.config
        return {
            "name": name,
            "active": name == self._active_name,
            "sandbox_id": sandbox.id,
            "variant": getattr(info, "variant", None),
            "status": getattr(info, "status", None),
            "environment": getattr(config, "environment", None) if config else None,
            "gpu": getattr(config, "gpu", None) if config else None,
        }
