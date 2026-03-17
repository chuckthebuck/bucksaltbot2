import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root: path.join(__dirname, "./client-src/"),
  base: "/assets/",

  resolve: {
    dedupe: ["vue"], // 🔥 CRITICAL
  },

  optimizeDeps: {
    include: ["vue", "@wikimedia/codex"], // 🔥 helps dev + build consistency
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
        format: "iife", // 🔥 ensures globals work predictably
        entryFileNames: "bundled/script-[hash].js",
      },
    },
  },
});
