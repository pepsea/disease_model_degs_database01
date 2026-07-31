import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // 開発時は API を同一オリジンに見せて CORS を避ける
    proxy: {
      "/api": {
        target: process.env.DMDEG_API_URL ?? "http://127.0.0.1:8002",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // Plotly はバンドルの大半を占めるうえ更新頻度が低い。別チャンクに切って
    // アプリ側の変更でキャッシュが無効化されないようにする。
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ["plotly.js-dist-min"],
          vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
        },
      },
    },
  },
});
