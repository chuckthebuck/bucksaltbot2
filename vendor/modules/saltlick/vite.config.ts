import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    assetsInlineLimit: 100_000,
    lib: {
      entry: "modules/saltlick/frontend/entry.ts",
      name: "SaltlickApp",
      formats: ["iife"],
      fileName: () => "saltlick-app.js",
      cssFileName: "style",
    },
    outDir: "modules/saltlick/static",
    emptyOutDir: true,
    cssCodeSplit: false,
  },
});
