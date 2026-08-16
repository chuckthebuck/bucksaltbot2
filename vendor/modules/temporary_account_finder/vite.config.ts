import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "modules/temporary_account_finder/frontend/entry.ts",
      name: "TemporaryAccountFinderApp",
      formats: ["iife"],
      fileName: () => "temporary-account-finder-app.js",
      cssFileName: "style",
    },
    outDir: "modules/temporary_account_finder/static",
    emptyOutDir: false,
    cssCodeSplit: false,
  },
});
