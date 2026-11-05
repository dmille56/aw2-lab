import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  root: "web",
  base: "./",
  plugins: [react()],
  build: { outDir: "../dist", emptyOutDir: true, target: "es2022" },
  server: {
    proxy: {
      "/health": "http://127.0.0.1:43127",
      "/v1": "http://127.0.0.1:43127",
    },
  },
});
