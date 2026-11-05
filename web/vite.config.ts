/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the bot (or `python -m mugetsu.web.demo`) serves the API on :8080
// and Vite serves the UI on :5173, forwarding everything that isn't UI code.
const backend = process.env.MUGETSU_BACKEND ?? "http://127.0.0.1:8080";
const forward = { target: backend, changeOrigin: true };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": forward,
      "/ws": { ...forward, ws: true },
      "/login": forward,
      "/callback": forward,
      "/logout": forward,
      "/healthz": forward,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: "node",
  },
});
