#!/usr/bin/env node
/** Generate side-effect imports for module frontends included in the root bundle. */
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..");
const configPath = path.join(repoRoot, "module-frontend-packages.json");
const outputPath = path.join(repoRoot, "client-src", "moduleRegistry.generated.ts");

const raw = JSON.parse(fs.readFileSync(configPath, "utf8"));
const modules = Array.isArray(raw.modules) ? raw.modules : [];
// Disabled or incomplete entries must not become build-time imports: Vite would
// otherwise fail the entire framework build on an intentionally absent module.
const enabledModules = modules.filter((item) => item?.enabled !== false && item?.import);

const imports = enabledModules
  .map((item) => `import ${JSON.stringify(item.import)};`)
  .join("\n");
const entries = enabledModules
  .map((item) => JSON.stringify({ name: item.name || null, import: item.import }))
  .join(", ");
const body = `${imports}${imports ? "\n\n" : ""}export default [${entries}];\n`;

// This file is generated deterministically so CI can detect a stale registry.
fs.writeFileSync(outputPath, body, "utf8");
console.log(`Wrote ${path.relative(repoRoot, outputPath)} with ${enabledModules.length} module frontend(s).`);
