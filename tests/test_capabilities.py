#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What this server can do, said out loud and switchable (#400).

A server does things a client cannot see and did not ask for. The one this
was written for: when a kernel dies, the server quietly starts another. Every
variable the person had is gone, the notebook's state is not what the agent
believes it is, and nothing anywhere says so — the next execution simply
behaves as if the session had always been empty (#398).

That is not a behaviour to delete; a fresh kernel is often exactly what
somebody wants. It is a bug because it is *invisible* and *not optional*. So
it becomes a capability: named, advertised, and off unless somebody turns it
on.

Launch the tests:
```
$ pytest tests/test_capabilities.py -v
```
"""

import pytest

from jupyter_mcp_server.capabilities import (
    CAPABILITIES_ENV,
    CAPABILITIES_EXTENSION,
    CAPABILITIES_RESOURCE,
    KERNEL_AUTO_RESTART,
    Capability,
    CapabilityRegistry,
    UnknownCapability,
    enabled,
    get_capabilities,
    parse_setting,
    reset_capabilities,
)


@pytest.fixture(autouse=True)
def fresh():
    reset_capabilities()
    yield
    reset_capabilities()


class TestTheDefaults:
    def test_the_silent_kernel_replacement_is_off(self):
        """The whole point. A caller that has not asked for a replacement
        should be told its kernel died, not handed a different one wearing
        the same name."""
        assert get_capabilities().enabled(KERNEL_AUTO_RESTART) is False

    def test_every_declared_capability_says_what_it_is(self):
        """A name alone tells an operator nothing about what turning it on
        would do — and this is the surface they decide from."""
        for capability in get_capabilities().all():
            assert capability.description.strip()
            assert len(capability.description) > 40, capability.name

    def test_an_unknown_name_reads_as_off(self):
        """Off rather than raising: this is called on the request path, and
        a capability nobody declared cannot have been turned on. Failing the
        call would turn a configuration mistake into an outage."""
        assert get_capabilities().enabled("nobody.declared.this") is False

    def test_the_listing_is_stable_between_calls(self):
        """A client may cache the advertisement and compare it. A set that
        reorders itself looks like a change that is not one."""
        registry = CapabilityRegistry(
            [
                Capability(name="z.thing", description="d" * 50),
                Capability(name="a.thing", description="d" * 50),
            ]
        )
        assert [c.name for c in registry.all()] == ["a.thing", "z.thing"]


class TestSettings:
    def test_a_bare_name_turns_it_on(self):
        assert parse_setting("kernel.auto-restart") == ("kernel.auto-restart", True)

    def test_off_turns_it_off(self):
        for spelling in ("off", "false", "0", "no", "disabled", "OFF"):
            assert parse_setting(f"x={spelling}") == ("x", False)

    def test_anything_else_turns_it_on(self):
        assert parse_setting("x=on") == ("x", True)
        assert parse_setting("x=true") == ("x", True)

    def test_whitespace_is_not_part_of_the_name(self):
        assert parse_setting("  kernel.auto-restart = off ") == ("kernel.auto-restart", False)

    def test_an_empty_entry_is_skipped_not_refused(self):
        """A trailing comma in a configured list is not a startup failure."""
        assert parse_setting("") == ("", True)
        get_capabilities().apply(["", " "], source="config")

    def test_a_misspelt_name_is_refused_rather_than_dropped(self):
        """Dropped, it leaves an operator certain they changed something
        they did not, with the behaviour they meant to change unchanged."""
        with pytest.raises(UnknownCapability) as raised:
            get_capabilities().set("kernel.autorestart", True)
        # Says what the real names are, so the fix is in the error.
        assert KERNEL_AUTO_RESTART in str(raised.value)

    def test_the_environment_is_read(self, monkeypatch):
        monkeypatch.setenv(CAPABILITIES_ENV, f"{KERNEL_AUTO_RESTART}")
        reset_capabilities()
        assert get_capabilities().enabled(KERNEL_AUTO_RESTART) is True

    def test_the_environment_can_turn_one_off_again(self, monkeypatch):
        monkeypatch.setenv(CAPABILITIES_ENV, f"{KERNEL_AUTO_RESTART}=off")
        reset_capabilities()
        assert get_capabilities().enabled(KERNEL_AUTO_RESTART) is False

    def test_a_misspelt_name_in_the_environment_is_refused_on_every_call(self, monkeypatch):
        """Refused once and then cached is the drop this refuses. The caller
        after the one that raised reads back a registry the bad entry stopped
        halfway through, with nothing anywhere saying so."""
        monkeypatch.setenv(CAPABILITIES_ENV, f"kernel.autorestart,{KERNEL_AUTO_RESTART}")
        with pytest.raises(UnknownCapability):
            reset_capabilities()
        with pytest.raises(UnknownCapability):
            get_capabilities()
        with pytest.raises(UnknownCapability):
            enabled(KERNEL_AUTO_RESTART)

    def test_the_environment_is_never_applied_in_part(self, monkeypatch):
        """Which settings survive must not depend on where the bad name sits."""
        monkeypatch.setenv(CAPABILITIES_ENV, f"{KERNEL_AUTO_RESTART},kernel.autorestart")
        with pytest.raises(UnknownCapability):
            reset_capabilities()
        with pytest.raises(UnknownCapability):
            enabled(KERNEL_AUTO_RESTART)


class TestWhereAValueCameFrom:
    """The first question when a capability surprises somebody."""

    def test_a_default_says_default(self):
        assert get_capabilities().get(KERNEL_AUTO_RESTART).source == "default"

    def test_a_flag_says_cli(self):
        get_capabilities().apply([KERNEL_AUTO_RESTART], source="cli")
        assert get_capabilities().get(KERNEL_AUTO_RESTART).source == "cli"

    def test_the_command_line_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv(CAPABILITIES_ENV, f"{KERNEL_AUTO_RESTART}=off")
        reset_capabilities()
        get_capabilities().apply([KERNEL_AUTO_RESTART], source="cli")
        assert get_capabilities().enabled(KERNEL_AUTO_RESTART) is True


class TestExtensionsDeclareTheirOwn:
    def test_an_extension_adds_a_capability(self):
        registry = CapabilityRegistry()
        registry.declare(
            Capability(
                name="sandboxes.snapshot",
                description="d" * 50,
                enabled=True,
                source="jupyter-mcp-sandboxes",
            )
        )
        assert registry.enabled("sandboxes.snapshot")
        assert registry.get("sandboxes.snapshot").source == "jupyter-mcp-sandboxes"

    def test_an_extension_may_turn_a_core_capability_on(self):
        """The extension is what implements it, so its value wins — but the
        core's description stands, so the name still means one thing."""
        registry = CapabilityRegistry()
        core = registry.get(KERNEL_AUTO_RESTART).description
        registry.declare(
            Capability(name=KERNEL_AUTO_RESTART, description="something else", enabled=True)
        )
        assert registry.enabled(KERNEL_AUTO_RESTART)
        assert registry.get(KERNEL_AUTO_RESTART).description == core

    def test_one_broken_extension_does_not_cost_the_others_theirs(self):
        from jupyter_mcp_server.extensions import ExtensionManager, JupyterMCPExtension

        class Broken(JupyterMCPExtension):
            def capabilities(self):
                raise RuntimeError("this plugin is having a bad day")

        class Fine(JupyterMCPExtension):
            def capabilities(self):
                return [Capability(name="fine.thing", description="d" * 50, enabled=True)]

        manager = ExtensionManager()
        manager._extensions = {"broken": Broken(), "fine": Fine()}
        registry = CapabilityRegistry()
        manager.collect_capabilities(registry)
        assert registry.enabled("fine.thing")

    def test_something_that_is_not_a_capability_is_logged_not_raised(self):
        from jupyter_mcp_server.extensions import ExtensionManager, JupyterMCPExtension

        class Confused(JupyterMCPExtension):
            def capabilities(self):
                return ["not a capability"]

        manager = ExtensionManager()
        manager._extensions = {"confused": Confused()}
        registry = CapabilityRegistry()
        manager.collect_capabilities(registry)
        assert registry.names() == []


class TestAdvertising:
    def test_the_block_lists_what_is_on(self):
        get_capabilities().apply([KERNEL_AUTO_RESTART], source="cli")
        block = get_capabilities().advertise()
        assert block["capabilities"] == [KERNEL_AUTO_RESTART]

    def test_the_block_also_says_what_exists_but_is_off(self):
        """A client that only saw what is *on* could not tell a capability
        this server does not have from one it has and is not using — and the
        answer decides whether asking an operator is worth it."""
        block = get_capabilities().advertise()
        assert block["capabilities"] == []
        assert [entry["name"] for entry in block["declared"]] == [KERNEL_AUTO_RESTART]
        assert block["declared"][0]["enabled"] is False

    def test_the_registry_is_advertised_on_the_server(self):
        """Not only readable at `capabilities://`, which a client has to know
        to ask for. Advertised as an SDK extension it appears in the server's
        own capabilities, where a client finds it without being told.

        This is the gap a review caught: the extension id existed, the
        docstrings said it was advertised, and nothing advertised it — so the
        only way to the registry was a resource nobody would look for."""
        from jupyter_mcp_server.server import mcp

        advertised = {extension.identifier for extension in mcp._extensions}
        assert CAPABILITIES_EXTENSION in advertised, sorted(advertised)

    def test_what_is_advertised_is_what_the_registry_says(self):
        """Two sources for one answer would drift, and the drifting one would
        be the one a client reads."""
        from jupyter_mcp_server.capabilities import capabilities_extension

        assert capabilities_extension().settings() == get_capabilities().advertise()

    def test_the_extension_id_is_namespaced(self):
        """A bare `capabilities` key would collide with the protocol's own."""
        assert "/" in CAPABILITIES_EXTENSION

    def test_the_resource_answers_the_same_block(self):
        from jupyter_mcp_server.server import capabilities_resource

        answer = capabilities_resource()
        assert answer["declared"]
        assert set(answer) == set(get_capabilities().advertise())

    def test_the_resource_has_a_uri(self):
        assert CAPABILITIES_RESOURCE.endswith("://")


class TestExtensionsRegisterAfterConfiguration:
    """When an extension gets to contribute its tools, and what it knows by then.

    Registration used to happen at module scope. That is earlier than it
    looks: the CLI imports the server module *in order to start it*, so
    extensions registered while the command line was still being parsed and
    before `set_config` had been called. An extension asking "what am I
    pointed at?" was told the default however the server had been invoked —
    and the only place the intent existed yet was `sys.argv`, which the
    Datalayer spaces extension had to go and read for itself, with a comment
    saying it was waiting on exactly this change.
    """

    def test_importing_the_server_does_not_register_anything(self):
        """The bug, stated as a property. If this ever passes again by
        accident, the extension is back to guessing from argv."""
        import subprocess
        import sys

        answer = subprocess.run(
            [
                sys.executable,
                "-c",
                "import jupyter_mcp_server.server as s;"
                "print(s.extension_manager._tools_registered)",
            ],
            capture_output=True,
            text=True,
        )
        assert answer.stdout.strip().endswith("False"), answer.stdout

    def test_registering_is_idempotent(self):
        """Every entry point calls it — the CLI after configuring, the
        Jupyter Server extension, the tool listing — and none of them has to
        know whether another got there first."""
        from jupyter_mcp_server.extensions import ExtensionManager, JupyterMCPExtension

        class Counting(JupyterMCPExtension):
            def __init__(self):
                self.times = 0

            def manifest(self):
                from reactor import PluginManifest

                return PluginManifest(name="counting", version="1.0.0")

            def register_tools(self, mcp):
                self.times += 1

        manager = ExtensionManager()
        counting = Counting()
        manager._extensions = {"counting": counting}
        manager._discovered = True
        manager.register_tools(object(), once=True)
        manager.register_tools(object(), once=True)
        assert counting.times == 1

    def test_the_cli_registers_after_it_has_configured(self):
        """The fix itself, and the order is the whole of it.

        `do_start` imports the server module (which no longer registers
        anything), then calls `set_config`, and only then lets extensions
        register. Register before `set_config` and every extension is back to
        being told the default; do not register at all and their tools are
        missing entirely.
        """
        import inspect

        from jupyter_mcp_server.utils import do_start

        source = inspect.getsource(do_start)
        assert "register_extension_tools()" in source, "the CLI never registers them"
        assert source.index("config = set_config(") < source.index(
            "register_extension_tools()"
        ), "extensions register before the server is configured"

    def test_asking_for_the_tool_list_registers_them(self):
        """Last line of defence: whoever asks gets a complete list, whichever
        entry point started the process and whether or not it remembered."""
        import inspect

        from jupyter_mcp_server.server import get_registered_tools

        assert "register_extension_tools()" in inspect.getsource(get_registered_tools)


class TestExtensionsRegisterInAOrderTheyCanRelyOn:
    """Registration is not independent, so the order cannot be accidental.

    An extension may replace a tool another registered — the hosted gateway's
    sandboxes extension narrows the scaffold's `launch_sandbox` — and the SDK
    keeps the *original* when a name is registered twice. So a replacement
    that runs first silently does nothing.

    `importlib.metadata` returns entry points in whatever order the
    installation produced. It varies between machines and between a wheel and
    an editable install, which is the worst kind of ordering bug: it works
    where it was written.
    """

    def test_they_are_registered_in_name_order(self):
        import inspect

        from jupyter_mcp_server.extensions import ExtensionManager

        source = inspect.getsource(ExtensionManager.discover)
        assert "sorted(" in source, "entry points are registered in arbitrary order"

    def test_the_order_is_the_one_extensions_are_told_about(self, monkeypatch):
        """Sorted by name, so an extension wanting to run after another can
        be named to. Proven by driving the manager rather than by reading it."""
        from jupyter_mcp_server.extensions import ExtensionManager

        registered: list[str] = []

        class _Point:
            def __init__(self, name):
                self.name = name

            def load(self):
                def factory():
                    registered.append(self.name)
                    return _Noop()

                return factory

        class _Noop:
            def manifest(self):
                from reactor import PluginManifest

                return PluginManifest(name=registered[-1], version="0.0.1")

        manager = ExtensionManager()
        monkeypatch.setattr(
            "jupyter_mcp_server.extensions.metadata.entry_points",
            lambda group=None: [_Point("zebra"), _Point("alpha"), _Point("middle")],
        )
        manager.discover()
        assert registered == ["alpha", "middle", "zebra"]
