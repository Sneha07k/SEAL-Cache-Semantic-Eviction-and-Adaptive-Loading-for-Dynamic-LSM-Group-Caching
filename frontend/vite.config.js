import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Requests to /api are forwarded to the FastAPI backend (default port 8000;
// override with API_TARGET=http://127.0.0.1:8001 when 8000 is taken).
const target = process.env.API_TARGET || "http://127.0.0.1:8000";
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": target } },
  preview: { port: 4173, proxy: { "/api": target } },
});
