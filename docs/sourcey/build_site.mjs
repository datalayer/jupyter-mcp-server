// Render the generated MCP reference from this directory into ../static/mcp,
// which Docusaurus then copies into its own build output at /mcp/.
//
// Wired to the `prebuild` / `prestart` scripts in ../package.json, so it runs as
// part of `npm run build` and `npm start`; ../static/mcp is git-ignored and never
// checked in.
//
//   node build_site.mjs
//
// generateOgImages is off: this must not put binary files on disk or in git.
import { rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildSiteDocs } from "sourcey";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "static", "mcp");

await rm(OUT, { recursive: true, force: true });

const { pageCount } = await buildSiteDocs({
  configDir: HERE,
  outputDir: OUT,
  generateOgImages: false,
});

console.log(`MCP reference: ${pageCount} pages -> docs/static/mcp`);
