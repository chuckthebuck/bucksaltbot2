import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "modules/self_delete/frontend/entry.ts",
      name: "SelfDeleteApp",
      formats: ["iife"],
      fileName: () => "self-delete-app.js",
      cssFileName: "style",
    },
    outDir: "modules/self_delete/static",
    emptyOutDir: false,
    cssCodeSplit: false,
  },
});
