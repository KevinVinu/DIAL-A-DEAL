import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    optimizeDeps: {
      exclude: ['@splinetool/runtime', '@splinetool/viewer', '@splinetool/react-spline'],
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâ€”file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Ignore backend SQLite/WAL/ChromaDB files so live calls never trigger Vite full-page reloads.
      watch:
        process.env.DISABLE_HMR === 'true'
          ? null
          : {
              ignored: ['**/backend/**', '**/*.db*', '**/chroma_db/**', '**/__pycache__/**'],
            },
    },
  };
});
