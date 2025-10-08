# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Auto-enrollment functionality for Jupyter MCP Server."""

import logging
from typing import Any

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

logger = logging.getLogger(__name__)


async def auto_enroll_document(
    config: Any,
    notebook_manager: NotebookManager,
    use_notebook_tool: UseNotebookTool,
    server_context: Any,
) -> None:
    """Automatically enroll the configured document_id as a managed notebook.
    
    Handles kernel creation/connection based on configuration:
    - If runtime_id is provided: Connect to that specific kernel
    - If start_new_runtime is True: Create a new kernel
    - If both are False/None: Enroll notebook WITHOUT kernel (notebook-only mode)
    
    Args:
        config: JupyterMCPConfig instance with configuration parameters
        notebook_manager: NotebookManager instance for managing notebooks
        use_notebook_tool: UseNotebookTool instance for enrolling notebooks
        server_context: ServerContext instance with server state
    """
    # Check if document_id is configured and not already managed
    if not config.document_id:
        logger.debug("No document_id configured, skipping auto-enrollment")
        return
        
    if "default" in notebook_manager:
        logger.debug("Default notebook already enrolled, skipping auto-enrollment")
        return
    
    # Check if we should skip kernel creation entirely
    if not config.runtime_id and not config.start_new_runtime:
        # Enroll notebook without kernel - just register the notebook path
        try:
            logger.info(f"Auto-enrolling document '{config.document_id}' without kernel (notebook-only mode)")
            # Add notebook to manager without kernel
            notebook_manager.add_notebook(
                "default",
                None,  # No kernel
                server_url=config.document_url,
                token=config.document_token,
                path=config.document_id
            )
            notebook_manager.set_current_notebook("default")
            logger.info(f"Auto-enrollment result: Successfully enrolled notebook 'default' at path '{config.document_id}' without kernel.")
            return
        except Exception as e:
            logger.warning(f"Failed to auto-enroll document without kernel: {e}")
            return
    
    # Otherwise, enroll with kernel
    try:
        # Determine kernel_id based on configuration
        kernel_id_to_use = None
        if config.runtime_id:
            # User explicitly provided a kernel ID to connect to
            kernel_id_to_use = config.runtime_id
            logger.info(f"Auto-enrolling document '{config.document_id}' with existing kernel '{kernel_id_to_use}'")
        elif config.start_new_runtime:
            # User wants a new kernel created
            kernel_id_to_use = None  # Will trigger new kernel creation in use_notebook_tool
            logger.info(f"Auto-enrolling document '{config.document_id}' with new kernel")
        
        # Use the use_notebook_tool to properly enroll the notebook with kernel
        result = await use_notebook_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            notebook_name="default",
            notebook_path=config.document_id,
            use_mode="connect",
            kernel_id=kernel_id_to_use,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            session_manager=server_context.session_manager,
            notebook_manager=notebook_manager,
            runtime_url=config.runtime_url if config.runtime_url != "local" else None,
            runtime_token=config.runtime_token,
        )
        logger.info(f"Auto-enrollment result: {result}")
    except Exception as e:
        logger.warning(f"Failed to auto-enroll document: {e}. You can manually use it with use_notebook tool.")
