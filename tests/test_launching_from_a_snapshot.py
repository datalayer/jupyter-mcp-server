# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Starting a sandbox from a saved state, and the one variant that can.

`code_sandboxes` has taken a `snapshot_name` on the Datalayer sandbox since
before this extension existed; the extension simply never passed it, so a
saved state was reachable from the library and not from a tool. These are the
two things that go wrong when a launch argument is threaded through three
layers: it arrives nowhere, or it arrives everywhere.

Launch the tests:
```
$ pytest tests/test_launching_from_a_snapshot.py -v
```
"""

from __future__ import annotations

from typing import Any

import pytest

from jupyter_mcp_sandboxes.manager import CodeSandboxManager


class _Sandbox:
    """Enough of a sandbox to be launched and serialized."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.config = type("Config", (), {"environment": None, "gpu": None})()
        self.info = type("Info", (), {"variant": kwargs.get("variant")})()
        self.id = "sbx-1"

    def start(self) -> None:
        return None


@pytest.fixture()
def created(monkeypatch):
    """Every `CodeSandboxClient.create` call the manager made."""
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> _Sandbox:
        calls.append(kwargs)
        return _Sandbox(**kwargs)

    monkeypatch.setattr(
        "jupyter_mcp_sandboxes.manager.CodeSandboxClient",
        type("Client", (), {"create": staticmethod(create)}),
    )
    return calls


def test_a_datalayer_launch_carries_the_snapshot_to_the_library(created):
    """The whole point: the name reaches the constructor that reads it."""
    CodeSandboxManager().launch(
        sandbox_name="restored",
        variant="datalayer",
        timeout=60.0,
        snapshot_name="before-the-training-run",
    )
    assert created[0]["snapshot_name"] == "before-the-training-run"


def test_a_launch_without_one_does_not_mention_it(created):
    """Absent, not None.

    `snapshot_name=None` reaches the constructor as an argument that was
    given, and a variant reading "was a snapshot asked for" by presence
    rather than by truthiness would answer yes.
    """
    CodeSandboxManager().launch(sandbox_name="fresh", variant="datalayer", timeout=60.0)
    assert "snapshot_name" not in created[0]


@pytest.mark.parametrize("variant", ["eval", "modal", "e2b", "docker"])
def test_a_variant_without_snapshots_refuses_rather_than_starting_empty(created, variant):
    """The failure this prevents is silent, which is why it is a refusal.

    Passing the argument on to a variant that does not know it is a
    `TypeError` from a constructor two packages away; dropping it is worse —
    the caller asked to continue from a saved state, got an empty sandbox
    that looks identical, and finds out when the variables are not there.
    """
    with pytest.raises(ValueError) as refusal:
        CodeSandboxManager().launch(
            sandbox_name="restored",
            variant=variant,
            timeout=60.0,
            snapshot_name="before-the-training-run",
        )
    assert variant in str(refusal.value)
    assert not created, "a refused launch must not have created a sandbox"
