import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    exclude: ["**/node_modules/**", "**/dist/**", "**/.kilo/**", "**/.git/**"],
    maxWorkers: 1,
    minWorkers: 1,
  },
});
