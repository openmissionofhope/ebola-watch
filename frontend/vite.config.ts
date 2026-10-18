import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Two builds:
// * default: served by the FastAPI app (same origin; the API sets a strict CSP
//   header: no inline scripts, no third-party hosts). In development, /api is
//   proxied to a locally running backend.
// * static (VITE_STATIC=1): reads data files written by `ebolawatch
//   export-static`, for hosting without a server (GitHub Pages). EW_BASE_PATH
//   is the path the site is served from, e.g. "/ebola-watch/" for a project
//   page or "/" for a custom domain. Static hosts cannot set headers, so the
//   CSP is a <meta> tag.
const isStatic = process.env.VITE_STATIC === "1";
const base = process.env.EW_BASE_PATH || "/";

const CSP =
  "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; " +
  "base-uri 'none'; form-action 'none'; object-src 'none'";

function staticBuild(): Plugin {
  return {
    name: "ebolawatch-static",
    transformIndexHtml(html) {
      return html
        .replace(
          '<meta charset="UTF-8" />',
          `<meta charset="UTF-8" />\n    <meta name="ebolawatch-build" content="static" />\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`,
        )
        .replace("The data are also available from the API at /api/docs.", "The data are also published as JSON and CSV files.");
    },
  };
}

export default defineConfig({
  plugins: [react(), ...(isStatic ? [staticBuild()] : [])],
  base: isStatic ? base : "/",
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false, target: "es2020" },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
});
