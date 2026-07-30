import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    // Inline the logo and emit one self-contained module bundle. The framework
    // serves these package assets from its authenticated module asset route.
    assetsInlineLimit: 100_000,
    lib: {
      entry: "modules/chuck_salt_shack/frontend/entry.ts",
      name: "ChuckSaltShackApp",
      formats: ["iife"],
      fileName: () => "chuck-salt-shack-app.js",
      cssFileName: "style",
    },
    outDir: "modules/chuck_salt_shack/static",
    emptyOutDir: true,
    cssCodeSplit: false,
  },
});
