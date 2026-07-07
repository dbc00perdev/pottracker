import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

// Reuse the app's vite config (aliases, plugins) and layer the test env on top.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: true,
    },
  }),
);
