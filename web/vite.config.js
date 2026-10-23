import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    proxy: {
      "/api": "http://localhost:8080",
      "/rag-query": "http://localhost:8001",
      "/alarm": "http://localhost:8001",
      "/board": "http://localhost:8001",
      // Voice-AI: 배포 Ingress 처럼 앞의 /voice 를 떼고 넘긴다 (voice 는 --root-path /voice 로 실행)
      "^/voice(/|$)": { target: "http://localhost:8008", rewrite: (path) => path.replace(/^\/voice/, "") || "/" },
    },
  },
});
