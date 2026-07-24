# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The Jupyter MCP Server sandboxes extension.

Registers the sandbox lifecycle tools (``launch_sandbox``, ``list_sandboxes``,
``use_sandbox``, ``terminate_sandbox``), routes ``execute_code`` to the active
sandbox when one is selected, and provides sandbox-backed kernels for
non-``jupyter`` sandbox variants.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional

from reactor import PluginCompatibility, PluginManifest
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.extensions import JupyterMCPExtension
from jupyter_mcp_server.hooks import with_hooks
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.utils import safe_notebook_operation
from mcp.types import ToolAnnotations
from pydantic import Field

from jupyter_mcp_sandboxes.manager import SandboxRuntimeManager
from jupyter_mcp_sandboxes.tools import (
    LaunchSandboxTool,
    ListSandboxesTool,
    TerminateSandboxTool,
    UseSandboxTool,
)

logger = logging.getLogger(__name__)


class SandboxesExtension(JupyterMCPExtension):
    """Sandboxes extension for Jupyter MCP Server."""

    def __init__(self) -> None:
        self._manager = SandboxRuntimeManager()

    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="jupyter-mcp-sandboxes",
            version="0.1.0",
            description=(
                "Launch and use code-sandboxes runtimes as an alternative to "
                "Jupyter kernels for code execution."
            ),
            author="Datalayer",
            tags=["sandbox", "execution"],
            compatibility=PluginCompatibility(api_version="v1"),
        )

    # -- Kernel factory -----------------------------------------------------

    def create_kernel(self, config: Any, log: logging.Logger) -> Optional[Any]:
        """Build a sandbox-backed kernel when a non-jupyter variant is set."""
        uses_variant = getattr(config, "uses_sandbox_variant", None)
        if not (uses_variant and config.uses_sandbox_variant()):
            return None

        from jupyter_mcp_sandboxes.kernel import SandboxKernel, build_sandbox

        kernel = None
        try:
            sandbox = build_sandbox(config, log)
            kernel = SandboxKernel(sandbox, logger=log)
            kernel.start()
            log.info("Sandbox kernel created and started (variant=%s)", config.sandbox_variant)
            return kernel
        except Exception:
            log.exception(
                "Failed to create sandbox kernel (variant=%s)", config.sandbox_variant
            )
            if kernel is not None:
                try:
                    kernel.stop()
                except Exception:
                    log.debug("Error during sandbox cleanup", exc_info=True)
            raise

    # -- execute_code interception -----------------------------------------

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> Optional[list[Any]]:
        """Route execute_code to the active sandbox when one is selected."""
        if not self._manager.get_active_name():
            return None

        async def _execute_in_active_sandbox() -> list[Any]:
            return self._manager.execute_on_active(code=code, timeout=timeout)

        return await safe_notebook_operation(_execute_in_active_sandbox, max_retries=1)

    # -- Lifecycle ----------------------------------------------------------

    def on_stop(self) -> None:
        self._manager.terminate_all()

    # -- Tool registration --------------------------------------------------

    def register_tools(self, mcp: Any) -> None:
        manager = self._manager
        server_context = ServerContext.get_instance()

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Launch Sandbox",
                destructiveHint=True,
            ),
        )
        @with_hooks("launch_sandbox")
        async def launch_sandbox(
            sandbox_name: Annotated[
                str, Field(description="Unique sandbox identifier used by list/use/terminate tools")
            ],
            variant: Annotated[
                Literal["eval", "docker", "jupyter", "datalayer", "colab", "kaggle", "monty", "modal"]
                | None,
                Field(
                    description=(
                        "Sandbox variant to launch. If omitted, defaults to configured "
                        "SANDBOX_VARIANT when it is non-jupyter; otherwise falls back to eval."
                    )
                ),
            ] = None,
            timeout: Annotated[
                int, Field(description="Default execution timeout in seconds for this sandbox", ge=1)
            ] = 60,
            environment: Annotated[
                str | None,
                Field(description="Optional sandbox environment name (common for datalayer/modal variants)"),
            ] = None,
            gpu: Annotated[
                str | None,
                Field(
                    description=(
                        "Optional GPU flavor / accelerator for supported variants "
                        "(modal/datalayer examples: T4, A10G, A100, H100; "
                        "kaggle examples: NvidiaTeslaT4, NvidiaTeslaP100, or aliases T4/P100)."
                    )
                ),
            ] = None,
            server_url: Annotated[
                str | None,
                Field(description="Runtime proxy URL when using colab or kaggle variant"),
            ] = None,
            kernel_id: Annotated[
                str | None,
                Field(description="Kernel ID when using colab or kaggle variant"),
            ] = None,
            proxy_token: Annotated[
                str | None,
                Field(description="Colab runtime proxy token when using colab variant"),
            ] = None,
            channels_url: Annotated[
                str | None,
                Field(
                    description="Notebook session WebSocket channels URL to derive server_url/kernel_id (colab or kaggle variant)"
                ),
            ] = None,
            token: Annotated[
                str | None,
                Field(
                    description="Datalayer API token override, or Kaggle API token for the kaggle variant (falls back to KAGGLE_API_TOKEN)"
                ),
            ] = None,
            run_url: Annotated[str | None, Field(description="Datalayer run URL override")] = None,
            python_version: Annotated[
                str | None,
                Field(description="Modal Python version override (e.g. 3.12). Only used for modal variant."),
            ] = None,
        ) -> Annotated[dict, Field(description="Launch status and sandbox metadata")]:
            """Launch a code-sandboxes runtime that can be used instead of Jupyter kernels.

            After launch, call use_sandbox to make execute_code run on this sandbox
            (as an alternative to notebook-bound kernel execution). Works in both
            MCP_SERVER and JUPYTER_SERVER modes.
            """
            configured_variant = get_config().sandbox_variant
            resolved_variant = variant or (
                configured_variant if configured_variant != "jupyter" else "eval"
            )

            return await safe_notebook_operation(
                lambda: LaunchSandboxTool().execute(
                    mode=server_context.mode,
                    sandbox_runtime_manager=manager,
                    sandbox_name=sandbox_name,
                    variant=resolved_variant,
                    timeout=timeout,
                    environment=environment,
                    gpu=gpu,
                    server_url=server_url,
                    kernel_id=kernel_id,
                    proxy_token=proxy_token,
                    channels_url=channels_url,
                    token=token,
                    run_url=run_url,
                    python_version=python_version,
                )
            )

        @mcp.tool(
            annotations=ToolAnnotations(
                title="List Sandboxes",
                readOnlyHint=True,
            ),
        )
        @with_hooks("list_sandboxes")
        async def list_sandboxes() -> Annotated[
            list[dict],
            Field(description="All launched sandboxes with name, variant, status, and active flag"),
        ]:
            """List launched sandbox runtimes that can be used as alternatives to kernels."""
            return await safe_notebook_operation(
                lambda: ListSandboxesTool().execute(
                    mode=server_context.mode,
                    sandbox_runtime_manager=manager,
                )
            )

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Use Sandbox",
                destructiveHint=True,
            ),
        )
        @with_hooks("use_sandbox")
        async def use_sandbox(
            sandbox_name: Annotated[
                str | None,
                Field(
                    description=(
                        "Sandbox name to activate for execute_code. Pass null/empty to disable sandbox routing and return to Jupyter kernels."
                    )
                ),
            ] = None,
        ) -> Annotated[str, Field(description="Sandbox routing status")]:
            """Select which launched sandbox execute_code should use instead of kernels."""
            return await safe_notebook_operation(
                lambda: UseSandboxTool().execute(
                    mode=server_context.mode,
                    sandbox_runtime_manager=manager,
                    sandbox_name=sandbox_name,
                )
            )

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Terminate Sandbox",
                destructiveHint=True,
            ),
        )
        @with_hooks("terminate_sandbox")
        async def terminate_sandbox(
            sandbox_name: Annotated[str, Field(description="Sandbox name to terminate and unregister")],
        ) -> Annotated[str, Field(description="Termination status message")]:
            """Terminate a launched sandbox runtime."""
            return await safe_notebook_operation(
                lambda: TerminateSandboxTool().execute(
                    mode=server_context.mode,
                    sandbox_runtime_manager=manager,
                    sandbox_name=sandbox_name,
                )
            )
