import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: process.env.VITE_BASE_PATH || '/',
  build: {
    outDir: process.env.VITE_OUT_DIR || '../spaces/crawler/static',
    emptyOutDir: true,
    assetsDir: 'ui-assets',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          markdown: ['marked', 'dompurify', 'highlight.js'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/search': 'http://localhost:8080',
      '/doc': 'http://localhost:8080',
      '/trending': 'http://localhost:8080',
      '/suggest': 'http://localhost:8080',
      '/stats': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/privacy': 'http://localhost:8080',
    },
  },
});
