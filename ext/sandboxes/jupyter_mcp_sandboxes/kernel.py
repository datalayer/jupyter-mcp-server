# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Sandbox construction helpers used by the sandboxes extension.

This module exposes:

- :func:`build_sandbox`: variant-aware sandbox construction.
- :func:`create_sandbox_kernel_client`: direct kernel-client creation from a
    sandbox when the variant exposes one.
- :func:`_execution_result_to_reply`: shared output conversion helper used by
    sandbox runtime tooling.
"""

from __future__ import annotations

import logging
from types import MethodType
from typing import Any


def _is_default_runtime_url(runtime_url: str | None) -> bool:
    if not runtime_url:
        return True
    normalized = runtime_url.strip().lower()
    return normalized in {"http://localhost:8888", "http://127.0.0.1:8888", "local"}


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


def build_sandbox(config, logger):
    """Build a code-sandboxes Sandbox for the configured sandbox variant.

    Args:
        config: The JupyterMCPConfig instance.
        logger: Logger for diagnostics.

    Returns:
        A started-capable ``code_sandboxes.Sandbox`` instance (not yet started).
    """
    from code_sandboxes import Sandbox

    engine = (config.sandbox_variant or "jupyter").lower()
    timeout = float(getattr(config, "execution_timeout", 30) or 30)

    if engine == "colab":
        create_kwargs: dict[str, Any] = {
            "variant": "colab",
            "timeout": timeout,
            "server_url": config.runtime_url,
            "proxy_token": config.runtime_proxy_token,
        }
        if config.runtime_id:
            create_kwargs["kernel_id"] = config.runtime_id
        if getattr(config, "runtime_channels_url", None):
            create_kwargs["channels_url"] = config.runtime_channels_url
        return Sandbox.create(**create_kwargs)
    if engine == "kaggle":
        runtime_url = getattr(config, "runtime_url", None)
        channels_url = getattr(config, "runtime_channels_url", None)
        has_explicit_runtime_url = not _is_default_runtime_url(runtime_url)

        create_kwargs: dict[str, Any] = {
            "variant": "kaggle",
            "timeout": timeout,
        }
        # If runtime values are not explicitly configured, prefer the
        # transparent batch path in code-sandboxes.
        if has_explicit_runtime_url and not channels_url:
            create_kwargs["server_url"] = runtime_url
        if config.runtime_id:
            create_kwargs["kernel_id"] = config.runtime_id
        if channels_url:
            create_kwargs["channels_url"] = channels_url
        if config.runtime_token:
            create_kwargs["token"] = config.runtime_token
        if getattr(config, "sandbox_gpu", None):
            create_kwargs["gpu"] = config.sandbox_gpu
        return Sandbox.create(**create_kwargs)
    if engine in ("jupyter", "jupyter_sandbox"):
        create_kwargs: dict[str, Any] = {
            "variant": "jupyter",
            "timeout": timeout,
            "server_url": config.runtime_url,
            "token": config.runtime_token,
            "kernel_id": config.runtime_id,
            # Keep parity with the core jupyter sandbox path: no runtime_id
            # means create a fresh kernel rather than reusing an arbitrary one.
            "reuse_kernel": False,
        }
        reconnect_interval = getattr(config, "reconnect_interval", 0) or 0
        if reconnect_interval:
            create_kwargs["client_kwargs"] = {"reconnect_interval": reconnect_interval}
        return Sandbox.create(**create_kwargs)
    if engine in ("monty", "modal", "eval", "docker", "datalayer"):
        create_kwargs = {"variant": engine, "timeout": timeout}
        if engine in ("modal", "datalayer") and getattr(config, "sandbox_gpu", None):
            create_kwargs["gpu"] = config.sandbox_gpu
        if engine == "datalayer":
            if config.runtime_token:
                create_kwargs["token"] = config.runtime_token
            if config.runtime_url:
                create_kwargs["run_url"] = config.runtime_url
        if config.sandbox_environment:
            create_kwargs["environment"] = config.sandbox_environment
        return Sandbox.create(**create_kwargs)

    raise ValueError(f"Unsupported sandbox variant: {config.sandbox_variant}")


def _attach_sandbox_stop(client: Any, sandbox: Any, logger: logging.Logger | None = None) -> None:
    """Ensure ``client.stop()`` also tears down the backing sandbox.

    ``shutdown_kernel=False`` preserves borrowed-kernel semantics by skipping
    sandbox-level shutdown.
    """
    original_stop = getattr(client, "stop", None)
    if not callable(original_stop) or getattr(client, "_mcp_sandbox_stop_wrapped", False):
        return

    log = logger or logging.getLogger(__name__)

    def _stop_with_sandbox(self, *args: Any, **kwargs: Any):
        shutdown_kernel = kwargs.get("shutdown_kernel", None)
        if shutdown_kernel is None and args:
            shutdown_kernel = args[0]

        if shutdown_kernel is False:
            return original_stop(*args, **kwargs)

        try:
            setattr(self, "stop", original_stop)
            return sandbox.stop()
        except Exception:
            log.debug("Error stopping sandbox from wrapped extension client.stop", exc_info=True)
            return original_stop(*args, **kwargs)
        finally:
            setattr(self, "stop", MethodType(_stop_with_sandbox, self))

    setattr(client, "stop", MethodType(_stop_with_sandbox, client))
    setattr(client, "_mcp_sandbox_stop_wrapped", True)


def create_sandbox_kernel_client(config, logger) -> Any:
    """Create and start a sandbox, then return its plain kernel client.

    This only supports variants exposing ``sandbox.kernel_client``.
    """
    sandbox = build_sandbox(config, logger)
    try:
        sandbox.start()
        client = getattr(sandbox, "kernel_client", None)
        if client is None:
            variant = getattr(config, "sandbox_variant", None)
            raise RuntimeError(
                "Sandbox variant does not expose a kernel client for notebook-bound "
                f"kernel flows: {variant!r}. Use launch_sandbox/use_sandbox with "
                "execute_code, or a kernel-backed variant (jupyter/colab/kaggle/docker)."
            )
        setattr(client, "_sandbox", sandbox)
        _attach_sandbox_stop(client, sandbox, logger)
        return client
    except Exception:
        try:
            sandbox.stop()
        except Exception:
            pass
        raise
