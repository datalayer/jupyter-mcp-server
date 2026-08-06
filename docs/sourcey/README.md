# Generated MCP reference (`/mcp/`)

This directory is the source for the generated MCP API reference served at
[`/mcp/`](https://jupyter-mcp-server.datalayer.tech/mcp/). The built site lives in
`../static/mcp/` and is published verbatim by the normal Docusaurus deploy — no
changes to the docs build are needed.

The reference is **generated, not hand-written**: every tool/prompt page is produced
from a live MCP protocol snapshot of the server, so it always shows exactly the
schemas the server advertises, with a link from each page back to the decorator
that registers it (pinned to the commit the snapshot was taken from).

## Contents

| File | Role |
|---|---|
| `mcp.json` | MCP server snapshot ([mcp-parser](https://www.npmjs.com/package/mcp-parser) format): 22 tools + 1 prompt, protocol `2025-11-25` |
| `sourcemap.json` | tool/prompt name → `file:line` of its `@mcp.tool` / `@mcp.prompt` decorator |
| `config-fields.json` | `JupyterMCPConfig` pydantic fields (name, type, default, description) |
| `index.md`, `configuration.md`, `tools/*.md`, `prompts/*.md` | generated pages (inputs to Sourcey) |
| `sourcey.config.ts` | [Sourcey](https://www.npmjs.com/package/sourcey) site config (two tabs: per-tool pages + interactive MCP explorer) |
| `snapshot.mjs`, `gen_sourcemap.py`, `dump_config.py`, `build_pages.mjs` | the pipeline below |

## Regenerating after the MCP surface changes

From a checkout at the commit you want to document, with the package (and
`ext/sandboxes`) installed into a virtualenv:

```bash
cd docs/sourcey
npm install sourcey@3.6.5 mcp-parser@0.4.1

# 1. Snapshot the live server surface over stdio
node snapshot.mjs <venv>/bin/jupyter-mcp-server mcp.json

# 2. Map every registered name to its decorator's file:line
python gen_sourcemap.py ../.. sourcemap.json

# 3. Dump the configuration model
<venv>/bin/python dump_config.py config-fields.json

# 4. Regenerate the markdown pages (update COMMIT in build_pages.mjs first)
node build_pages.mjs

# 5. Rebuild the site
npx sourcey build -o ../static/mcp
```

`build_pages.mjs` fails loudly if the snapshot and the page groups ever disagree
(a new tool without a nav entry, or a nav entry whose tool disappeared).
