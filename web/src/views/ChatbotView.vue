<script setup>
import { nextTick, ref } from "vue";
import { RouterLink } from "vue-router";

const RAG_API_URL = import.meta.env.VITE_RAG_API_URL || "/rag-query";
const prompt = ref("");
const source = ref("pdf");
const isLoading = ref(false);
const messages = ref([]);

async function ask() {
  const question = prompt.value.trim();
  if (!question || isLoading.value) return;

  messages.value.push({ role: "user", text: question });
  prompt.value = "";
  isLoading.value = true;
  const answer = { role: "assistant", text: "선택한 자료를 검색하고 있습니다...", loading: true };
  messages.value.push(answer);
  await nextTick();
  document.querySelector(".chat-composer textarea")?.focus();

  try {
    const response = await fetch(RAG_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: question, source: source.value, top_k: 5 }),
    });
    const result = await response.json().catch(() => null);

    if (!response.ok) {
      const detail = result?.detail || result?.error || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (typeof result?.response !== "string" || !result.response.trim()) {
      throw new Error("검색 서버에서 답변을 받지 못했습니다.");
    }
    answer.text = result.response;
  } catch (error) {
    console.error(error);
    answer.role = "error";
    answer.text = `답변을 가져오지 못했습니다. RAG 서버(${RAG_API_URL})가 실행 중인지 확인해 주세요.\n${error.message}`;
  } finally {
    answer.loading = false;
    isLoading.value = false;
    await nextTick();
    document.querySelector(".chat-composer textarea")?.focus();
  }
}

function onInputKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ask();
  }
}
</script>

<template>
  <div class="chat-page">
    <header class="chat-topbar">
      <RouterLink class="site-brand" to="/home">
        <span class="brand-heart" aria-hidden="true">♡</span>
        HeartSignal
      </RouterLink>
      <RouterLink class="back-link" to="/home">← 평상시 화면</RouterLink>
    </header>

    <main class="chat-main">
      <section class="chat-intro">
        <div class="chat-intro-icon" aria-hidden="true">✦</div>
        <h1>무엇이 궁금하신가요?</h1>
        <p>안전 관련 질문을 입력하면 선택한 지식 자료를 검색해 답변합니다.</p>

        <div class="source-picker" role="group" aria-label="답변에 사용할 자료 선택">
          <button type="button" :aria-pressed="source === 'pdf'" @click="source = 'pdf'">안전 문서</button>
          <button type="button" :aria-pressed="source === 'web'" @click="source = 'web'">웹 자료</button>
        </div>
        <p class="source-description">
          {{ source === "pdf" ? "업로드된 PDF 안전 자료를 기준으로 답변합니다." : "수집된 웹 자료를 기준으로 답변합니다." }}
        </p>
      </section>

      <section class="chat-messages" aria-live="polite" aria-label="대화 내용">
        <div v-if="messages.length === 0" class="chat-empty">
          질문을 입력해 대화를 시작해 보세요.<br>
          예: “화학물질이 눈에 들어갔을 때 어떻게 해야 하나요?”
        </div>

        <article
          v-for="(message, index) in messages"
          :key="index"
          class="chat-message"
          :class="[`is-${message.role}`, { 'is-loading': message.loading }]"
        >
          <span v-if="message.role !== 'user'" class="assistant-avatar" aria-hidden="true">♥</span>
          <div class="message-content">
            <p class="message-label">
              {{ message.role === "user" ? "나" : message.role === "error" ? "연결 오류" : message.loading ? "검색 중" : "HeartSignal 안전 도우미" }}
            </p>
            <div class="message-bubble">{{ message.text }}</div>
          </div>
        </article>
      </section>

      <div class="composer-area">
        <form class="chat-composer" @submit.prevent="ask">
          <textarea
            v-model="prompt"
            rows="1"
            maxlength="2000"
            placeholder="안전 관련 질문을 입력하세요..."
            aria-label="질문 입력"
            required
            @keydown="onInputKeydown"
          ></textarea>
          <button type="submit" aria-label="질문 보내기" :disabled="isLoading || !prompt.trim()">↑</button>
        </form>
        <p class="chat-footnote">답변은 검색된 자료를 바탕으로 생성됩니다. 위급한 상황에서는 현장 안전 절차와 긴급 신고를 우선하세요.</p>
      </div>
    </main>
  </div>
</template>
