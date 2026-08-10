# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

import json

import pytest

from jupyter_mcp_server.utils import execute_via_execution_stack


class _ExecutionStack:
    def __init__(self):
        self._results = iter(
            [
                {
                    "pending": True,
                    "request_status": "queued",
                    "outputs": "[]",
                },
                {
                    "pending": True,
                    "request_status": "running",
                    "outputs": json.dumps(
                        [{"output_type": "stream", "name": "stdout", "text": "partial\n"}]
                    ),
                },
                {
                    "pending": False,
                    "request_status": "complete",
                    "status": "ok",
                    "execution_count": 1,
                    "outputs": json.dumps(
                        [{"output_type": "stream", "name": "stdout", "text": "complete\n"}]
                    ),
                },
            ]
        )

    def put(self, kernel_id, code, metadata):
        return "request-id"

    def get(self, kernel_id, request_id):
        return next(self._results)


class _Extension:
    def __init__(self, execution_stack):
        self._Extension__execution_stack = execution_stack


class _ExtensionManager:
    def __init__(self, extension):
        self.extension_apps = {"jupyter_server_nbmodel": {extension}}


class _ServerApp:
    def __init__(self, execution_stack):
        self.extension_manager = _ExtensionManager(_Extension(execution_stack))


@pytest.mark.asyncio
async def test_rich_pending_snapshots_are_not_treated_as_completion():
    raw_outputs = []
    execution_counts = []

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(_ExecutionStack()),
        kernel_id="kernel-id",
        code="print('complete')",
        poll_interval=0,
        raw_outputs=raw_outputs,
        execution_count_out=execution_counts,
    )

    assert any("complete" in str(output) for output in outputs)
    assert all("partial" not in str(output) for output in outputs)
    assert raw_outputs == [{"output_type": "stream", "name": "stdout", "text": "complete\n"}]
    assert execution_counts == [1]
