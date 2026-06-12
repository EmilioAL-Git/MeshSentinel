import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En desarrollo, Vite hace de proxy hacia el backend (en prod lo hace nginx)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://backend:8000", changeOrigin: true },
      "/ws": { target: "ws://backend:8000", ws: true },
    },
  },
});
