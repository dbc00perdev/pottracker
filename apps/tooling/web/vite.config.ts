import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: proxy the API so the SPA and FastAPI share an origin (no CORS). The API
// runs at :8000 (`uvicorn apps.tooling.api.main:create_app --factory`). Prod
// serving (nginx under /tooling) is Phase 10.
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
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
