import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/',
  build: {
    outDir: '../spaces/crawler/static',
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
      '/search': 'http://localhost:7860',
      '/doc': 'http://localhost:7860',
      '/trending': 'http://localhost:7860',
      '/suggest': 'http://localhost:7860',
      '/stats': 'http://localhost:7860',
      '/health': 'http://localhost:7860',
      '/privacy': 'http://localhost:7860',
    },
  },
});
