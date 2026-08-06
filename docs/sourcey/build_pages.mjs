// Generate per-tool / per-prompt / configuration markdown pages for the
// Sourcey site from the live MCP snapshot (mcp.json), the source map
// (sourcemap.json, tool -> file:line at the pinned commit) and the pydantic
// configuration dump (config-fields.json). Nothing on any page is hand-typed
// per-tool: every fact comes from one of those three machine-produced inputs.
//
//   node build_pages.mjs
//
// Outputs pages/ next to this script plus pages-manifest.json (consumed by the
// packet builder so page counts are computed, not asserted).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OWNER = "datalayer";
const REPO = "jupyter-mcp-server";
const COMMIT = "c132b061240dbe53d83290bff3007f43fc01ea6b";
const PKG_VERSION = "1.2.0"; // src/jupyter_mcp_server/__version__.py at the pin
const BLOB = `https://github.com/${OWNER}/${REPO}/blob/${COMMIT}`;

const spec = JSON.parse(await readFile(join(HERE, "mcp.json"), "utf8"));
const srcmap = JSON.parse(await readFile(join(HERE, "sourcemap.json"), "utf8"));
const cfg = JSON.parse(await readFile(join(HERE, "config-fields.json"), "utf8"));

const GROUPS = [
  ["Connection & server", ["connect_to_jupyter", "list_files", "list_kernels"]],
  ["Notebooks", ["use_notebook", "list_notebooks", "read_notebook", "restart_notebook", "unuse_notebook"]],
  ["Cells", ["insert_cell", "read_cell", "edit_cell_source", "overwrite_cell_source", "move_cell", "delete_cell", "clear_cell_output"]],
  ["Execution", ["execute_cell", "insert_execute_code_cell", "execute_code"]],
  ["Sandboxes (extension)", ["launch_sandbox", "list_sandboxes", "use_sandbox", "terminate_sandbox"]],
];

const tools = new Map((spec.tools ?? []).map((t) => [t.name, t]));
const prompts = spec.prompts ?? [];

// -- integrity: groups must cover the snapshot exactly ---------------------
const grouped = GROUPS.flatMap(([, names]) => names);
const missing = [...tools.keys()].filter((n) => !grouped.includes(n));
const phantom = grouped.filter((n) => !tools.has(n));
if (missing.length || phantom.length) {
  throw new Error(`group mismatch: missing=${missing} phantom=${phantom}`);
}
for (const name of [...tools.keys(), ...prompts.map((p) => p.name)]) {
  if (!srcmap[name]) throw new Error(`no source map entry for ${name}`);
}

// -- helpers ----------------------------------------------------------------
const esc = (s) =>
  String(s ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
// Sourcey slugifies page paths (underscores become hyphens); public links must
// use the slugified form or they 404 on the built site.
const urlOf = (kind, name) => `/mcp/${kind}/${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}/`;
const firstSentence = (s) => {
  const t = String(s ?? "").trim().split(/\r?\n/)[0];
  const m = t.match(/^.*?[.!?](\s|$)/);
  return (m ? m[0] : t).trim();
};
const typeOf = (sch) => {
  if (!sch) return "any";
  if (sch.anyOf) return sch.anyOf.map(typeOf).join(" \\| ");
  if (sch.type === "array") return `array<${typeOf(sch.items)}>`;
  if (sch.enum) return sch.enum.map((v) => `\`${v}\``).join(" · ");
  return sch.type ?? "object";
};
// Python-literal serializer for the Python call sample — JSON.stringify emits
// true/false/null, which are NameErrors in Python (True/False/None).
const pyLit = (v) => {
  if (v === null) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (Array.isArray(v)) return `[${v.map(pyLit).join(", ")}]`;
  if (typeof v === "object")
    return `{${Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${pyLit(x)}`).join(", ")}}`;
  return JSON.stringify(v);
};
const sourceSection = (name) => {
  const e = srcmap[name];
  return [
    "## Source",
    "",
    `Registered by the \`@mcp.${e.kind}\` decorator at [\`${e.file}:${e.line}\`](${BLOB}/${e.file}#L${e.line}) (commit \`${COMMIT.slice(0, 12)}\`).`,
    "",
  ].join("\n");
};

const files = [];
async function emit(rel, lines) {
  const body = lines.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
  const abs = join(HERE, rel);
  await mkdir(dirname(abs), { recursive: true });
  await writeFile(abs, body, "utf8");
  files.push({ path: rel, bytes: Buffer.byteLength(body) });
}

// -- tool pages -------------------------------------------------------------
for (const [name, tool] of tools) {
  const lines = [];
  lines.push("---", `title: "${name}"`, `description: "${esc(firstSentence(tool.description)).replace(/"/g, '\\"')}"`, "---", "");
  lines.push(`# ${name}`, "");
  if (tool.title && tool.title !== name) lines.push(`**${tool.title}**`, "");
  lines.push(String(tool.description ?? "").trim(), "");

  const a = tool.annotations ?? {};
  const hints = [
    ["read-only", a.readOnlyHint],
    ["destructive", a.destructiveHint],
    ["idempotent", a.idempotentHint],
    ["open-world", a.openWorldHint],
  ].filter(([, v]) => v !== undefined);
  if (hints.length) {
    lines.push(
      "> " + hints.map(([k, v]) => `${k}: **${v ? "yes" : "no"}**`).join(" · "),
      ""
    );
  }

  const props = tool.inputSchema?.properties ?? {};
  const required = new Set(tool.inputSchema?.required ?? []);
  lines.push("## Parameters", "");
  if (Object.keys(props).length === 0) {
    lines.push("This tool takes no parameters.", "");
  } else {
    lines.push(
      "| Parameter | Type | Required | Default | Description |",
      "| --- | --- | --- | --- | --- |"
    );
    for (const [pname, p] of Object.entries(props)) {
      const def = p.default === undefined ? "—" : `\`${JSON.stringify(p.default)}\``;
      lines.push(
        `| \`${pname}\` | ${typeOf(p)} | ${required.has(pname) ? "yes" : "no"} | ${def} | ${esc(p.description ?? p.title ?? "")} |`
      );
    }
    lines.push("");
  }

  if (tool.outputSchema) {
    lines.push("## Output", "", "```json", JSON.stringify(tool.outputSchema, null, 2), "```", "");
  }

  // Sample must include every required parameter (required is a Set of NAMES,
  // so test the key, not the schema object) plus every optional with a default.
  // p.default !== undefined (not ??) so a null default renders as null, never
  // as a "<name>" placeholder that looks required.
  const example = Object.fromEntries(
    Object.entries(props)
      .filter(([k, p]) => p.default !== undefined || required.has(k))
      .map(([k, p]) => [
        k,
        p.default !== undefined
          ? p.default
          : p.type === "number" || p.type === "integer"
            ? 0
            : `<${k}>`,
      ])
  );
  lines.push("## Call it", "");
  lines.push("```json");
  lines.push(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: example } }, null, 2));
  lines.push("```", "");
  lines.push("```python");
  lines.push(`result = await session.call_tool("${name}", arguments=${pyLit(example)})`);
  lines.push("```", "");

  lines.push(sourceSection(name));
  await emit(`tools/${name}.md`, lines);
}

// -- prompt pages -----------------------------------------------------------
for (const prompt of prompts) {
  const lines = [];
  lines.push("---", `title: "${prompt.name}"`, `description: "${esc(firstSentence(prompt.description)).replace(/"/g, '\\"')}"`, "---", "");
  lines.push(`# ${prompt.name}`, "", String(prompt.description ?? "").trim(), "");
  const args = prompt.arguments ?? [];
  lines.push("## Arguments", "");
  if (!args.length) {
    lines.push("This prompt takes no arguments.", "");
  } else {
    lines.push("| Argument | Required | Description |", "| --- | --- | --- |");
    for (const arg of args) {
      lines.push(`| \`${arg.name}\` | ${arg.required ? "yes" : "no"} | ${esc(arg.description ?? "")} |`);
    }
    lines.push("");
  }
  lines.push("## Call it", "");
  lines.push("```json");
  lines.push(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "prompts/get", params: { name: prompt.name, arguments: Object.fromEntries(args.map((x) => [x.name, `<${x.name}>`])) } }, null, 2));
  lines.push("```", "");
  lines.push(sourceSection(prompt.name));
  await emit(`prompts/${prompt.name}.md`, lines);
}

// -- configuration page -----------------------------------------------------
{
  const lines = [];
  lines.push("---", 'title: "Configuration"', `description: "Every setting of ${cfg.model}, generated from the pydantic model at the pinned commit."`, "---", "");
  lines.push("# Configuration", "");
  lines.push(
    `All runtime settings live on the \`${cfg.model}\` pydantic model ` +
      `([\`${cfg.source_file}\`](${BLOB}/${cfg.source_file})). Most map 1:1 to ` +
      "`jupyter-mcp-server` CLI options (kebab-case) and environment variables (upper snake-case).",
    ""
  );
  lines.push("| Setting | Type | Default | Description |", "| --- | --- | --- | --- |");
  for (const f of cfg.fields) {
    const def = f.default === null ? "`None`" : `\`${JSON.stringify(f.default)}\``;
    lines.push(`| \`${f.name}\` | ${esc(f.type.replace(/<class '|'>/g, ""))} | ${def} | ${esc(f.description)} |`);
  }
  lines.push("");
  lines.push("## Transports", "");
  lines.push(
    `The server speaks MCP over two transports, selected with \`--transport\` ` +
      `([\`jupyter_mcp_server/cli/commands/serve.py:20\`](${BLOB}/jupyter_mcp_server/cli/commands/serve.py#L20)):`,
    "",
    `- \`stdio\` (default) — the server is spawned by the MCP client and framed over stdin/stdout ([\`jupyter_mcp_server/utils.py:345\`](${BLOB}/jupyter_mcp_server/utils.py#L345)).`,
    `- \`streamable-http\` — served by uvicorn on \`--port\`; requires \`--mcp-token\` unless \`--insecure-mcp-noauth\` is passed ([\`jupyter_mcp_server/utils.py:253\`](${BLOB}/jupyter_mcp_server/utils.py#L253)).`,
    ""
  );
  lines.push("## Serving modes", "");
  lines.push(
    `Beyond the standalone \`MCP_SERVER\` mode documented here, the package also runs embedded ` +
      `inside a Jupyter Server as an extension (\`JUPYTER_SERVER\` mode) — see ` +
      `[\`jupyter_mcp_server/server_modes.py\`](${BLOB}/jupyter_mcp_server/server_modes.py) and ` +
      `[\`jupyter_mcp_server/jupyter_extension/\`](https://github.com/${OWNER}/${REPO}/tree/${COMMIT}/jupyter_mcp_server/jupyter_extension).`,
    ""
  );
  await emit("configuration.md", lines);
}

// -- index / overview -------------------------------------------------------
{
  const lines = [];
  lines.push("---", 'title: "Overview"', `description: "MCP reference for Jupyter MCP Server ${PKG_VERSION}: ${tools.size} tools and ${prompts.length} prompt, generated from a live protocol snapshot at a pinned commit."`, "---", "");
  lines.push("# Jupyter MCP Server — MCP reference", "");
  lines.push(
    `[Jupyter MCP Server](https://github.com/${OWNER}/${REPO}) v${PKG_VERSION} is a ` +
      "[Model Context Protocol](https://modelcontextprotocol.io) server that lets AI agents " +
      "operate Jupyter notebooks: managing notebooks and cells, executing code on live kernels, " +
      "and provisioning code sandboxes.",
    ""
  );
  lines.push(
    `This reference documents the server's complete MCP surface — **${tools.size} tools** and ` +
      `**${prompts.length} prompt** (protocol revision \`${spec.mcpVersion}\`) — captured from a ` +
      `running server built at commit ` +
      `[\`${COMMIT.slice(0, 12)}\`](https://github.com/${OWNER}/${REPO}/tree/${COMMIT}). ` +
      "Each page shows the exact schema the server advertises plus a link to the decorator that registers it. " +
      "The [MCP Reference tab](/mcp/reference/) renders the same snapshot as a single interactive page, " +
      "and [Configuration](/mcp/configuration/) covers every runtime setting and both transports.",
    ""
  );
  for (const [group, names] of GROUPS) {
    lines.push(`## ${group}`, "");
    lines.push("| Tool | Summary |", "| --- | --- |");
    for (const n of names) {
      lines.push(`| [\`${n}\`](${urlOf("tools", n)}) | ${esc(firstSentence(tools.get(n).description))} |`);
    }
    lines.push("");
  }
  lines.push("## Prompts", "");
  lines.push("| Prompt | Summary |", "| --- | --- |");
  for (const p of prompts) {
    lines.push(`| [\`${p.name}\`](${urlOf("prompts", p.name)}) | ${esc(firstSentence(p.description))} |`);
  }
  lines.push("");
  lines.push("## About these docs", "");
  lines.push(
    "Generated with [Sourcey](https://www.npmjs.com/package/sourcey) 3.6.5 from an " +
      "[mcp-parser](https://www.npmjs.com/package/mcp-parser) stdio snapshot of the server " +
      `(\`jupyter-mcp-server --transport stdio --start-new-code-sandbox false\`) installed from commit \`${COMMIT.slice(0, 12)}\`. ` +
      "The snapshot, source map, and page generator are checked in next to the site so the docs can be " +
      "regenerated from any commit.",
    ""
  );
  await emit("index.md", lines);
}

await writeFile(
  join(HERE, "pages-manifest.json"),
  JSON.stringify(
    {
      commit: COMMIT,
      package_version: PKG_VERSION,
      mcp_version: spec.mcpVersion,
      tool_pages: tools.size,
      prompt_pages: prompts.length,
      config_fields: cfg.fields.length,
      markdown_pages: files.length,
      files,
    },
    null,
    2
  ) + "\n"
);
console.log(`${files.length} markdown pages generated`);
