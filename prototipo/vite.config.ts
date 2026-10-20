import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// O protótipo conversa com o mesmo servidor de teste do app (porta 5001).
// O proxy faz o navegador enxergar tudo como mesma origem: sem CORS, e o
// cookie de sessão do login vale normalmente.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5001', changeOrigin: false },
      '/demo-fotos': { target: 'http://127.0.0.1:5001', changeOrigin: false },
    },
  },
});
