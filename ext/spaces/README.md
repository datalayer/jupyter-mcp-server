<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Jupyter MCP Spaces

Lists and opens the notebooks of a [Datalayer](https://datalayer.ai) space.

Datalayer keeps notebooks in **spaces**, addressed by uid. There is no
filesystem and no kernels API, so the tools that assume a Jupyter server have
nothing to answer:

| Tool | On a Jupyter server | On Datalayer |
|---|---|---|
| `list_files` | lists the directory | nothing to list |
| `list_kernels` | lists kernels | runtimes, provisioned on demand |
| `list_notebooks` | notebooks bound this session | — |

This extension replaces `list_notebooks` with one that answers the question
people actually ask, adds `list_spaces` and `find_notebook`, and hides the
tools that cannot work — so an agent is never offered a tool that always
fails.

## Install

```bash
pip install jupyter-mcp-spaces
```

It registers itself on the `jupyter_mcp_server.extensions` entry point and
activates only when the server runs with `--document-provider datalayer`.
Pointed at a Jupyter server it does nothing, and the ordinary tools stay.

```bash
jupyter-mcp-server start --transport streamable-http \
  --document-provider datalayer \
  --document-url https://prod1.datalayer.run
```

## Tools

| Tool | What it answers |
|---|---|
| `list_spaces` | The spaces you can reach |
| `list_notebooks` | The notebooks in them, with uid and space |
| `find_notebook` | Which notebook a name means — or the candidates, when it is ambiguous |

`find_notebook` never picks between candidates. Guessing which notebook
somebody meant is how an agent edits the wrong one.

## Credentials

Every call carries the token of the request being served, from
`jupyter_mcp_server.identity`. A server acting for several people over its
life must use the credential each request arrived with, not one configured at
startup — see the [identity
documentation](https://jupyter-mcp-server.datalayer.tech/features/identity).
