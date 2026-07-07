import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: proxy the API so the SPA and FastAPI share an origin (no CORS). The
// tooling API runs on :8001 in dev — port 8000 is taken by Lance CNC Tracker on
// the shared box. Override with TOOLING_API_PROXY if yours differs. Start it via
//   uvicorn apps.tooling.api.main:create_app --factory --port 8001
// Prod serving (nginx under /tooling) is Phase 10.
const apiTarget = process.env.TOOLING_API_PROXY ?? "http://127.0.0.1:8001";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api/tooling": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
