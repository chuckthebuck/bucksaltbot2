import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root: path.join(__dirname, "./client-src/"),
  base: "/assets/",

  resolve: {
    dedupe: ["vue"], 
  },

  optimizeDeps: {
    include: ["vue", "@wikimedia/codex"], 
  },

  build: {
    outDir: path.join(__dirname, "./assets_compiled/"),
    manifest: "manifest.json",
    assetsDir: "bundled",
    emptyOutDir: true,
    copyPublicDir: false,

    rollupOptions: {
      input: [
        "client-src/script.ts",
        "client-src/styles.less",
      ],

      output: {
        format: "iife", 
        entryFileNames: "bundled/script-[hash].js",
      },
    },
  },
});
