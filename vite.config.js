import path from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  root: path.join(__dirname, "./client-src/"),
  base: "/assets/",
  build: {
    outDir: path.join(__dirname, "./assets_compiled/"),
    manifest: "manifest.json",
    assetsDir: "bundled",
    rollupOptions: {
        input: [
          "client-src/script.ts",
          "client-src/styles.less",
        ],
    },
    emptyOutDir: true,
    copyPublicDir: false,
  },
});