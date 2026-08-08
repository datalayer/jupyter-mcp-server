# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for streaming execution routing in CodeSandboxManager."""

from __future__ import annotations

from types import SimpleNamespace

from jupyter_mcp_sandboxes.manager import CodeSandboxManager


class _FakeStreamingSandbox:
    """Client that streams events, like CodeSandboxClient does."""

    def execute_code_streaming(self, code: str, timeout: int):
        assert code == "print('hi')"
        assert timeout == 10
        yield SimpleNamespace(line="[kaggle] submitted job: me/demo", error=False)
        yield SimpleNamespace(line="[kaggle] status: RUNNING", error=False)
        yield SimpleNamespace(
            data={"text/plain": "42"},
            is_main_result=True,
            extra={"meta": "value"},
        )


class _FakeFallbackSandbox:
    """Client whose stream is empty, so execute() supplies the outputs.

    ``CodeSandboxClient.execute`` returns a Jupyter-shaped reply dict, not an
    ExecutionResult.
    """

    def execute_code_streaming(self, code: str, timeout: int):
        assert code == "print('hi')"
        assert timeout == 10
        return iter(())

    def execute(self, code: str, timeout: int):
        assert code == "print('hi')"
        assert timeout == 10
        return {
            "execution_count": 1,
            "status": "ok",
            "outputs": [
                {"output_type": "stream", "name": "stdout", "text": "fallback\n"},
            ],
        }


def test_execute_on_active_prefers_streaming_path():
    manager = CodeSandboxManager()
    manager._active_name = "k1"
    manager._sandboxes["k1"] = _FakeStreamingSandbox()

    outputs = manager.execute_on_active("print('hi')", timeout=10)

    text = "\n".join(str(item) for item in outputs)
    assert "submitted job" in text
    assert "status: RUNNING" in text
    assert "42" in text


def test_execute_on_active_falls_back_to_execute_when_stream_is_empty():
    manager = CodeSandboxManager()
    manager._active_name = "k1"
    manager._sandboxes["k1"] = _FakeFallbackSandbox()

    outputs = manager.execute_on_active("print('hi')", timeout=10)

    text = "\n".join(str(item) for item in outputs)
    assert "fallback" in text
