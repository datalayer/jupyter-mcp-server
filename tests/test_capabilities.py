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
