# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`execute_cell` runs on the sandbox the caller selected — and writes back.

The first attempt at this (PR #375) intercepted `execute_cell` and ran the
cell's source through the same shortcut `execute_code` uses. The cell ran, an
answer came back — and the notebook never changed: no execution count, no
outputs in the document, nothing for anyone watching in the application. That
is `execute_code` semantics wearing `execute_cell`'s name.

The real contract is the ordinary path's: `notebook.execute_cell(index,
kernel)` executes on a code-sandbox client and the collaborative document
consumes the outputs as they stream. So the fix lives one level down — the
kernel *factory* returns the sandbox selected with `use_sandbox` instead of
creating a fresh one — and `execute_cell` itself stays untouched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_sandboxes.extension import SandboxesExtension


def _config(variant="datalayer"):
    return SimpleNamespace(
        sandbox_variant=variant,
        uses_sandbox_variant=lambda: variant != "jupyter",
    )


import logging

LOG = logging.getLogger("test")


class TestTheFactoryHonoursTheSelection:
    def test_the_selected_sandbox_is_the_execution_backend(self):
        """The property the whole fix rests on.

        A caller who launched a sandbox and selected it has said where the
        cell should run. A factory that creates a second runtime ignores
        that, bills for it, and runs the cell somewhere else.
        """
        extension = SandboxesExtension()
        chosen = object()
        extension._manager._sandboxes["mine"] = chosen
        extension._manager._active_name = "mine"

        assert extension.create_code_sandbox(_config(), LOG) is chosen

    def test_without_a_selection_a_sandbox_is_created(self):
        extension = SandboxesExtension()
        built = object()
        with patch(
            "jupyter_mcp_sandboxes.kernel.create_sandbox_client", return_value=built
        ):
            assert extension.create_code_sandbox(_config(), LOG) is built

    def test_the_jupyter_variant_is_left_to_the_core(self):
        # A plain Jupyter deployment has no sandbox layer to consult.
        extension = SandboxesExtension()
        extension._manager._sandboxes["mine"] = object()
        extension._manager._active_name = "mine"
        assert extension.create_code_sandbox(_config("jupyter"), LOG) is None


class TestExecuteCellIsNotIntercepted:
    def test_the_tool_no_longer_shortcuts_past_the_notebook(self):
        """The revert, pinned.

        If interception comes back to `execute_cell`, outputs stop reaching
        the document again — silently, because the caller still gets its
        answer. This is the cheapest place to notice.
        """
        import inspect

        from jupyter_mcp_server import server

        fn = getattr(server.execute_cell, "fn", server.execute_cell)
        source = inspect.getsource(fn)
        assert "intercept_execute_code" not in source
        assert "_cell_source_for_sandbox" not in source
