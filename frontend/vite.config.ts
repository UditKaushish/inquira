import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  preview: {
    port: 4173,
    proxy: { "/api": { target: process.env.INQUIRA_API_URL ?? "http://127.0.0.1:8000", changeOrigin: true } },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.INQUIRA_API_URL ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: { charts: ["recharts"], vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] },
      },
    },
  },
});
