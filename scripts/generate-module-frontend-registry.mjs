#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..");
const configPath = path.join(repoRoot, "module-frontend-packages.json");
const outputPath = path.join(repoRoot, "client-src", "moduleRegistry.generated.ts");

const raw = JSON.parse(fs.readFileSync(configPath, "utf8"));
const modules = Array.isArray(raw.modules) ? raw.modules : [];
const enabledModules = modules.filter((item) => item?.enabled !== false && item?.import);

const imports = enabledModules
  .map((item, index) => `import module${index} from ${JSON.stringify(item.import)};`)
  .join("\n");
const entries = enabledModules.map((_item, index) => `module${index}`).join(", ");
const body = `${imports}${imports ? "\n\n" : ""}export default [${entries}];\n`;

fs.writeFileSync(outputPath, body, "utf8");
console.log(`Wrote ${path.relative(repoRoot, outputPath)} with ${enabledModules.length} module frontend(s).`);
