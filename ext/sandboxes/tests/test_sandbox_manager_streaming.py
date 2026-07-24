# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for streaming execution routing in SandboxRuntimeManager."""

from __future__ import annotations

from types import SimpleNamespace

from jupyter_mcp_sandboxes.manager import SandboxRuntimeManager


class _FakeStreamingSandbox:
    def run_code_streaming(self, code: str, timeout: int):
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
    def run_code(self, code: str, timeout: int):
        assert code == "print('hi')"
        assert timeout == 10
        return SimpleNamespace(
            execution_count=1,
            code_error=None,
            logs=SimpleNamespace(
                stdout=[SimpleNamespace(line="fallback")],
                stderr=[],
            ),
            results=[],
        )


def test_execute_on_active_prefers_streaming_path():
    manager = SandboxRuntimeManager()
    manager._active_name = "k1"
    manager._sandboxes["k1"] = _FakeStreamingSandbox()

    outputs = manager.execute_on_active("print('hi')", timeout=10)

    text = "\n".join(str(item) for item in outputs)
    assert "submitted job" in text
    assert "status: RUNNING" in text
    assert "42" in text


def test_execute_on_active_falls_back_to_run_code_when_no_streaming():
    manager = SandboxRuntimeManager()
    manager._active_name = "k1"
    manager._sandboxes["k1"] = _FakeFallbackSandbox()

    outputs = manager.execute_on_active("print('hi')", timeout=10)

    text = "\n".join(str(item) for item in outputs)
    assert "fallback" in text
