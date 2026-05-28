import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite serves the SPA on :5173 and proxies the API + Socket.IO to the
// Flask backend on :5000 (DESIGN.md §4). Prod: `npm run build` emits web/dist,
// which Flask serves directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5001",
      "/socket.io": { target: "http://127.0.0.1:5001", ws: true },
    },
  },
  build: { outDir: "dist" },
});
