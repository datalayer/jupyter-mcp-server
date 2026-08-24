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


class _SingleResultExecutionStack:
    """Return one terminal result, whatever it is, on the first poll."""

    def __init__(self, result):
        self._result = result

    def put(self, kernel_id, code, metadata):
        return "request-id"

    def get(self, kernel_id, request_id):
        return self._result

    def cancel(self, kernel_id):
        pass


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


@pytest.mark.asyncio
async def test_string_shaped_error_keeps_its_message():
    # jupyter-server-nbmodel writes a request-level failure as a plain string,
    # which is the only shape it ever writes for the "error" key: a kernel it
    # could not connect to, a superseded request, a cancelled request. The
    # missing-kernel one leaves as an exception instead, so execute_cell can
    # retry it; see tests/test_execute_cell_dead_kernel_retry.py.
    raw_outputs = []

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(
            _SingleResultExecutionStack(
                {
                    "error": "Request superseded by a newer execution for this cell",
                    "pending": False,
                    "request_status": "complete",
                }
            )
        ),
        kernel_id="kernel-id",
        code="print('hi')",
        poll_interval=0,
        raw_outputs=raw_outputs,
    )

    assert outputs == [
        "[ERROR: ExecutionError: Request superseded by a newer execution for this cell]"
    ]
    assert raw_outputs == [
        {
            "output_type": "error",
            "ename": "ExecutionError",
            "evalue": "Request superseded by a newer execution for this cell",
            "traceback": [],
        }
    ]


@pytest.mark.asyncio
async def test_mapping_shaped_error_still_reports_ename_and_evalue():
    raw_outputs = []

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(
            _SingleResultExecutionStack(
                {
                    "error": {
                        "ename": "ZeroDivisionError",
                        "evalue": "division by zero",
                        "traceback": ["Traceback line"],
                    },
                    "pending": False,
                    "request_status": "complete",
                }
            )
        ),
        kernel_id="kernel-id",
        code="1/0",
        poll_interval=0,
        raw_outputs=raw_outputs,
    )

    assert outputs == ["[ERROR: ZeroDivisionError: division by zero]"]
    assert raw_outputs == [
        {
            "output_type": "error",
            "ename": "ZeroDivisionError",
            "evalue": "division by zero",
            "traceback": ["Traceback line"],
        }
    ]
