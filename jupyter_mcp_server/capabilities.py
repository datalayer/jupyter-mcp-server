# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""What this server can do, said out loud and switchable.

A server does things a client cannot see and did not ask for. The clearest
example is the one this module was written for: when a kernel dies,
``ensure_code_sandbox_alive`` quietly starts another. Every variable the
person had is gone, the notebook's state is not what the agent believes it
is, and nothing anywhere says so — the next ``execute_cell`` simply behaves as
if the session had always been empty (#398).

That is not a bug to fix by removing the behaviour; a fresh kernel is often
exactly what somebody wants. It is a bug because it is *invisible* and *not
optional*. So it becomes a capability: named, advertised, and off unless
somebody turns it on.

The registry is filled from four places, later ones winning:

1. the defaults declared here;
2. configuration and environment (``JUPYTER_MCP_CAPABILITIES``);
3. the command line (``--capability name`` / ``--capability name=off``);
4. each extension's ``capabilities()``, so an extension that genuinely adds
   an ability declares it rather than the core guessing.

A client reads the result in ``server/discover`` under
``io.jupyter-mcp/capabilities`` and at the ``capabilities://`` resource. The
same vocabulary is used by Datalayer's hosted gateway, which reads the set off
a runtime rather than a flag — a name means one thing on both sides.

@module jupyter_mcp_server.capabilities
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)

#: The extension id capabilities are advertised under. Namespaced, because a
#: bare `capabilities` key would collide with the protocol's own.
CAPABILITIES_EXTENSION = "io.jupyter-mcp/capabilities"

#: The resource a client can read the same set from.
CAPABILITIES_RESOURCE = "capabilities://"

#: Where configuration names capabilities: a comma-separated list, each
#: `name` or `name=off`.
CAPABILITIES_ENV = "JUPYTER_MCP_CAPABILITIES"

#: Restart a dead kernel automatically, losing the session's state without
#: saying so. Off by default: a caller that has not asked for it should be
#: told its kernel died, not handed a different one wearing its name.
KERNEL_AUTO_RESTART = "kernel.auto-restart"


@dataclass(frozen=True)
class Capability:
    """One thing this server can do, and whether it is doing it."""

    name: str
    description: str
    enabled: bool = False
    #: Where the current value came from: `default`, `config`, `cli` or the
    #: extension's name. Reported so an operator can see *why* a capability
    #: is on, which is the first question asked when one surprises somebody.
    source: str = "default"
    #: Free-form detail an extension may attach — a provider name, a limit.
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        answer: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "source": self.source,
        }
        if self.params:
            answer["params"] = dict(self.params)
        return answer


#: The capabilities the core server knows about, with their defaults.
BUILT_IN: tuple[Capability, ...] = (
    Capability(
        name=KERNEL_AUTO_RESTART,
        description=(
            "Start a replacement kernel when the current one is gone. The "
            "replacement is empty: every variable, import and definition of "
            "the session is lost. Off by default, so a caller is told its "
            "kernel died rather than handed a different one silently."
        ),
        enabled=False,
    ),
)


class UnknownCapability(ValueError):
    """A name nobody declared.

    Raised rather than ignored: a misspelt `--capability kernel.autorestart`
    that is quietly dropped leaves an operator certain they enabled something
    they did not, and the behaviour they were trying to change unchanged.
    """


class CapabilityRegistry:
    """Every capability this server has, and where each value came from."""

    def __init__(self, declared: Iterable[Capability] = ()) -> None:
        self._capabilities: dict[str, Capability] = {}
        for capability in declared or BUILT_IN:
            self._capabilities[capability.name] = capability

    # -- reading ---------------------------------------------------------

    def __contains__(self, name: object) -> bool:
        return name in self._capabilities

    def enabled(self, name: str) -> bool:
        """Whether this capability is on. An unknown name is off.

        Off rather than raising, because this is what a tool calls on the
        request path: a capability nobody declared cannot have been turned
        on, and failing the call would turn a configuration mistake into an
        outage.
        """
        capability = self._capabilities.get(name)
        return bool(capability and capability.enabled)

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def all(self) -> list[Capability]:
        """Every capability, by name, so the answer is stable between calls.

        Stable because a client may cache the advertisement and compare it:
        a set that reorders itself looks like a change that is not one.
        """
        return [self._capabilities[name] for name in sorted(self._capabilities)]

    def names(self, *, enabled_only: bool = True) -> list[str]:
        return [
            capability.name
            for capability in self.all()
            if capability.enabled or not enabled_only
        ]

    # -- filling ---------------------------------------------------------

    def declare(self, capability: Capability) -> None:
        """Add a capability an extension brings with it.

        A name the core already declared is not replaced — the core's
        description and default stand — but the extension's value is applied,
        because the extension is what actually implements it.
        """
        existing = self._capabilities.get(capability.name)
        if existing is None:
            self._capabilities[capability.name] = capability
            return
        self._capabilities[capability.name] = replace(
            existing,
            enabled=capability.enabled,
            source=capability.source,
            params=capability.params or existing.params,
        )

    def set(self, name: str, enabled: bool, *, source: str = "config") -> None:
        """Turn one capability on or off."""
        capability = self._capabilities.get(name)
        if capability is None:
            known = ", ".join(sorted(self._capabilities)) or "(none)"
            raise UnknownCapability(
                f"{name!r} is not a capability of this server. Known: {known}"
            )
        self._capabilities[name] = replace(
            capability, enabled=enabled, source=source
        )

    def apply(self, values: Iterable[str], *, source: str) -> None:
        """Apply `name` / `name=off` settings, as a flag or a variable gives them."""
        for raw in values:
            name, enabled = parse_setting(raw)
            if name:
                self.set(name, enabled, source=source)

    # -- advertising -----------------------------------------------------

    def advertise(self) -> dict[str, Any]:
        """The block `server/discover` and `capabilities://` both answer with."""
        return {
            "version": "1",
            "capabilities": self.names(),
            "declared": [capability.to_dict() for capability in self.all()],
        }


def parse_setting(raw: str) -> tuple[str, bool]:
    """Read one `name`, `name=off`, `name=true` setting.

    An empty entry is skipped rather than refused, so a trailing comma in a
    configured list is not a startup failure.
    """
    text = (raw or "").strip()
    if not text:
        return "", True
    name, separator, value = text.partition("=")
    name = name.strip()
    if not separator:
        return name, True
    return name, value.strip().lower() not in ("off", "false", "0", "no", "disabled")


def from_environment(variable: str = CAPABILITIES_ENV) -> list[str]:
    """The settings named in the environment, as a list."""
    return [part for part in (os.environ.get(variable) or "").split(",") if part.strip()]


_registry: CapabilityRegistry | None = None


def get_capabilities() -> CapabilityRegistry:
    """The registry of this process, built on first use.

    Published only once the environment has been applied. Assigning first
    leaves a registry the bad entry stopped halfway through, and every call
    after the one that raised reads it back as though it were configured.
    """
    global _registry
    if _registry is None:
        registry = CapabilityRegistry()
        registry.apply(from_environment(), source="config")
        _registry = registry
    return _registry


def reset_capabilities() -> CapabilityRegistry:
    """Start again from the declared defaults. For the tests, and for a reload."""
    global _registry
    _registry = None
    return get_capabilities()


def enabled(name: str) -> bool:
    """Whether this capability is on — what a tool calls."""
    return get_capabilities().enabled(name)


def capabilities_extension() -> Any:
    """The SDK extension that advertises this registry to a client.

    Without it the registry is readable only by asking for the
    ``capabilities://`` resource — which a client has to know to look for.
    Advertised as an extension it appears in the server's own capabilities,
    where a client discovers it without being told.

    The settings are computed once, at construction, because that is when the
    SDK reads them. A capability turned on later by an extension's
    ``capabilities()`` will not appear here; the resource is the live answer
    and says so.
    """
    from mcp.server.mcpserver import Extension

    class CapabilitiesExtension(Extension):
        identifier = CAPABILITIES_EXTENSION

        def settings(self) -> dict[str, Any]:
            return get_capabilities().advertise()

    return CapabilitiesExtension()
