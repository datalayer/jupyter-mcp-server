# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The Jupyter MCP Server spaces extension.

Datalayer keeps notebooks in **spaces**, addressed by uid. It has no
filesystem and no kernels API, so the tools that assume a Jupyter server —
``list_files``, ``list_kernels``, ``connect_to_jupyter`` — have nothing to
answer and return the platform router's 404. An agent handed a tool that
always fails keeps trying it and then invents explanations, which is how a
hosted session ends up offering to connect to a Jupyter on your laptop.

So this extension does two things when the document provider is
``datalayer``:

- **replaces** ``list_notebooks`` with one that lists the notebooks in the
  user's spaces, and teaches ``use_notebook`` to accept a name or a uid;
- **removes** the tools that cannot work, so they are never offered.

Both matter for how an agent behaves. Keeping the upstream names is
deliberate: an agent asked to list notebooks calls ``list_notebooks``, and a
differently named tool would be found second, after the empty one has already
answered "you have none".

@module jupyter_mcp_spaces.extension
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field
from reactor import PluginCompatibility, PluginManifest

from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.extensions import JupyterMCPExtension
from jupyter_mcp_spaces import spaces


def _version() -> str:
    """The version of this package, from its metadata.

    Read rather than restated: a number written here as well as in
    `pyproject.toml` is one that will disagree with it, and the manifest is
    what a reader consults to find out which build is loaded.
    """
    try:
        from importlib.metadata import version

        return version("jupyter-mcp-spaces")
    except Exception:
        return "0.0.0.dev0"


logger = logging.getLogger(__name__)

#: The tools that assume a Jupyter server, and so cannot be answered by a
#: platform that has spaces instead of files and runtimes instead of kernels.
JUPYTER_ONLY_TOOLS = (
    "list_files",
    "list_kernels",
    "connect_to_jupyter",
)


class SpacesExtension(JupyterMCPExtension):
    """Datalayer spaces as the notebooks an agent can reach."""

    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="jupyter-mcp-spaces",
            version=_version(),
            description=(
                "List and open the notebooks of a Datalayer space, in place of "
                "the filesystem tools of a Jupyter server."
            ),
            author="Datalayer",
            tags=["datalayer", "spaces", "notebooks"],
            compatibility=PluginCompatibility(api_version="v1"),
        )

    def register_tools(self, mcp: Any) -> None:
        if not _serving_datalayer():
            # Pointed at a Jupyter server: its own tools are the right ones,
            # and replacing them would break the ordinary case.
            logger.debug("Document provider is not datalayer; spaces tools not registered")
            return

        _remove(mcp, JUPYTER_ONLY_TOOLS)
        # Removed before registering, not merely re-declared: MCPServer warns
        # "Tool already exists" and *keeps the original*, so a replacement
        # registered on top of a live name silently does nothing.
        _remove(mcp, ("list_notebooks",))

        @mcp.tool(
            annotations=ToolAnnotations(title="List Spaces", readOnlyHint=True),
        )
        async def list_spaces() -> list[dict[str, Any]]:
            """List the Datalayer spaces you can reach.

            A space holds notebooks, documents and datasets. Most people have
            one; teams have several.
            """
            try:
                return await spaces.list_spaces()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

        @mcp.tool(
            annotations=ToolAnnotations(title="List Notebooks", readOnlyHint=True),
        )
        async def list_notebooks() -> list[dict[str, Any]]:
            """List the notebooks in your Datalayer spaces.

            Returns each notebook's name, its uid, and the space it belongs
            to. Pass a name or a uid to `use_notebook` to open one.
            """
            try:
                return await spaces.list_notebooks()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

        @mcp.tool(
            annotations=ToolAnnotations(title="Find Notebook", readOnlyHint=True),
        )
        async def find_notebook(
            name: Annotated[
                str,
                Field(description="A notebook name, part of one, or a uid"),
            ],
        ) -> dict[str, Any]:
            """Find which notebook a name refers to, before opening it.

            Answers with one match, or with the candidates when a name is
            ambiguous — so the right notebook is chosen rather than guessed.
            """
            try:
                notebooks = await spaces.list_notebooks()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

            matches = spaces.resolve(notebooks, name)
            if not matches:
                return {
                    "found": False,
                    "message": (
                        f"No notebook of yours matches '{name}'. "
                        "Use list_notebooks to see them all."
                    ),
                }
            if len(matches) > 1:
                return {
                    "found": False,
                    "ambiguous": True,
                    "candidates": matches,
                    "message": (
                        f"{len(matches)} notebooks match '{name}'. "
                        "Ask which one is meant, then use its uid."
                    ),
                }
            return {"found": True, "notebook": matches[0]}

        _wrap_use_notebook(mcp)

        logger.info(
            "Datalayer spaces tools registered; %s hidden",
            ", ".join(JUPYTER_ONLY_TOOLS),
        )


def _serving_datalayer() -> bool:
    """Whether this server is pointed at Datalayer rather than a Jupyter.

    Asked at *import* time, which is earlier than it looks. The open source
    server registers extensions at module scope, so this runs while the CLI is
    still parsing its arguments and before ``set_config`` has been called —
    meaning the configuration says ``jupyter`` however the server was invoked.
    Reading only the configuration therefore always answers "no", and the
    extension silently does nothing.

    So three sources, in the order they become trustworthy:

    1. the configuration, when something has already set it — programmatic
       callers and tests;
    2. ``DOCUMENT_PROVIDER`` in the environment, which a deployment controls;
    3. the command line, which is what the CLI is about to configure from.

    Reading ``sys.argv`` is not elegant. It is, at this point in startup, the
    only place the intent exists. The proper fix belongs upstream — register
    extensions after configuration rather than at import — and when that lands
    the first source alone will do.
    """
    # Any of them naming Datalayer is enough, rather than the first that
    # answers winning. The configuration is never silent — it defaults to
    # "jupyter" — so treating it as authoritative here would mean the later
    # sources are never reached, and this would answer "no" at import however
    # the server was started.
    try:
        configured = (get_config().document_provider or "").lower()
    except Exception:
        configured = ""
    sources = (
        configured,
        (os.environ.get("DOCUMENT_PROVIDER") or "").lower(),
        _provider_from_argv(),
    )
    return "datalayer" in sources


def _provider_from_argv() -> str:
    """The provider named on the command line, if one was.

    Accepts ``--document-provider datalayer`` and
    ``--document-provider=datalayer``, and the short form the CLI also takes.
    """
    argv = sys.argv[1:]
    for index, argument in enumerate(argv):
        if argument.startswith("--document-provider="):
            return argument.split("=", 1)[1].strip().lower()
        if argument in ("--document-provider", "-dp") and index + 1 < len(argv):
            return argv[index + 1].strip().lower()
    return ""


def _remove(mcp: Any, names: tuple[str, ...]) -> None:
    """Take tools off the list, tolerating ones that were never on it.

    A missing tool raises rather than passing quietly, and an upstream release
    that renames one must not stop this server from starting.
    """
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:  # pragma: no cover - defensive
        logger.warning("No tool manager; leaving the tool list alone")
        return
    for name in names:
        try:
            manager.remove_tool(name)
            logger.debug("Removed tool [%s]", name)
        except Exception:
            logger.debug("Tool [%s] was not registered", name)


def _wrap_use_notebook(mcp: Any) -> None:
    """Let `use_notebook` be given a name, not only a uid.

    Datalayer addresses notebooks by uid, and a uid is not something a person
    says out loud. An agent asked to open "welcome to datalayer" should not
    have to be told the identifier first — and if it guesses one, it opens
    nothing.

    So the name is resolved here, and the original tool is called with the
    uid. The original is *wrapped*, not rewritten: everything it does after
    the identifier — the kernel, the collaboration session, registering the
    notebook — is not this extension's business and would rot if copied.

    A name matching several notebooks is not resolved. The candidates are
    returned instead, because opening one of several notebooks the user did
    not choose is worse than asking.
    """
    manager = getattr(mcp, "_tool_manager", None)
    existing = getattr(manager, "_tools", {}).get("use_notebook") if manager else None
    if existing is None:
        logger.debug("No use_notebook tool to wrap")
        return
    original = existing.fn

    try:
        manager.remove_tool("use_notebook")
    except Exception as error:
        # Already absent is the acceptable outcome; anything else is worth a
        # line, because a tool that failed to be removed is a tool that
        # silently keeps the original behaviour.
        logger.debug("use_notebook was not registered: %s", error)

    @mcp.tool(annotations=ToolAnnotations(title="Use Notebook"))
    async def use_notebook(
        notebook_name: Annotated[
            str, Field(description="A short name to refer to this notebook by later")
        ],
        notebook_path: Annotated[
            str,
            Field(
                description=(
                    "Which notebook to open: its name as shown in Datalayer, "
                    "or its uid. Use list_notebooks to see them."
                )
            ),
        ] = "",
        mode: Annotated[
            str, Field(description="'connect' to an existing notebook, or 'create'")
        ] = "connect",
        kernel_id: Annotated[
            str, Field(description="An existing kernel to attach, if you have one")
        ] = "",
    ) -> Any:
        """Open one of your Datalayer notebooks, by name or by uid."""
        resolved = notebook_path
        if notebook_path and mode != "create":
            try:
                notebooks = await spaces.list_notebooks()
            except spaces.SpacesError as error:
                raise ValueError(str(error)) from error

            if not any(n["uid"] == notebook_path for n in notebooks):
                matches = spaces.resolve(notebooks, notebook_path)
                if len(matches) == 1:
                    resolved = matches[0]["uid"]
                    logger.info(
                        "Resolved notebook [%s] to [%s]", notebook_path, resolved
                    )
                elif len(matches) > 1:
                    names = ", ".join(f"{m['name']} ({m['uid']})" for m in matches)
                    raise ValueError(
                        f"{len(matches)} notebooks match '{notebook_path}': {names}. "
                        "Ask which one is meant, then pass its uid."
                    )
                else:
                    raise ValueError(
                        f"No notebook of yours matches '{notebook_path}'. "
                        "Use list_notebooks to see them."
                    )

        return await original(
            notebook_name=notebook_name,
            notebook_path=resolved,
            mode=mode,
            kernel_id=kernel_id or None,
        )
