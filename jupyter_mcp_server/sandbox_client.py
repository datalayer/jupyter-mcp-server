# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Create variant-neutral Code Sandbox clients for Jupyter connections."""

from __future__ import annotations

import logging
from typing import Any

from code_sandboxes import CodeSandboxClient


class JupyterMessageShim:
    """Give Code Sandbox output messages the Jupyter envelope consumers expect.

    ``NotebookModel.execute_cell`` talks to the kernel client the way it talks
    to ``JupyterKernelClient``, which differs from ``CodeSandboxClient`` in two
    ways:

    * Its ``output_hook`` (``jupyter_kernel_client.client.output_hook``) reads
      ``message["header"]["msg_type"]``, but the sandbox client emits
      ``{"msg_type": ..., "content": ...}`` with no header —
      ``KeyError: 'header'``, and every cell output is lost.
    * It reads the reply as ``reply["content"]["status"]``, but the sandbox
      client returns ``status``/``execution_count`` flat — ``KeyError:
      'content'``.

    This wrapper restores both envelopes. Everything else is delegated
    untouched to the wrapped client.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def execute_interactive(self, *args: Any, **kwargs: Any) -> Any:
        output_hook = kwargs.get("output_hook")
        if output_hook is not None:
            kwargs["output_hook"] = _with_jupyter_header(output_hook)
        reply = self._client.execute_interactive(*args, **kwargs)
        return _with_reply_content(reply)


def _with_jupyter_header(output_hook: Any) -> Any:
    """Wrap ``output_hook`` so each message carries a ``header``."""

    def _hook(message: Any) -> Any:
        if isinstance(message, dict) and "header" not in message:
            message = dict(message)
            message["header"] = {"msg_type": message.get("msg_type", "display_data")}
        return output_hook(message)

    return _hook


def _with_reply_content(reply: Any) -> Any:
    """Nest a flat execute reply under ``content``, as Jupyter replies are."""
    if not isinstance(reply, dict) or "content" in reply:
        return reply
    reply = dict(reply)
    reply["content"] = {
        "status": reply.get("status", "ok"),
        "execution_count": reply.get("execution_count"),
    }
    return reply


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
    """Build and start a Jupyter-variant Code Sandbox client."""
    client_kwargs: dict[str, Any] = {}
    if reconnect_interval:
        client_kwargs["reconnect_interval"] = reconnect_interval

    create_kwargs: dict[str, Any] = {
        "variant": "jupyter",
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
