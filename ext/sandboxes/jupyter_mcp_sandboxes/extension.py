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
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field
from reactor import PluginCompatibility, PluginManifest

from jupyter_mcp_sandboxes.manager import CodeSandboxManager
from jupyter_mcp_sandboxes.tools import (
    LaunchSandboxTool,
    ListSandboxesTool,
    TerminateSandboxTool,
    UseSandboxTool,
)
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.extensions import JupyterMCPExtension
from jupyter_mcp_server.hooks import with_hooks
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.utils import safe_notebook_operation

logger = logging.getLogger(__name__)


class SandboxesExtension(JupyterMCPExtension):
    """Sandboxes extension for Jupyter MCP Server."""

    def __init__(self) -> None:
        self._manager = CodeSandboxManager()

    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="jupyter-mcp-sandboxes",
            version="0.1.0",
            description=(
                "Launch and use code-sandboxes code sandboxes as an alternative to "
                "Jupyter kernels for code execution."
            ),
            author="Datalayer",
            tags=["sandbox", "execution"],
            compatibility=PluginCompatibility(api_version="v1"),
        )

    # -- Kernel factory -----------------------------------------------------

    @staticmethod
    def _is_reusable(client: Any, log: logging.Logger) -> bool:
        """Whether the selected client can actually run code.

        A client without ``is_alive`` is trusted (nothing to ask); a check
        that raises counts as dead — a client that cannot even answer the
        question is not one to bind a notebook to.
        """
        is_alive = getattr(client, "is_alive", None)
        if is_alive is None:
            return True
        try:
            return bool(is_alive())
        except Exception:
            log.warning("Liveness check on the active sandbox failed", exc_info=True)
            return False

    def create_code_sandbox(self, config: Any, log: logging.Logger) -> Any | None:
        """Build a sandbox-backed kernel when a non-jupyter variant is set."""
        uses_variant = getattr(config, "uses_sandbox_variant", None)
        if not (uses_variant and config.uses_sandbox_variant()):
            return None

        # The sandbox the caller selected with `use_sandbox`, when there is
        # one. Creating a fresh sandbox here would ignore that choice, pay for
        # a second runtime, and run the cell somewhere other than where the
        # caller pointed — the notebook binds to this client, so this is also
        # what makes "assign the sandbox to the notebook" true.
        active = self._manager.get_active()
        if active is not None:
            if self._is_reusable(active, log):
                log.info(
                    "Reusing the active sandbox [%s] as the execution backend",
                    self._manager.get_active_name(),
                )
                return active
            # A dead selection must not become the notebook's backend: the
            # factory would keep handing the same corpse back and
            # ensure_code_sandbox_alive could never recover. Fall through to
            # a fresh sandbox instead.
            log.warning(
                "The active sandbox [%s] is not alive; creating a fresh one",
                self._manager.get_active_name(),
            )

        from jupyter_mcp_sandboxes.kernel import create_sandbox_client

        try:
            sandbox_client = create_sandbox_client(config, log)
            log.info(
                "Code sandbox client created and started (variant=%s)",
                config.sandbox_variant,
            )
            return sandbox_client
        except Exception:
            log.exception(
                "Failed to create code sandbox client (variant=%s)", config.sandbox_variant
            )
            raise

    # -- execute_code interception -----------------------------------------

    async def intercept_execute_code(
        self, code: str, timeout: int
    ) -> list[Any] | None:
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
                Literal[
                    "eval",
                    "docker",
                    "jupyter",
                    "datalayer",
                    "google_colab",
                    "google-colab",
                    "colab",
                    "kaggle",
                    "monty",
                    "modal",
                ]
                | None,
                Field(
                    description=(
                        "Sandbox variant to launch. If omitted, defaults to configured "
                        "SANDBOX_VARIANT when it is non-jupyter; otherwise falls back to eval."
                    )
                ),
            ] = None,
            timeout: Annotated[
                int,
                Field(description="Default execution timeout in seconds for this sandbox", ge=1),
            ] = 60,
            environment: Annotated[
                str | None,
                Field(
                    description=(
                        "Optional sandbox environment name (common for datalayer/modal variants)"
                    )
                ),
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
                Field(
                    description=(
                        "Code Sandbox proxy URL when using google_colab/google-colab "
                        "(or legacy colab) or kaggle variant"
                    )
                ),
            ] = None,
            kernel_id: Annotated[
                str | None,
                Field(
                    description=(
                        "Kernel ID when using google_colab/google-colab "
                        "(or legacy colab) or kaggle variant"
                    )
                ),
            ] = None,
            proxy_token: Annotated[
                str | None,
                Field(
                    description=(
                        "Google Colab code sandbox proxy token when using "
                        "google_colab/google-colab (or legacy colab) variant"
                    )
                ),
            ] = None,
            channels_url: Annotated[
                str | None,
                Field(
                    description=(
                        "Notebook session WebSocket channels URL to derive "
                        "server_url/kernel_id (google_colab/google-colab/colab or kaggle variant)"
                    )
                ),
            ] = None,
            token: Annotated[
                str | None,
                Field(
                    description=(
                        "Datalayer API token override, or Kaggle API token for the"
                        " kaggle variant (falls back to KAGGLE_API_TOKEN)"
                    )
                ),
            ] = None,
            run_url: Annotated[str | None, Field(description="Datalayer run URL override")] = None,
            python_version: Annotated[
                str | None,
                Field(
                    description=(
                        "Modal Python version override (e.g. 3.12). Only used for modal variant."
                    )
                ),
            ] = None,
        ) -> Annotated[dict, Field(description="Launch status and code sandbox metadata")]:
            """Launch a code sandbox that can be used instead of Jupyter kernels.

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
                    code_sandbox_manager=manager,
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
            """List launched code sandboxes that can be used as alternatives to kernels."""
            return await safe_notebook_operation(
                lambda: ListSandboxesTool().execute(
                    mode=server_context.mode,
                    code_sandbox_manager=manager,
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
                        "Sandbox name to activate for execute_code. Pass null/empty to"
                        " disable sandbox routing and return to Jupyter kernels."
                    )
                ),
            ] = None,
        ) -> Annotated[str, Field(description="Sandbox routing status")]:
            """Select which launched sandbox execute_code should use instead of kernels."""
            return await safe_notebook_operation(
                lambda: UseSandboxTool().execute(
                    mode=server_context.mode,
                    code_sandbox_manager=manager,
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
            sandbox_name: Annotated[
                str, Field(description="Sandbox name to terminate and unregister")
            ],
        ) -> Annotated[str, Field(description="Termination status message")]:
            """Terminate a launched code sandbox."""
            return await safe_notebook_operation(
                lambda: TerminateSandboxTool().execute(
                    mode=server_context.mode,
                    code_sandbox_manager=manager,
                    sandbox_name=sandbox_name,
                )
            )
