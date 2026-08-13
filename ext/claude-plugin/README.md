<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://images.datalayer.io/brand/logos/datalayer-horizontal.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

<div align="center">

<!-- omit in toc -->

# 🪐🤖 Datalayer Plugin for Claude Code

</div>

Connect Claude Code to your Datalayer Notebooks — always-on notebooks, durable
execution and your data — through the hosted Jupyter MCP Server.

## Without the plugin

You do not need this plugin. Claude Code speaks MCP, and the hosted endpoint is
a URL:

```bash
claude mcp add --transport http datalayer https://mcp.datalayer.run/mcp
```

The first call opens a browser, you sign into Datalayer, and you approve what
the agent may do. Claude Code stores the credentials and refreshes them.

```bash
claude mcp list          # check the connection
claude mcp remove datalayer
```

To connect a self-hosted Jupyter instead, point at your own server and pass a
token:

```bash
claude mcp add --transport http jupyter http://localhost:4040/mcp \
  --header "Authorization: Bearer ${MCP_TOKEN}"
```

That is the whole integration. What follows only makes it pleasanter.

## With the plugin

The plugin adds three things on top of the same connection:

- the MCP server is **declared for you**, so there is no URL to remember;
- **slash commands** for the things people do repeatedly;
- prompts that tell Claude how to behave with a remote notebook — most
  importantly, that execution outlives the session.

### Install

```bash
/plugin marketplace add datalayer/jupyter-mcp-server
/plugin install datalayer
```

Or from a checkout of this repository:

```bash
/plugin marketplace add ./ext
/plugin install datalayer
```

Restart Claude Code when prompted. The first tool call opens the browser for
authorization, exactly as above.

### Commands

| Command | What it does |
|---|---|
| `/datalayer:notebook [name]` | List your notebooks, open one, and summarise it |
| `/datalayer:run [index \| all \| description]` | Execute a cell or the whole notebook on the server |
| `/datalayer:status` | Show the connection, the active notebook and running sandboxes |

`/datalayer:notebook` with no argument lists what you can reach and asks. With
an argument it opens the best match, and asks rather than guessing when several
match.

`/datalayer:run` is deliberately careful: it confirms before running a cell it
identified from a description, and when a cell fails it shows the error and
proposes a fix rather than retrying.

## What you can ask for

Once connected, the notebook is simply part of the conversation:

> Open my `sales-forecast` notebook and tell me what it does.

> Add a cell that plots revenue by month and run it.

> Start the training cell — I'm closing my laptop, tell me where to look later.

That last one is the point of the hosted endpoint. Execution belongs to the
server, so a long computation keeps running and its outputs stay attached to
the notebook after Claude Code disconnects.

## What the agent is allowed to do

You approve scopes once, per agent:

| Scope | What it allows |
|---|---|
| `notebooks:read` | Read cells, outputs and metadata |
| `notebooks:write` | Add, edit and delete cells |
| `code:execute` | Run cells on a code sandbox, which consumes credits |
| `data:read` | Read datasets, datasources and dataservers |

Two independent limits apply to every call. The **scope** decides what kind of
operation is allowed; your **Datalayer permissions** decide which notebooks and
data it touches. An agent can never reach a notebook you cannot reach, and a
refusal names the scope that was missing.

Review and disconnect agents under **Settings → Connected Agents** on
Datalayer. Revoking one leaves the others alone.

Your Datalayer password is never shared with Claude Code: you sign into
Datalayer in the browser, and the agent receives only a scoped token.

## Troubleshooting

**The browser did not open.** Check the endpoint is reachable and that it
advertises where to authenticate:

```bash
curl -s https://mcp.datalayer.run/.well-known/oauth-protected-resource/mcp
```

**"This agent was not granted the ... scope."** You approved less than the
command needs. Disconnect the agent in **Settings → Connected Agents** and
connect again, approving the scope named in the message.

**"You do not have permission to ... the notebook ...".** The notebook is not
shared with you at that level. Agents follow the same sharing rules you do, so
ask its owner for edit or execute access.

**Tools do not appear.** Run `claude mcp list`. If `datalayer` is absent, the
plugin did not register it; if it is present but failing, the message names the
reason.

## Learn more

- [Connect an agent to Datalayer](https://datalayer.ai/docs/access-jupyter-mcp-server)
- [Hosted Jupyter MCP Server](https://jupyter-mcp-server.datalayer.tech/hosted)
- [Identity and authentication](https://jupyter-mcp-server.datalayer.tech/features/identity)
