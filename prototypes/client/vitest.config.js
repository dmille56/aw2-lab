import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: ["tests/**/*.test.js"],
    coverage: {
      provider: "v8",
      include: ["web/state.js", "web/transport.js"],
      reporter: ["text", "json-summary"],
    },
  },
});
