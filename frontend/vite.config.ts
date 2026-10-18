import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build is served by the FastAPI app (same origin, strict CSP:
// no inline scripts, no third-party hosts). In development, /api is proxied to
// a locally running backend.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false, target: "es2020" },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
});
