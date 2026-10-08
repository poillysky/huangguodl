import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          artplayer: ["artplayer", "hls.js"],
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    // 反代域名（如 Cloudflare / frp）访问时需放行 Host
    allowedHosts: ["e.605081.xyz", ".605081.xyz"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
