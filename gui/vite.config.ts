import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import pkg from "./package.json" with { type: "json" };

// The window loads the built files from disk; only `npm run dev` uses a
// server, and Tauri expects it on this port.
export default defineConfig({
  plugins: [react()],
  // The About view shows the window's own version; taking it from package.json
  // keeps one number instead of two that drift apart.
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  build: { target: "es2023" },
});
