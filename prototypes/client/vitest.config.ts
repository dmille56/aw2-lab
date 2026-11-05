import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{js,ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["web/**/*.{ts,tsx}"],
      exclude: ["web/generated/**", "web/main.tsx", "web/env.d.ts"],
      reporter: ["text", "json-summary"],
    },
  },
});
