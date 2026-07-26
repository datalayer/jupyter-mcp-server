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
from typing import Any

from code_sandboxes.interfaces import ISandboxClient


def create_jupyter_sandbox_client(
    *,
    server_url: str | None,
    token: str | None,
    kernel_id: str | None = None,
    path: str | None = None,
    timeout: float | None = None,
    reconnect_interval: int = 0,
    logger: logging.Logger | None = None,
) -> ISandboxClient:
    """Build and start a jupyter sandbox, then return its plain kernel client.

    When ``kernel_id`` is provided, the client connects to that specific
    existing kernel; otherwise a new kernel is created.
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

    sandbox = Sandbox.create(**create_kwargs)
    try:
        sandbox.start()
        client = sandbox.kernel_client
        if client is None:
            raise RuntimeError("Sandbox started but no kernel_client was exposed")

        # Keep a reference for cleanup/diagnostics by callers that manage
        # lifecycle beyond the kernel-client API.
        setattr(client, "_sandbox", sandbox)
        return client
    except Exception:
        try:
            sandbox.stop()
        except Exception:
            log.debug("Error stopping sandbox after startup failure", exc_info=True)
        raise
