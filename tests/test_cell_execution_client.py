# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Which client a notebook cell executes on.

`CodeSandboxClient.execute_interactive` replays a cell's outputs only when the
execution ends, so a cell executed through it shows nothing in the notebook
while it runs. A sandbox backed by a Jupyter kernel exposes the kernel client
it executes on, whose `execute_interactive` hands over each output as it
arrives; cells execute on that one. The live behaviour is covered end to end
by `test_execute_cell_streams_outputs_live.py`; this pins down the choice.

Launch the tests:
```
$ pytest tests/test_cell_execution_client.py -v
```
"""

from __future__ import annotations

from code_sandboxes import CodeSandboxClient

from jupyter_mcp_server.utils import cell_execution_client


class KernelClient:
    """The surface of `jupyter_kernel_client.JupyterKernelClient` used here."""

    def execute_interactive(self, code, **kwargs): ...

    def interrupt(self): ...


class JupyterLikeSandbox:
    def __init__(self, kernel_client):
        self.kernel_client = kernel_client


class SandboxWithoutKernelClient:
    """Every variant that does not run on a Jupyter kernel."""


def test_a_jupyter_sandbox_executes_cells_on_its_kernel_client():
    kernel_client = KernelClient()
    wrapper = CodeSandboxClient(JupyterLikeSandbox(kernel_client))
    assert cell_execution_client(wrapper) is kernel_client


def test_a_sandbox_without_a_kernel_client_keeps_the_wrapper():
    wrapper = CodeSandboxClient(SandboxWithoutKernelClient())
    assert cell_execution_client(wrapper) is wrapper


def test_a_sandbox_not_started_yet_keeps_the_wrapper():
    """`kernel_client` is `None` until the sandbox starts."""
    wrapper = CodeSandboxClient(JupyterLikeSandbox(None))
    assert cell_execution_client(wrapper) is wrapper


def test_a_kernel_client_that_cannot_be_interrupted_is_not_used():
    """A cell that cannot be stopped is worse than one that does not stream:
    the timeout and `tasks/cancel` interrupt through this same client."""

    class NoInterrupt:
        def execute_interactive(self, code, **kwargs): ...

    wrapper = CodeSandboxClient(JupyterLikeSandbox(NoInterrupt()))
    assert cell_execution_client(wrapper) is wrapper


def test_anything_else_is_passed_through_untouched():
    """Extensions and tests may hand over their own kernel objects."""
    custom = object()
    assert cell_execution_client(custom) is custom
