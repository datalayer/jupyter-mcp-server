# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The legacy `create_kernel` hook is announced, never silently skipped.

A sandboxes extension built before the factory hook was renamed defines
`create_kernel` and nothing else; this server only calls
`create_code_sandbox`, so without the warning the mismatch shows up as an
execution hanging on a Jupyter kernel that is not there — the exact incident
that motivated the check.
"""

import logging
from types import SimpleNamespace

from jupyter_mcp_server.extensions import ExtensionManager, JupyterMCPExtension


class LegacyExtension(JupyterMCPExtension):
    """The shape of a pre-rename extension: the old hook, not the new one."""

    def create_kernel(self, config, log):
        raise AssertionError("the server must not call the legacy hook")


class CurrentExtension(JupyterMCPExtension):
    """A post-rename extension that overrides the factory hook."""

    def __init__(self):
        self.asked = False

    def create_code_sandbox(self, config, logger):
        self.asked = True
        return None


def _manager_with(name, extension):
    manager = ExtensionManager()
    # Injected directly: discovery reads entry points of the environment,
    # which is exactly what a unit test must not depend on.
    manager._discovered = True
    manager._extensions[name] = extension
    return manager


def test_a_legacy_extension_is_warned_about(caplog):
    manager = _manager_with("oldster", LegacyExtension())
    log = logging.getLogger("test-factory")
    with caplog.at_level(logging.WARNING, logger="test-factory"):
        result = manager.create_code_sandbox(SimpleNamespace(), log)
    assert result is None
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "create_kernel" in record.message
    ]
    assert len(warnings) == 1
    assert "oldster" in warnings[0].getMessage()
    assert "Upgrade" in warnings[0].message


def test_a_current_extension_is_not_warned_about(caplog):
    extension = CurrentExtension()
    manager = _manager_with("current", extension)
    log = logging.getLogger("test-factory")
    with caplog.at_level(logging.WARNING, logger="test-factory"):
        manager.create_code_sandbox(SimpleNamespace(), log)
    assert extension.asked
    assert not [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]


def test_a_current_extension_with_a_leftover_create_kernel_is_trusted(caplog):
    """Overriding the new hook is what counts, whatever else the class keeps."""

    class Both(CurrentExtension):
        def create_kernel(self, config, log):
            return None

    extension = Both()
    manager = _manager_with("both", extension)
    log = logging.getLogger("test-factory")
    with caplog.at_level(logging.WARNING, logger="test-factory"):
        manager.create_code_sandbox(SimpleNamespace(), log)
    assert extension.asked
    assert not [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
