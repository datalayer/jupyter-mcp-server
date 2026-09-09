# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`execute_via_execution_stack_http` drives the runtime's HTTP /execute route.

The in-process driver reads `ExecutionStack.get` straight off the extension;
this one cannot (the worker is a separate process), so it POSTs to
`/api/kernels/{id}/execute` and polls the request URL, turning on the HTTP
*status code* — 202 pending/running, 200 complete, 300 input, 500 error. The
route serializes the same result dict either way, so the terminal handling is
shared and only the transport is faked here. No live runtime needed.
"""

import json

import pytest

from jupyter_mcp_server.utils import (
    MissingKernelError,
    document_id_from_ws_url,
    execute_via_execution_stack_http,
)


class _FakeTransport:
    """A scripted async transport: one POST answer, a sequence of GET answers.

    Each method answers `(status_code, body, headers)`, the shape the poll loop
    needs — the real runtime's 202/300/500 would be hidden by a client that
    raised on non-2xx.
    """

    def __init__(self, *, post=(202, None, None), polls=()):
        status, body, headers = post
        self._post = (
            status,
            body
            if body is not None
            else {
                "request_id": "r1",
                "request_url": "/api/kernels/k1/requests/r1",
            },
            headers or {},
        )
        self._polls = iter(polls)
        self.posted: list = []
        self.got: list = []

    async def post(self, path, json=None):
        self.posted.append((path, json))
        return self._post

    async def get(self, path):
        self.got.append(path)
        status, body = next(self._polls)
        return status, body, {}


@pytest.mark.asyncio
async def test_a_complete_run_returns_its_outputs_and_counts():
    raw_outputs: list = []
    execution_counts: list = []
    transport = _FakeTransport(
        polls=[
            (202, {"request_status": "running", "outputs": "[]"}),
            (
                200,
                {
                    "request_status": "complete",
                    "status": "ok",
                    "execution_count": 7,
                    "outputs": json.dumps(
                        [{"output_type": "stream", "name": "stdout", "text": "done\n"}]
                    ),
                },
            ),
        ],
    )

    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="print('done')",
        document_id="json:notebook:file-1",
        cell_id="cell-1",
        poll_interval=0,
        transport=transport,
        raw_outputs=raw_outputs,
        execution_count_out=execution_counts,
    )

    assert any("done" in str(output) for output in outputs)
    assert raw_outputs == [{"output_type": "stream", "name": "stdout", "text": "done\n"}]
    assert execution_counts == [7]
    # It POSTed the code and polled the request_url the runtime handed back,
    # not a guessed path.
    assert transport.posted[0][0] == "/api/kernels/k1/execute"
    assert transport.posted[0][1]["code"] == "print('done')"
    assert transport.got == ["/api/kernels/k1/requests/r1", "/api/kernels/k1/requests/r1"]


@pytest.mark.asyncio
async def test_both_document_and_cell_are_carried_so_the_runtime_can_persist():
    # The durability of outputs past this worker's death depends on the runtime
    # knowing which cell to write into: both ids must reach it, or neither.
    transport = _FakeTransport(polls=[(200, {"outputs": "[]"})])
    await execute_via_execution_stack_http(
        kernel_id="k1",
        code="1+1",
        document_id="json:notebook:file-1",
        cell_id="cell-9",
        poll_interval=0,
        transport=transport,
    )
    assert transport.posted[0][1]["metadata"] == {
        "document_id": "json:notebook:file-1",
        "cell_id": "cell-9",
    }

    # Only one id is not enough to place an output, so no half-metadata is sent.
    transport = _FakeTransport(polls=[(200, {"outputs": "[]"})])
    await execute_via_execution_stack_http(
        kernel_id="k1",
        code="1+1",
        document_id="json:notebook:file-1",
        poll_interval=0,
        transport=transport,
    )
    assert transport.posted[0][1]["metadata"] == {}


@pytest.mark.asyncio
async def test_a_string_shaped_error_keeps_its_message():
    raw_outputs: list = []
    transport = _FakeTransport(
        polls=[(500, {"error": "Request superseded by a newer execution for this cell"})]
    )

    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="print('hi')",
        poll_interval=0,
        transport=transport,
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
async def test_a_mapping_shaped_error_reports_ename_and_evalue():
    transport = _FakeTransport(
        polls=[
            (
                500,
                {
                    "error": {
                        "ename": "ZeroDivisionError",
                        "evalue": "division by zero",
                        "traceback": ["Traceback line"],
                    }
                },
            )
        ]
    )

    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="1/0",
        poll_interval=0,
        transport=transport,
    )

    assert outputs == ["[ERROR: ZeroDivisionError: division by zero]"]


@pytest.mark.asyncio
async def test_a_gone_kernel_raises_missing_kernel_error():
    # A 404 on the POST is the HTTP equivalent of "kernel not found" — left as
    # an exception so execute_cell's replace-and-retry-once path can run.
    transport = _FakeTransport(post=(404, {"message": "kernel not found"}, None))

    with pytest.raises(MissingKernelError):
        await execute_via_execution_stack_http(
            kernel_id="gone",
            code="1+1",
            poll_interval=0,
            transport=transport,
        )


@pytest.mark.asyncio
async def test_an_unexpected_input_request_is_reported():
    # allow_stdin is False, so a 300 input-required is not expected; it is
    # reported rather than hung on.
    transport = _FakeTransport(polls=[(300, {"input_request": {"prompt": "?", "password": False}})])

    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="input()",
        poll_interval=0,
        transport=transport,
    )

    assert outputs == ["[ERROR: Unexpected input request]"]


@pytest.mark.asyncio
async def test_a_run_that_never_finishes_times_out():
    # Every poll stays 202; the loop must give up at the timeout rather than
    # spin forever.
    def _always_running():
        while True:
            yield (202, {"request_status": "running"})

    transport = _FakeTransport()
    transport._polls = _always_running()

    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="while True: pass",
        timeout=0,
        poll_interval=0,
        transport=transport,
    )
    # Timeout is caught by the outer handler and surfaced as an error string.
    assert outputs == ["[ERROR: Execution timed out after 0 seconds]"]


@pytest.mark.asyncio
async def test_an_unexpected_poll_status_is_an_error_not_silence():
    # A 401/403/404/429 while polling is not a result; it must surface as an
    # actionable error rather than a quiet "[No output generated]".
    transport = _FakeTransport(polls=[(403, {"message": "forbidden"})])
    outputs = await execute_via_execution_stack_http(
        kernel_id="k1",
        code="1+1",
        poll_interval=0,
        transport=transport,
    )
    assert len(outputs) == 1
    assert outputs[0].startswith("[ERROR:")
    assert "403" in outputs[0]


def test_document_id_from_ws_url_reads_the_room():
    # A Jupyter collaboration room id is already json:notebook:<fileId>.
    assert (
        document_id_from_ws_url(
            "wss://r/api/collaboration/room/json:notebook:FILE1?sessionId=s"
        )
        == "json:notebook:FILE1"
    )
    # A Datalayer documents endpoint hands back a bare file id; it is wrapped
    # into the form the /execute route writes outputs under.
    assert (
        document_id_from_ws_url("wss://r/api/spacer/documents/ws/FILE2?token=y")
        == "json:notebook:FILE2"
    )
    # Percent-encoded colons are decoded.
    assert (
        document_id_from_ws_url("wss://r/api/collaboration/room/json%3Anotebook%3AFILE3")
        == "json:notebook:FILE3"
    )
    # Nothing to read -> None, so the caller stays on the WebSocket path rather
    # than writing into the wrong (or no) document.
    assert document_id_from_ws_url("") is None
    assert document_id_from_ws_url(None) is None
