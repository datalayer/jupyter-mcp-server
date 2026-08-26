<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Jupyter MCP Server - Architecture

The architecture is documented on the documentation site, on the
[Architecture](https://jupyter-mcp-server.datalayer.tech/architecture) page.
Its source is [`docs/docs/architecture/index.mdx`](docs/docs/architecture/index.mdx)
in this repository.

In short: one codebase, two modes — a standalone MCP server (`jupyter-mcp-server start`,
over stdio or Streamable HTTP) and a Jupyter Server extension (the same tools, served
under Jupyter's `/mcp`). Both run the same tool classes; the mode decides whether a tool
reaches the notebooks and the code sandbox over HTTP/WebSocket or through the managers of
the Jupyter Server it runs in.
