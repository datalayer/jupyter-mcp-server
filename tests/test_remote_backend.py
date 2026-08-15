# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The backend that talks to a Jupyter server over the network.

`LocalBackend` drives the managers of a server this process is embedded in.
This one addresses a server somewhere else, and the two halves of "somewhere
else" need not be the same machine: documents come from one URL, execution
from another.

Every method here was `raise NotImplementedError("To be refactored from
server.py")` until recently, so these tests exist mostly to say that it now
does something, and does it against the right server.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jupyter_mcp_server.jupyter_extension.backends.base import Backend
from jupyter_mcp_server.jupyter_extension.backends.remote_backend import (
    RemoteBackend,
    _text,
)


@pytest.fixture
def backend() -> RemoteBackend:
    return RemoteBackend(
        document_url="http://documents.test",
        document_token="doc-token",
        code_sandbox_url="http://sandbox.test",
        code_sandbox_token="sbx-token",
    )


class TestItHonoursTheContract:
    def test_every_method_of_the_contract_is_present(self):
        missing = [
            name
            for name in dir(Backend)
            if not name.startswith("_") and not hasattr(RemoteBackend, name)
        ]
        assert missing == []

    def test_nothing_is_left_saying_it_is_unimplemented(self):
        import inspect

        # The whole class used to be `raise NotImplementedError("To be
        # refactored from server.py")`. What remains of that phrasing would be
        # a method nobody finished.
        assert "To be refactored" not in inspect.getsource(RemoteBackend)


class TestTheTwoServersStaySeparate:
    """Documents and execution can live on different machines.

    Reading a notebook from the server that happens to run the code — or the
    other way round — is the failure this split exists to prevent, and it is
    silent when both happen to be the same host in development.
    """

    def test_documents_go_to_the_document_server(self, backend):
        with patch(
            "jupyter_mcp_server.jupyter_extension.backends.remote_backend.JupyterServerClient"
        ) as client:
            backend._documents()
        client.assert_called_once_with(
            base_url="http://documents.test", token="doc-token"
        )

    def test_kernels_go_to_the_execution_server(self, backend):
        with patch(
            "jupyter_mcp_server.jupyter_extension.backends.remote_backend.JupyterServerClient"
        ) as client:
            backend._sandbox()
        client.assert_called_once_with(
            base_url="http://sandbox.test", token="sbx-token"
        )


class TestNotebookOperations:
    @pytest.mark.asyncio
    async def test_a_missing_notebook_is_absent_rather_than_an_error(self, backend):
        # Callers ask "is it there?" and must get an answer, not an exception
        # they have to interpret.
        with patch.object(backend, "_documents") as documents:
            documents.return_value.contents.get.side_effect = RuntimeError("404")
            assert await backend.notebook_exists("nope.ipynb") is False

    @pytest.mark.asyncio
    async def test_an_existing_notebook_is_present(self, backend):
        with patch.object(backend, "_documents") as documents:
            documents.return_value.contents.get.return_value = {"type": "notebook"}
            assert await backend.notebook_exists("there.ipynb") is True

    @pytest.mark.asyncio
    async def test_listing_descends_into_directories(self, backend):
        """A notebook two folders down is still one of your notebooks."""
        tree = {
            "": [
                MagicMock(path="top.ipynb", type="notebook"),
                MagicMock(path="sub", type="directory"),
            ],
            "sub": [MagicMock(path="sub/deep.ipynb", type="notebook")],
        }
        with patch.object(backend, "_documents") as documents:
            documents.return_value.contents.list_directory.side_effect = (
                lambda path: tree[path]
            )
            assert await backend.list_notebooks() == ["sub/deep.ipynb", "top.ipynb"]

    @pytest.mark.asyncio
    async def test_only_notebooks_are_listed(self, backend):
        with patch.object(backend, "_documents") as documents:
            documents.return_value.contents.list_directory.return_value = [
                MagicMock(path="notes.txt", type="file"),
                MagicMock(path="real.ipynb", type="notebook"),
            ]
            assert await backend.list_notebooks() == ["real.ipynb"]


class TestKernelQueries:
    @pytest.mark.asyncio
    async def test_kernels_are_reported_with_their_state(self, backend):
        kernel = MagicMock(id="k1", name="python3", execution_state="idle", connections=2)
        with patch.object(backend, "_sandbox") as sandbox:
            sandbox.return_value.kernels.list_kernels.return_value = [kernel]
            listed = await backend.list_kernels()
        assert listed[0]["id"] == "k1"
        assert listed[0]["execution_state"] == "idle"

    @pytest.mark.asyncio
    async def test_a_missing_kernel_is_absent_rather_than_an_error(self, backend):
        with patch.object(backend, "_sandbox") as sandbox:
            sandbox.return_value.kernels.get_kernel.side_effect = RuntimeError("410")
            assert await backend.kernel_exists("gone") is False


class TestExecutionIsNotTheBackends:
    """Starting and running code belongs to the sandbox layer.

    Only that layer knows which variant a deployment runs — a Jupyter kernel, a
    Datalayer runtime, something else. Implementing it here would rebuild the
    coupling the sandbox extension exists to remove, so these refuse loudly
    rather than half-working.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method, args",
        [
            ("get_or_create_kernel", ("nb.ipynb",)),
            ("execute_cell", ("nb.ipynb", 0, "k1")),
            ("interrupt_kernel", ("k1",)),
            ("restart_kernel", ("k1",)),
            ("shutdown_kernel", ("k1",)),
        ],
    )
    async def test_it_says_whose_job_it_is(self, backend, method, args):
        with pytest.raises(NotImplementedError) as caught:
            await getattr(backend, method)(*args)
        assert "sandbox layer" in str(caught.value)


class TestCellSource:
    def test_a_string_is_left_alone(self):
        assert _text("print(1)") == "print(1)"

    def test_lines_are_joined_without_being_re_separated(self):
        # nbformat stores source as a list of lines that already carry their
        # newlines; adding more would double every line break.
        assert _text(["a\n", "b\n"]) == "a\nb\n"
