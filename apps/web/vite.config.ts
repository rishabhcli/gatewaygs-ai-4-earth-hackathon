import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4171,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:4170",
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4171,
    strictPort: true,
  },
  build: {
    sourcemap: true,
    target: "es2022",
  },
});
