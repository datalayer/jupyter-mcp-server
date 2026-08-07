// Snapshot the jupyter-mcp-server MCP surface over stdio.
// Usage: node snapshot.mjs <path-to-jupyter-mcp-server-exe> <out.json>
// Requires `npm install mcp-parser` in this directory (see README.md).
import { snapshot, validate } from "mcp-parser";
import { writeFile } from "node:fs/promises";

const [cmd, out] = process.argv.slice(2);
if (!cmd || !out) {
  console.error("usage: node snapshot.mjs <server-command> <out.json>");
  process.exit(2);
}

const spec = await snapshot({
  // --start-new-code-sandbox false: without it the server blocks before the
  // stdio loop, trying to reach a Jupyter at localhost:8888 that isn't there.
  transport: {
    type: "stdio",
    command: cmd,
    args: ["--transport", "stdio", "--start-new-code-sandbox", "false"],
  },
  timeout: 120000,
});

// The snapshot records the literal spawn command; replace the local venv path
// with the installed console-script name so no machine-specific path is published.
if (spec.transport?.command) spec.transport.command = "jupyter-mcp-server";

const result = validate(spec);
for (const d of result.diagnostics ?? []) {
  console.error(`${d.severity}: ${d.path} - ${d.message}`);
}
await writeFile(out, JSON.stringify(spec, null, 2) + "\n");
console.log(
  JSON.stringify({
    valid: result.valid,
    server: spec.server,
    mcpVersion: spec.mcpVersion,
    tools: spec.tools?.length ?? 0,
    resources: spec.resources?.length ?? 0,
    resourceTemplates: spec.resourceTemplates?.length ?? 0,
    prompts: spec.prompts?.length ?? 0,
  }),
);
