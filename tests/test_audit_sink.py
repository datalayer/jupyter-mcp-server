#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Where a deployment sends its record of who asked for what.

This server has no opinion about auditing, and shouldn't: a laptop needs none,
a hosted deployment needs a durable queryable one, a bank needs it in a SIEM.
So there is a seam — `JUPYTER_MCP_AUDIT_SINK_CLASS` names a class and every
tool call reaches it through the hooks that already exist.

Two rules, and both are about not making auditing worse than none:

- a sink that fails never fails the call it was describing. An audit outage
  that took the server down with it would be an outage caused by the thing
  meant to make outages explicable.
- a sink that fails says so at ERROR, every time. A silently dropped record is
  worse than a missing one, because it looks like nothing happened.

And a third, at the other end: a name that cannot be loaded stops the server.
An operator who configured auditing and got a server running without it has
the worst of both — they believe calls are recorded, and they are not.

```
$ pytest tests/test_audit_sink.py -v
```
"""

import asyncio
import logging

import pytest

from jupyter_mcp_server import audit
from jupyter_mcp_server.audit import (
    AUDIT_SINK_CLASS_ENV,
    load_sink_class,
    register_audit_sink,
    resolve_audit_sink,
)
from jupyter_mcp_server.hooks import HookEvent, HookRegistry


class RecordingSink:
    """A sink that keeps what it was told."""

    seen: list = []

    def __init__(self):
        RecordingSink.seen = []

    async def on_event(self, event, **details):
        RecordingSink.seen.append((event, details))


class FailingSink:
    async def on_event(self, event, **details):
        raise RuntimeError("the SIEM is down")


class NotASink:
    """No `on_event`. A configuration mistake worth naming."""


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(AUDIT_SINK_CLASS_ENV, raising=False)
    HookRegistry.reset()
    yield
    HookRegistry.reset()


class TestConfiguring:
    def test_no_sink_is_configured_by_default(self):
        """A laptop needs none, and paying for one it did not ask for is a
        cost with no benefit."""
        assert resolve_audit_sink() is None
        assert register_audit_sink() is None

    def test_a_named_sink_is_built_and_registered(self, monkeypatch):
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:RecordingSink")
        assert register_audit_sink() is not None
        assert len(HookRegistry.get_instance()._handlers) == 1

    def test_the_dotted_spelling_works_too(self, monkeypatch):
        """The same spelling the token verifier takes, so a deployment
        configuring both does not have to remember two conventions."""
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}.RecordingSink")
        assert resolve_audit_sink() is not None

    def test_a_name_that_cannot_be_imported_stops_the_server(self, monkeypatch):
        """Rather than running without the auditing somebody configured."""
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, "no.such.module:Sink")
        with pytest.raises(RuntimeError, match=AUDIT_SINK_CLASS_ENV):
            resolve_audit_sink()

    def test_something_that_is_not_a_sink_is_refused_by_name(self, monkeypatch):
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:NotASink")
        with pytest.raises(RuntimeError, match="on_event"):
            resolve_audit_sink()

    def test_a_malformed_path_says_what_the_shape_is(self):
        with pytest.raises(ValueError, match="package.module:ClassName"):
            load_sink_class("NoModuleHere")


class TestTheServerActuallyRegistersIt:
    def test_startup_registers_the_configured_sink(self):
        """The seam is only real if something walks through it. Without this
        call a deployment configures a sink, sees no error, and records
        nothing."""
        import inspect

        from jupyter_mcp_server.utils import do_start

        assert "register_audit_sink()" in inspect.getsource(do_start)

    def test_it_is_registered_after_the_configuration_is_set(self):
        """A sink built before `set_config` would be built against the
        defaults, whatever the server was actually told."""
        import inspect

        from jupyter_mcp_server.utils import do_start

        source = inspect.getsource(do_start)
        assert source.index("config = set_config(") < source.index("register_audit_sink()")


class TestWhatASinkSees:
    def test_every_tool_call_reaches_it_before_and_after(self, monkeypatch):
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:RecordingSink")
        register_audit_sink()
        registry = HookRegistry.get_instance()

        async def scenario():
            context = await registry.fire(
                HookEvent.BEFORE_TOOL_CALL, tool_name="read_cell", arguments={"cell_index": 1}
            )
            await registry.fire(
                HookEvent.AFTER_TOOL_CALL, tool_name="read_cell", context=context
            )

        asyncio.run(scenario())
        events = [event for event, _ in RecordingSink.seen]
        assert events == [HookEvent.BEFORE_TOOL_CALL, HookEvent.AFTER_TOOL_CALL]

    def test_the_two_halves_share_a_context(self, monkeypatch):
        """Which is where a duration, or the id assigned to the call, goes:
        a sink cannot pair a before with an after otherwise."""
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:RecordingSink")
        register_audit_sink()
        registry = HookRegistry.get_instance()

        async def scenario():
            context = await registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="read_cell")
            context["call_id"] = "abc"
            await registry.fire(
                HookEvent.AFTER_TOOL_CALL, tool_name="read_cell", context=context
            )

        asyncio.run(scenario())
        assert RecordingSink.seen[-1][1]["context"]["call_id"] == "abc"


class TestASinkNeverBreaksTheCall:
    def test_a_failing_sink_does_not_raise(self, monkeypatch):
        """An audit outage that took the server down with it would be an
        outage caused by the thing meant to make outages explicable."""
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:FailingSink")
        register_audit_sink()
        registry = HookRegistry.get_instance()
        asyncio.run(registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="read_cell"))

    def test_a_failing_sink_is_logged_at_error(self, monkeypatch, caplog):
        """A silently dropped audit record is worse than a missing one: it
        looks exactly like nothing having happened."""
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, f"{__name__}:FailingSink")
        register_audit_sink()
        registry = HookRegistry.get_instance()
        with caplog.at_level(logging.ERROR):
            asyncio.run(registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="read_cell"))
        assert any(record.levelno >= logging.ERROR for record in caplog.records)
        assert "not recorded" in caplog.text

    def test_a_sink_never_propagates_its_errors(self, monkeypatch):
        """Whatever the sink says about itself. `propagate_errors` is the
        registry's escape hatch for handlers that must be fatal, and a sink
        is exactly the handler that must not be."""

        class Insistent(FailingSink):
            propagate_errors = True

        monkeypatch.setattr(audit, "load_sink_class", lambda _path: Insistent)
        monkeypatch.setenv(AUDIT_SINK_CLASS_ENV, "anything:Insistent")
        sink = resolve_audit_sink()
        assert sink.propagate_errors is False


class TestTheProtocolLayerIsTracedOnce:
    def test_the_sdk_installs_its_own_middleware(self):
        """mcp 2 adds `OpenTelemetryMiddleware` by default, so this server
        passes none."""
        from jupyter_mcp_server.server import mcp

        names = [type(item).__name__ for item in mcp.middleware]
        assert "OpenTelemetryMiddleware" in names

    def test_it_is_installed_exactly_once(self):
        """Passing one as well appends a second instance and every message is
        traced twice — which reads as double the traffic on every dashboard
        built from it."""
        from jupyter_mcp_server.server import mcp

        names = [type(item).__name__ for item in mcp.middleware]
        assert names.count("OpenTelemetryMiddleware") == 1, names
