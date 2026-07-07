import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import "@/index.css";

// Scaffold entry (Phase 4 step 1). Providers (QueryClient, Router, Auth) are
// wired in step 2 — this just proves the toolchain renders.
const root = document.getElementById("root");
if (!root) throw new Error("root element not found");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
