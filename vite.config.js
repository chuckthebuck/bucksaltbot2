import path from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  root: path.join(__dirname, "./client-src/"),
  base: "/assets/",
  plugins: [vue()],
  resolve: {
    dedupe: ["vue"],
  },
  build: {
    outDir: path.join(__dirname, "./assets_compiled/"),
    manifest: "manifest.json",
    assetsDir: "bundled",
    emptyOutDir: true,
    copyPublicDir: false,
    rollupOptions: {
      input: "script.ts",
    },
  },
});
