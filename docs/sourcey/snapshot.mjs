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

// What this server is, for whoever reads the published reference.
//
// Set here because the snapshot does not carry it: `initialize` returns the
// server's `instructions`, which is what an MCP client reads at runtime, but
// mcp-parser records only the name and version — so the validator asks for a
// description that nothing else supplies. Keep this in step with
// `INSTRUCTIONS` in jupyter_mcp_server/server.py; they address the same two
// audiences, a reader of the docs and an agent choosing a tool.
spec.description =
  "Read, edit and run Jupyter notebooks over MCP. Cells are addressed by " +
  "index within a notebook opened with use_notebook, and execution happens " +
  "on the server, so a long computation keeps running after the session ends.";

// Descriptions come straight from Python docstrings, and CPython 3.13 dedents
// docstrings at compile time while 3.12 and earlier keep the source indentation
// (gh.io/cpython#81283). Without normalising, the same server yields a different
// snapshot on different interpreters and the CI drift check in
// .github/workflows/docs.yml fails for no real reason. Reproduce the 3.13 form
// everywhere: strip the common indent from every line after the first and blank
// out whitespace-only lines.
const dedent = (text) => {
  const lines = String(text).split("\n");
  if (lines.length < 2) return text;
  const rest = lines.slice(1);
  let margin = null;
  for (const line of rest) {
    if (!line.trim()) continue;
    const indent = line.match(/^[ \t]*/)[0];
    if (margin === null || indent.length < margin.length) margin = indent;
  }
  if (!margin) return lines[0] + "\n" + rest.map((l) => (l.trim() ? l : "")).join("\n");
  return (
    lines[0] +
    "\n" +
    rest.map((l) => (l.trim() ? l.slice(margin.length) : "")).join("\n")
  );
};

const normalize = (node) => {
  if (Array.isArray(node)) return node.forEach(normalize);
  if (!node || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node)) {
    if (key === "description" && typeof value === "string") node[key] = dedent(value);
    else normalize(value);
  }
};
normalize(spec);

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
