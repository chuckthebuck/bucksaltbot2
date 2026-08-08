import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "modules/chuck_file_changer/frontend/entry.ts",
      name: "ChuckFileChangerApp",
      formats: ["iife"],
      fileName: () => "chuck-file-changer-app.js",
      cssFileName: "style",
    },
    outDir: "modules/chuck_file_changer/static",
    // Static assets are packaged with the module.  Keep unrelated packaged
    // files instead of removing them whenever the Vue bundle is rebuilt.
    emptyOutDir: false,
    cssCodeSplit: false,
  },
});
