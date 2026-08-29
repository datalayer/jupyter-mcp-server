# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Variant-aware Code Sandbox client construction for the MCP extension."""

from __future__ import annotations

from typing import Any

from code_sandboxes import CodeSandboxClient, normalize_variant

from jupyter_mcp_server.config import JUPYTER_SERVER_VARIANT


def _is_default_code_sandbox_url(code_sandbox_url: str | None) -> bool:
    if not code_sandbox_url:
        return True
    normalized = code_sandbox_url.strip().lower()
    return normalized in {"http://localhost:8888", "http://127.0.0.1:8888", "local"}


def build_sandbox_client(config, logger) -> CodeSandboxClient:
    """Build an unstarted client for the configured sandbox variant."""
    del logger
    # Read the way `code_sandboxes` reads it, rather than with a table of
    # aliases of our own: it answers to a dash, an underscore or capitals, and
    # a second table is a second thing to keep in step through a rename.
    engine = normalize_variant(config.sandbox_variant or JUPYTER_SERVER_VARIANT)
    timeout = float(getattr(config, "execution_timeout", 30) or 30)

    if engine == "google-colab":
        create_kwargs: dict[str, Any] = {
            "variant": "google-colab",
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

    if engine == JUPYTER_SERVER_VARIANT:
        create_kwargs = {
            "variant": JUPYTER_SERVER_VARIANT,
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

    if engine in (
        "monty",
        "modal",
        "eval",
        "docker",
        "daytona",
        "e2b",
        "coreweave",
        "cloudflare",
        "datalayer",
    ):
        create_kwargs = {"variant": engine, "timeout": timeout}
        # A GPU asked for is passed on WHATEVER the engine is, because
        # `code_sandboxes` is where the answer lives: the engines that have a
        # GPU take it, and the ones that have none refuse it by name, saying
        # which engines do. Filtering it away here would turn that refusal
        # into silence — SANDBOX_GPU=H100 with SANDBOX_VARIANT=e2b would run
        # on a CPU while looking as though it had been granted an H100, which
        # is the failure worth avoiding.
        if getattr(config, "sandbox_gpu", None):
            create_kwargs["gpu"] = config.sandbox_gpu
        if engine == "datalayer":
            # The caller's own credential when the request carries one, so a
            # server acting for several people runs each person's code as
            # them. `resolved_code_sandbox_token` falls back to whatever was
            # configured, which is the single-user case and unchanged.
            token = _sandbox_token(config)
            if token:
                create_kwargs["token"] = token
            if config.code_sandbox_url:
                create_kwargs["run_url"] = config.code_sandbox_url
        if config.sandbox_environment:
            create_kwargs["environment"] = config.sandbox_environment
        return CodeSandboxClient.create(**create_kwargs)

    raise ValueError(f"Unsupported sandbox variant: {config.sandbox_variant}")


def _sandbox_token(config) -> str | None:
    """The credential to run code with: the caller's, else the configured one.

    Guarded because the resolver arrived in jupyter-mcp-server 1.3.4 and this
    extension supports older ones, where the configured token is all there is.
    """
    resolver = getattr(config, "resolved_code_sandbox_token", None)
    if callable(resolver):
        return resolver()
    return config.code_sandbox_token


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
