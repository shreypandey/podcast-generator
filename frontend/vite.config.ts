import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API contract deploys as a single container: FastAPI serves /api/* and the compiled
// dist/. In dev we proxy /api to the local backend (default :8000). Set VITE_USE_MOCK=1 to
// run the whole UI against the in-browser mock backend with no server at all.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
