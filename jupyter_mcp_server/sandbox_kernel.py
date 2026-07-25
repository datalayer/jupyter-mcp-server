# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Adapter exposing a code-sandboxes ``Sandbox`` through the kernel interface.

The Jupyter MCP server historically drove a direct ``KernelClient``
implementation. To route all execution through
the ``code_sandboxes`` abstraction (``jupyter`` variant by default) without
rewriting every tool — and without any direct call to a legacy kernel client package
from this package — :class:`SandboxKernel` wraps a ``code_sandboxes.Sandbox``
and re-exposes the exact subset of the ``KernelClient`` API the server relies
on.

For the ``jupyter`` variant the sandbox owns a real ``KernelClient`` internally
(``sandbox.kernel_client``). The adapter delegates every execution and
introspection call to that client so behaviour — including streaming via
``execute_interactive`` used by the RTC ``execute_cell`` path — is identical to
the previous implementation. The sandbox is used only to construct and tear
down the client (and, for locally spawned variants, its server).
"""

from __future__ import annotations

import logging
from typing import Any

from jupyter_kernel_client import KernelClient


class SandboxKernel:
    """Expose a code-sandboxes ``Sandbox`` through the ``KernelClient`` API."""

    def __init__(self, sandbox: Any, logger: logging.Logger | None = None) -> None:
        self._sandbox = sandbox
        self._log = logger or logging.getLogger(__name__)

    @property
    def sandbox(self) -> Any:
        """The wrapped code-sandboxes ``Sandbox`` instance."""
        return self._sandbox

    @property
    def _client(self) -> KernelClient | None:
        """The underlying kernel client owned by the sandbox (may be ``None``).

        For the ``jupyter`` variant this is a real kernel client. Other
        variants may not expose
        one, in which case execution falls back to ``sandbox.run_code``.
        """
        return getattr(self._sandbox, "kernel_client", None)

    # -- lifecycle ---------------------------------------------------------

    def start(self, *args: Any, **kwargs: Any) -> None:
        """Start the underlying sandbox (which creates and starts the kernel)."""
        self._sandbox.start()

    def stop(self, shutdown_kernel: bool | None = None, *args: Any, **kwargs: Any) -> None:
        """Stop the underlying sandbox.

        ``shutdown_kernel`` mirrors ``KernelClient.stop``: a borrowed kernel
        (connected by id, not owned) is never shut down by the sandbox, so the
        argument only matters for owned kernels, which the sandbox tears down
        as part of ``stop()``.
        """
        self._sandbox.stop()

    def is_alive(self, *args: Any, **kwargs: Any) -> bool:
        """Return whether the kernel/sandbox is currently running."""
        client = self._client
        if client is not None and hasattr(client, "is_alive"):
            try:
                return bool(client.is_alive())
            except Exception as exc:  # pragma: no cover - defensive
                self._log.debug("Kernel is_alive check failed: %s", exc)
                return False
        return bool(getattr(self._sandbox, "is_started", False))

    def interrupt(self, *args: Any, **kwargs: Any) -> Any:
        """Interrupt the currently running code."""
        client = self._client
        if client is not None and hasattr(client, "interrupt"):
            return client.interrupt()
        try:
            return self._sandbox.interrupt()
        except Exception as exc:  # pragma: no cover - defensive
            self._log.debug("Sandbox interrupt failed: %s", exc)
            return False

    def restart(self, *args: Any, **kwargs: Any) -> Any:
        """Restart the kernel."""
        client = self._client
        if client is not None and hasattr(client, "restart"):
            return client.restart()
        # Fall back to a stop/start cycle of the whole sandbox.
        try:
            self._sandbox.stop()
        finally:
            self._sandbox.start()

    # -- identity ----------------------------------------------------------

    @property
    def id(self) -> str | None:
        """The kernel identifier (analogous to ``KernelClient.id``)."""
        client = self._client
        if client is not None and hasattr(client, "id"):
            return client.id
        info = getattr(self._sandbox, "info", None)
        return info.id if info is not None else None

    # -- execution ---------------------------------------------------------

    def execute(self, code: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Execute code and return a Jupyter-style reply dict.

        Delegates to the underlying kernel client so the returned dict has the
        exact ``{"execution_count", "outputs", "status"}`` shape the tools
        expect. Falls back to ``sandbox.run_code`` when no client is exposed.
        """
        client = self._client
        if client is not None and hasattr(client, "execute"):
            return client.execute(code, *args, **kwargs)
        result = self._sandbox.run_code(code, timeout=kwargs.get("timeout"))
        return _execution_result_to_reply(result)

    def execute_interactive(self, code: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Execute code with the low-level streaming API.

        This backs the RTC ``execute_cell`` path (real-time ``output_hook``
        streaming). It requires the underlying kernel client.
        """
        client = self._client
        if client is not None and hasattr(client, "execute_interactive"):
            return client.execute_interactive(code, *args, **kwargs)
        raise NotImplementedError(
            "The active sandbox does not expose a kernel client that supports "
            "streaming execution (execute_interactive)."
        )

    # -- variables ---------------------------------------------------------

    def get_variable(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Read a variable from the kernel."""
        client = self._client
        if client is not None and hasattr(client, "get_variable"):
            return client.get_variable(name, *args, **kwargs)
        return self._sandbox.get_variable(name)

    def set_variable(self, name: str, value: Any, *args: Any, **kwargs: Any) -> None:
        """Set a variable in the kernel."""
        client = self._client
        if client is not None and hasattr(client, "set_variable"):
            client.set_variable(name, value, *args, **kwargs)
            return
        self._sandbox.set_variable(name, value)


def _execution_result_to_reply(result: Any) -> dict[str, Any]:
    """Convert a code-sandboxes ``ExecutionResult`` to a Jupyter reply dict."""
    outputs: list[dict[str, Any]] = []

    logs = getattr(result, "logs", None)
    if logs is not None:
        stdout_lines = [msg.line for msg in getattr(logs, "stdout", [])]
        if stdout_lines:
            outputs.append(
                {
                    "output_type": "stream",
                    "name": "stdout",
                    "text": "\n".join(stdout_lines) + "\n",
                }
            )
        stderr_lines = [msg.line for msg in getattr(logs, "stderr", [])]
        if stderr_lines:
            outputs.append(
                {
                    "output_type": "stream",
                    "name": "stderr",
                    "text": "\n".join(stderr_lines) + "\n",
                }
            )

    for res in getattr(result, "results", []) or []:
        output_type = "execute_result" if getattr(res, "is_main_result", False) else "display_data"
        outputs.append(
            {
                "output_type": output_type,
                "data": getattr(res, "data", {}) or {},
                "metadata": getattr(res, "extra", {}) or {},
            }
        )

    code_error = getattr(result, "code_error", None)
    status = "ok"
    if code_error is not None:
        status = "error"
        traceback = getattr(code_error, "traceback", "") or ""
        outputs.append(
            {
                "output_type": "error",
                "ename": getattr(code_error, "name", "Error"),
                "evalue": getattr(code_error, "value", ""),
                "traceback": traceback.split("\n") if traceback else [],
            }
        )

    return {
        "execution_count": getattr(result, "execution_count", None),
        "status": status,
        "outputs": outputs,
    }


def create_jupyter_sandbox_kernel(
    *,
    server_url: str | None,
    token: str | None,
    kernel_id: str | None = None,
    path: str | None = None,
    timeout: float | None = None,
    reconnect_interval: int = 0,
    logger: logging.Logger | None = None,
) -> SandboxKernel:
    """Build a started ``SandboxKernel`` backed by the code-sandboxes jupyter variant.

    Connects to the Jupyter runtime at ``server_url`` and wraps it. When
    ``kernel_id`` is provided the sandbox connects to that specific kernel;
    otherwise a brand-new kernel is created (matching the previous
    ``KernelClient`` semantics used by ``create_kernel``).

    Args:
        server_url: Runtime (Jupyter server) URL.
        token: Runtime authentication token.
        kernel_id: Optional existing kernel id to connect to.
        path: Optional notebook path to associate with the kernel on start.
        timeout: Optional execution/startup timeout in seconds.
        reconnect_interval: Websocket auto-reconnect interval (0 disables).
        logger: Optional logger.

    Returns:
        A started :class:`SandboxKernel`.
    """
    from code_sandboxes import Sandbox

    client_kwargs: dict[str, Any] = {}
    if reconnect_interval:
        client_kwargs["reconnect_interval"] = reconnect_interval

    create_kwargs: dict[str, Any] = {
        "variant": "jupyter",
        "server_url": server_url,
        "token": token,
        "kernel_id": kernel_id,
        "kernel_path": path,
        # Preserve the original create_kernel semantics: no id means create a
        # new kernel rather than silently reusing an arbitrary existing one.
        "reuse_kernel": False,
    }
    if timeout is not None:
        create_kwargs["timeout"] = float(timeout)
    if client_kwargs:
        create_kwargs["client_kwargs"] = client_kwargs

    sandbox = Sandbox.create(**create_kwargs)
    kernel = SandboxKernel(sandbox, logger=logger)
    try:
        kernel.start()
    except Exception:
        try:
            sandbox.stop()
        except Exception:
            pass
        raise
    return kernel
