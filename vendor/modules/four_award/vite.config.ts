import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "modules/four_award/frontend/entry.ts",
      name: "FourAwardHelperApp",
      formats: ["iife"],
      fileName: () => "four-award-app.js",
      cssFileName: "style",
    },
    outDir: "modules/four_award/static",
    emptyOutDir: true,
    cssCodeSplit: false,
  },
});
