# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests that execute_code reports the kernel it actually ran on to the hooks."""

import pytest

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool


PROVISIONED_KERNEL_ID = "kernel-provisioned-during-this-call"


class RecordingHandler:
    """Records the kernel_id carried by every execution hook."""

    def __init__(self):
        self.propagate_errors = False
        self.kernel_ids: list[tuple[HookEvent, str]] = []

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        if event in (HookEvent.BEFORE_EXECUTE, HookEvent.AFTER_EXECUTE):
            self.kernel_ids.append((event, kwargs.get("kernel_id")))


class FakeCodeSandbox:
    """Minimal stand-in for the sandbox client the factory hands back."""

    def __init__(self, sandbox_id):
        self.id = sandbox_id

    def is_alive(self):
        return True

    def execute(self, code):
        return {"outputs": []}


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests."""
    HookRegistry.reset()
    yield
    HookRegistry.reset()


async def _noop_wait_for_idle(code_sandbox, max_wait_seconds=30):
    return None


@pytest.mark.asyncio
async def test_hooks_receive_the_kernel_provisioned_during_this_call():
    notebook_manager = NotebookManager()
    notebook_manager.add_notebook("notebook", None)
    notebook_manager.set_current_notebook("notebook")

    handler = RecordingHandler()
    HookRegistry.get_instance().register(handler)

    await ExecuteCodeTool()._execute_via_notebook_manager(
        notebook_manager=notebook_manager,
        code="1 + 1",
        timeout=5,
        ensure_code_sandbox_alive_fn=lambda: notebook_manager.ensure_code_sandbox_alive(
            "notebook", lambda: FakeCodeSandbox(PROVISIONED_KERNEL_ID)
        ),
        wait_for_code_sandbox_idle_fn=_noop_wait_for_idle,
        safe_extract_outputs_fn=lambda outputs: [],
    )

    assert handler.kernel_ids == [
        (HookEvent.BEFORE_EXECUTE, PROVISIONED_KERNEL_ID),
        (HookEvent.AFTER_EXECUTE, PROVISIONED_KERNEL_ID),
    ]


@pytest.mark.asyncio
async def test_hooks_receive_the_kernel_id_when_the_sandbox_already_exists():
    notebook_manager = NotebookManager()
    notebook_manager.add_notebook("notebook", FakeCodeSandbox("kernel-already-running"))
    notebook_manager.set_current_notebook("notebook")

    handler = RecordingHandler()
    HookRegistry.get_instance().register(handler)

    def _fail_if_called():
        raise AssertionError("an existing sandbox must not be re-provisioned")

    await ExecuteCodeTool()._execute_via_notebook_manager(
        notebook_manager=notebook_manager,
        code="1 + 1",
        timeout=5,
        ensure_code_sandbox_alive_fn=_fail_if_called,
        wait_for_code_sandbox_idle_fn=_noop_wait_for_idle,
        safe_extract_outputs_fn=lambda outputs: [],
    )

    assert handler.kernel_ids == [
        (HookEvent.BEFORE_EXECUTE, "kernel-already-running"),
        (HookEvent.AFTER_EXECUTE, "kernel-already-running"),
    ]
