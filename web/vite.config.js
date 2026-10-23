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
      "/board": "http://localhost:8001",   // 비상 화면 (/board/current)
      "/alarm": "http://localhost:8001",   // Swagger 시연용 경보 API
      "/tts": "http://localhost:8008",     // 대피 음성 (Voice-AI OpenAI TTS)
      "/uploads": "http://localhost:8008", // Voice-AI가 만든 mp3
    },
  },
});
