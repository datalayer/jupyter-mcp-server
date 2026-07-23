# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Adapter exposing a code-sandboxes ``Sandbox`` as a ``KernelClient``.

The Jupyter MCP tools were originally written against
``jupyter_kernel_client.KernelClient``. To support additional execution engines
(Google Colab, Monty, Modal, Docker, ...) without rewriting every tool, this
module provides :class:`SandboxKernel`, a thin adapter that wraps a
``code_sandboxes.Sandbox`` and mimics the small subset of the ``KernelClient``
API used across the codebase:

* ``start()`` / ``stop()``
* ``execute(code, timeout=...)`` returning a Jupyter-style reply dict
* ``interrupt()`` / ``restart()`` / ``is_alive()``
* ``id`` property

Only ``execute`` requires translation: the sandbox returns a structured
``ExecutionResult`` which is converted back into the ``{"outputs": [...]}`` dict
shape that :func:`jupyter_mcp_server.utils.safe_extract_outputs` consumes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _execution_result_to_reply(result: Any) -> dict[str, Any]:
    """Convert a code-sandboxes ``ExecutionResult`` to a Jupyter reply dict.

    Args:
        result: The ``ExecutionResult`` returned by ``Sandbox.run_code``.

    Returns:
        A dict with ``execution_count``, ``status`` and ``outputs`` keys, where
        ``outputs`` follows the nbformat output schema.
    """
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


class SandboxKernel:
    """Expose a code-sandboxes ``Sandbox`` through the ``KernelClient`` API."""

    def __init__(self, sandbox: Any, logger: Optional[logging.Logger] = None) -> None:
        self._sandbox = sandbox
        self._log = logger or logging.getLogger(__name__)

    @property
    def sandbox(self) -> Any:
        """The wrapped code-sandboxes Sandbox instance."""
        return self._sandbox

    @property
    def id(self) -> Optional[str]:
        """The sandbox identifier (analogous to a kernel id)."""
        info = getattr(self._sandbox, "info", None)
        return info.id if info is not None else None

    def start(self, *args: Any, **kwargs: Any) -> None:
        """Start the underlying sandbox."""
        self._sandbox.start()

    def stop(self, shutdown_kernel: Optional[bool] = None, *args: Any, **kwargs: Any) -> None:
        """Stop the underlying sandbox.

        The ``shutdown_kernel`` argument is accepted for signature compatibility
        with ``KernelClient.stop`` and ignored: sandboxes manage their own
        lifecycle.
        """
        self._sandbox.stop()

    def is_alive(self, *args: Any, **kwargs: Any) -> bool:
        """Return whether the sandbox is currently started."""
        return bool(getattr(self._sandbox, "is_started", False))

    def interrupt(self, *args: Any, **kwargs: Any) -> bool:
        """Request interruption of the running code."""
        try:
            return bool(self._sandbox.interrupt())
        except Exception as exc:  # pragma: no cover - defensive
            self._log.debug("Sandbox interrupt failed: %s", exc)
            return False

    def restart(self, *args: Any, **kwargs: Any) -> None:
        """Restart the sandbox by stopping and starting it again."""
        try:
            self._sandbox.stop()
        finally:
            self._sandbox.start()

    def execute(self, code: str, timeout: Optional[float] = None, **kwargs: Any) -> dict[str, Any]:
        """Execute code and return a Jupyter-style reply dict."""
        result = self._sandbox.run_code(code, timeout=timeout)
        return _execution_result_to_reply(result)
