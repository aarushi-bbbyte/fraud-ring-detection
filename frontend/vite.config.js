import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; /api is proxied so the app uses the
// same relative URLs as in the nginx container.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
