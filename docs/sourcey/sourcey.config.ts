import { defineConfig } from "sourcey";

// Sourcey 3.6.5 build for datalayer/jupyter-mcp-server, pinned to commit
// c132b061240dbe53d83290bff3007f43fc01ea6b.
//
// Two tabs over one machine-produced input:
//  - "Reference": one generated page per MCP tool/prompt plus configuration,
//    built by build_pages.mjs from mcp.json (a live mcp-parser stdio snapshot
//    of the server installed from the pin) and sourcemap.json (decorator
//    file:line at the pin). Every page links back to its source.
//  - "MCP Explorer": Sourcey's native MCP adapter rendering the same mcp.json
//    as a single interactive spec page.
export default defineConfig({
  name: "Jupyter MCP Server",
  siteUrl: "https://jupyter-mcp-server.datalayer.tech",
  baseUrl: "/mcp",
  prettyUrls: "slash",
  repo: "https://github.com/datalayer/jupyter-mcp-server",
  navigation: {
    tabs: [
      {
        tab: "Reference",
        slug: "",
        groups: [
          { group: "Getting started", pages: ["index", "configuration"] },
          {
            group: "Connection & server",
            pages: ["tools/connect_to_jupyter", "tools/list_files", "tools/list_kernels"],
          },
          {
            group: "Notebooks",
            pages: [
              "tools/use_notebook",
              "tools/list_notebooks",
              "tools/read_notebook",
              "tools/restart_notebook",
              "tools/unuse_notebook",
            ],
          },
          {
            group: "Cells",
            pages: [
              "tools/insert_cell",
              "tools/read_cell",
              "tools/edit_cell_source",
              "tools/overwrite_cell_source",
              "tools/move_cell",
              "tools/delete_cell",
              "tools/clear_cell_output",
            ],
          },
          {
            group: "Execution",
            pages: ["tools/execute_cell", "tools/insert_execute_code_cell", "tools/execute_code"],
          },
          {
            group: "Sandboxes (extension)",
            pages: [
              "tools/launch_sandbox",
              "tools/list_sandboxes",
              "tools/use_sandbox",
              "tools/terminate_sandbox",
            ],
          },
          { group: "Prompts", pages: ["prompts/jupyter_cite"] },
        ],
      },
      {
        tab: "MCP Explorer",
        slug: "reference",
        mcp: "mcp.json",
      },
    ],
  },
});
