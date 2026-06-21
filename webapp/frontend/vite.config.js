import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The browser talks only to the Node gateway. In dev, Vite serves the SPA and
// proxies every /api/* call to the gateway (which mints the Mappls token and
// forwards data/forecast calls to the Python FastAPI service).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
