import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// The server resolves production assets through Vite's manifest; development
// requests use the same index entry through the Vite client injected by base.html.
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true
  },
  build: {
    // Flask serves this directory directly and uses the manifest to include any
    // hashed CSS chunks emitted for the shared application entry.
    outDir: 'static/dist',
    emptyOutDir: true,
    manifest: true,
    cssCodeSplit: true
  }
})
