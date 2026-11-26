import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7860",
      "/sessions": "http://127.0.0.1:7860",
      "/start": "http://127.0.0.1:7860",
    },
  },
});
