# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Helpers for creating jupyter sandbox-backed kernel clients.

This module intentionally returns the plain kernel client exposed by the
``code_sandboxes`` jupyter variant (``sandbox.kernel_client``) rather than an
adapter class.
"""

from __future__ import annotations

import logging
from types import MethodType
from typing import Any

from code_sandboxes.interfaces import ISandboxClient


def _attach_sandbox_stop(client: ISandboxClient, sandbox: Any, log: logging.Logger) -> None:
    """Ensure ``client.stop()`` also releases the backing sandbox.

    When callers pass ``shutdown_kernel=False`` (borrowed-kernel flow), keep the
    original client stop semantics and skip sandbox-level shutdown.
    """
    original_stop = getattr(client, "stop", None)
    if not callable(original_stop):
        return

    if getattr(client, "_mcp_sandbox_stop_wrapped", False):
        return

    def _stop_with_sandbox(self, *args: Any, **kwargs: Any):
        shutdown_kernel = kwargs.get("shutdown_kernel", None)
        if shutdown_kernel is None and args:
            shutdown_kernel = args[0]

        if shutdown_kernel is False:
            return original_stop(*args, **kwargs)

        previous_stop = getattr(self, "stop", None)
        try:
            setattr(self, "stop", original_stop)
            return sandbox.stop()
        except Exception:
            log.debug("Error stopping sandbox from wrapped client.stop", exc_info=True)
            if callable(previous_stop):
                return original_stop(*args, **kwargs)
            raise
        finally:
            setattr(self, "stop", MethodType(_stop_with_sandbox, self))

    setattr(client, "stop", MethodType(_stop_with_sandbox, client))
    setattr(client, "_mcp_sandbox_stop_wrapped", True)


def create_jupyter_sandbox_client(
    *,
    server_url: str | None,
    token: str | None,
    kernel_id: str | None = None,
    path: str | None = None,
    timeout: float | None = None,
    reconnect_interval: int = 0,
    headers: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> ISandboxClient:
    """Build and start a jupyter sandbox, then return its plain kernel client.

    When ``kernel_id`` is provided, the client connects to that specific
    existing kernel; otherwise a new kernel is created.

    ``headers`` carries extra HTTP headers for every request the sandbox makes,
    used by password auth to pass the session Cookie and the matching
    X-XSRFToken. A password-authenticated server has no token, so callers pass
    ``token=None`` alongside and let the headers authenticate.
    """
    from code_sandboxes import Sandbox

    log = logger or logging.getLogger(__name__)

    client_kwargs: dict[str, Any] = {}
    if reconnect_interval:
        client_kwargs["reconnect_interval"] = reconnect_interval

    create_kwargs: dict[str, Any] = {
        "variant": "jupyter",
        "server_url": server_url,
        "token": token,
        "kernel_id": kernel_id,
        "kernel_path": path,
        # Preserve original semantics: no id means create a new kernel.
        "reuse_kernel": False,
    }
    if timeout is not None:
        create_kwargs["timeout"] = float(timeout)
    if client_kwargs:
        create_kwargs["client_kwargs"] = client_kwargs
    if headers:
        create_kwargs["headers"] = dict(headers)

    sandbox = Sandbox.create(**create_kwargs)
    try:
        sandbox.start()
        client = sandbox.kernel_client
        if client is None:
            raise RuntimeError("Sandbox started but no kernel_client was exposed")

        # Keep a reference for cleanup/diagnostics by callers that manage
        # lifecycle beyond the kernel-client API.
        setattr(client, "_sandbox", sandbox)
        _attach_sandbox_stop(client, sandbox, log)
        return client
    except Exception:
        try:
            sandbox.stop()
        except Exception:
            log.debug("Error stopping sandbox after startup failure", exc_info=True)
        raise
