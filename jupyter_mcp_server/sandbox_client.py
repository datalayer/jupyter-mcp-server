# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Create variant-neutral Code Sandbox clients for Jupyter connections."""

from __future__ import annotations

import logging
from typing import Any

from code_sandboxes import CodeSandboxClient


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
) -> CodeSandboxClient:
    """Build and start a `jupyter-server` variant Code Sandbox client."""
    client_kwargs: dict[str, Any] = {}
    if reconnect_interval:
        client_kwargs["reconnect_interval"] = reconnect_interval

    create_kwargs: dict[str, Any] = {
        "variant": "jupyter-server",
        "server_url": server_url,
        "token": token,
        "kernel_id": kernel_id,
        "kernel_path": path,
        "reuse_kernel": False,
    }
    if timeout is not None:
        create_kwargs["timeout"] = float(timeout)
    if client_kwargs:
        create_kwargs["client_kwargs"] = client_kwargs
    if headers:
        create_kwargs["headers"] = dict(headers)

    client = CodeSandboxClient.create(**create_kwargs)
    try:
        client.start()
        return client
    except Exception:
        try:
            client.close()
        except Exception:
            (logger or logging.getLogger(__name__)).debug(
                "Error stopping code sandbox after startup failure",
                exc_info=True,
            )
        raise
