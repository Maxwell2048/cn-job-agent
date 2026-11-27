import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server: http://127.0.0.1:5173 with /api proxied to `cn-agent serve` on 8100.
// Production: `npm run build`, then `cn-agent serve` serves dist/ itself.
// VITE_BASE=/cn-job-agent/ builds the read-only demo for GitHub Pages (see .github/workflows/pages.yml).
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8100", changeOrigin: false } },
  },
});
