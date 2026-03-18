import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'static/dist',
    emptyOutDir: true,

    cssCodeSplit: true, 

    rollupOptions: {
      input: path.resolve(__dirname, 'client-src/script.ts'),
      output: {
        entryFileNames: 'bundle.js'
      }
    }
  }
})
