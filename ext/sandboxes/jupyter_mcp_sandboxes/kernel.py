# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Variant-aware Code Sandbox client construction for the MCP extension."""

from __future__ import annotations

from typing import Any

from code_sandboxes import CodeSandboxClient


def _is_default_code_sandbox_url(code_sandbox_url: str | None) -> bool:
    if not code_sandbox_url:
        return True
    normalized = code_sandbox_url.strip().lower()
    return normalized in {"http://localhost:8888", "http://127.0.0.1:8888", "local"}


def build_sandbox_client(config, logger) -> CodeSandboxClient:
    """Build an unstarted client for the configured sandbox variant."""
    del logger
    engine = (config.sandbox_variant or "jupyter").lower()
    if engine in {"google-colab", "colab"}:
        engine = "google_colab"
    timeout = float(getattr(config, "execution_timeout", 30) or 30)

    if engine == "google_colab":
        create_kwargs: dict[str, Any] = {
            "variant": "google_colab",
            "timeout": timeout,
            "server_url": config.code_sandbox_url,
            "proxy_token": config.code_sandbox_proxy_token,
        }
        if config.code_sandbox_id:
            create_kwargs["kernel_id"] = config.code_sandbox_id
        if getattr(config, "code_sandbox_channels_url", None):
            create_kwargs["channels_url"] = config.code_sandbox_channels_url
        return CodeSandboxClient.create(**create_kwargs)

    if engine == "kaggle":
        code_sandbox_url = getattr(config, "code_sandbox_url", None)
        channels_url = getattr(config, "code_sandbox_channels_url", None)
        has_explicit_url = not _is_default_code_sandbox_url(code_sandbox_url)
        create_kwargs = {"variant": "kaggle", "timeout": timeout}
        if has_explicit_url and not channels_url:
            create_kwargs["server_url"] = code_sandbox_url
        if config.code_sandbox_id:
            create_kwargs["kernel_id"] = config.code_sandbox_id
        if channels_url:
            create_kwargs["channels_url"] = channels_url
        if config.code_sandbox_token:
            create_kwargs["token"] = config.code_sandbox_token
        if getattr(config, "sandbox_gpu", None):
            create_kwargs["gpu"] = config.sandbox_gpu
        return CodeSandboxClient.create(**create_kwargs)

    if engine in ("jupyter", "jupyter_sandbox"):
        create_kwargs = {
            "variant": "jupyter",
            "timeout": timeout,
            "server_url": config.code_sandbox_url,
            "token": config.code_sandbox_token,
            "kernel_id": config.code_sandbox_id,
            "reuse_kernel": False,
        }
        reconnect_interval = getattr(config, "reconnect_interval", 0) or 0
        if reconnect_interval:
            create_kwargs["client_kwargs"] = {"reconnect_interval": reconnect_interval}
        return CodeSandboxClient.create(**create_kwargs)

    if engine in ("monty", "modal", "eval", "docker", "datalayer"):
        create_kwargs = {"variant": engine, "timeout": timeout}
        if engine in ("modal", "datalayer") and getattr(config, "sandbox_gpu", None):
            create_kwargs["gpu"] = config.sandbox_gpu
        if engine == "datalayer":
            if config.code_sandbox_token:
                create_kwargs["token"] = config.code_sandbox_token
            if config.code_sandbox_url:
                create_kwargs["run_url"] = config.code_sandbox_url
        if config.sandbox_environment:
            create_kwargs["environment"] = config.sandbox_environment
        return CodeSandboxClient.create(**create_kwargs)

    raise ValueError(f"Unsupported sandbox variant: {config.sandbox_variant}")


def create_sandbox_client(config, logger) -> CodeSandboxClient:
    """Create and start the configured variant-neutral client."""
    client = build_sandbox_client(config, logger)
    try:
        client.start()
        return client
    except Exception:
        try:
            client.close()
        except Exception:
            logger.debug("Error stopping sandbox after startup failure", exc_info=True)
        raise
