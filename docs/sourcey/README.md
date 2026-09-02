# Generated MCP reference (`/mcp/`)

This directory is the **source** for the generated MCP API reference served at
[`/mcp/`](https://jupyter-mcp-server.datalayer.tech/mcp/). Nothing here is served
directly and nothing built is checked in: `npm run build` in `docs/` renders this
source into `../static/mcp/` (git-ignored) via the `prebuild` script, and Docusaurus
copies it into its own build output like any other static asset. There is no runtime
component — the pages are plain HTML produced at docs build time.

The reference is **generated, not hand-written**: every tool/prompt page is produced
from a live MCP protocol snapshot of the server, so it always shows exactly the
schemas the server advertises, with a link from each page back to the file that
registers it.

`.github/workflows/docs.yml` re-runs the whole generation on every pull request and
fails if the result differs from what is checked in, so these files cannot drift from
the code.

## Contents

| File | Role |
|---|---|
| `mcp.json` | MCP server snapshot ([mcp-parser](https://www.npmjs.com/package/mcp-parser) format): 22 tools + 1 prompt |
| `sourcemap.json` | tool/prompt name → the file whose `@mcp.tool` / `@mcp.prompt` decorator registers it |
| `config-fields.json` | `JupyterMCPConfig` pydantic fields (name, type, default, description) |
| `index.md`, `configuration.md`, `tools/*.md`, `prompts/*.md` | generated pages, rendered from the three files above |
| `sourcey.config.ts` | [Sourcey](https://www.npmjs.com/package/sourcey) site config (two tabs: per-tool pages + interactive MCP explorer) |
| `snapshot.mjs`, `gen_sourcemap.py`, `dump_config.py`, `build_pages.mjs` | the generation pipeline below |
| `build_site.mjs` | renders the pages into `../static/mcp/`; run by `npm run build` / `npm start` |

## Regenerating after the MCP surface changes

From the repository root, with the package (and `extensions/sandboxes`) installed:

```bash
make sync-sourcey
```

That runs `npm install` in `docs/` — which a monorepo-wide install does not cover, since
`docs/` is not one of the workspaces — then the four steps below, checking that step 1
produced a usable `mcp.json` before the steps that read it.

It also refuses to run in an environment that registers `jupyter_mcp_server.extensions`
entry points beyond `sandboxes`. The snapshot is whatever the *installed* server
advertises, so an extra extension silently changes it —
`datalayer_jupyter_mcp_server`'s `spaces` adds `find_notebook` and `list_spaces` and its
tool policy hides `connect_to_jupyter`, `list_files` and `list_kernels` — and the result
is a reference CI can never reproduce, since it installs only this package and
`extensions/sandboxes`. Use a clean environment, or set
`SOURCEY_ALLOW_EXTRA_EXTENSIONS=1` if you know what you are doing.

The steps it runs, if you would rather drive them by hand:

```bash
cd docs/sourcey

# 1. Snapshot the live server surface over stdio
node snapshot.mjs jupyter-mcp-server mcp.json

# 2. Map every registered name to the file that registers it
python gen_sourcemap.py ../.. sourcemap.json

# 3. Dump the configuration model
python dump_config.py config-fields.json

# 4. Regenerate the markdown pages
node build_pages.mjs
```

Commit whatever changed; that is exactly what CI checks. Rendering the site is not
part of this loop — `npm run build` in `docs/` does it, and its output is ignored by
git.

`build_pages.mjs` fails loudly if the three inputs ever disagree: a tool in the
snapshot with no decorator, a decorator missing from the snapshot, or a tool without a
navigation entry in `sourcey.config.ts`.

Source links point at `main` rather than a pinned commit, and carry no line numbers, so
an unrelated edit that merely shifts lines does not make the docs stale.
