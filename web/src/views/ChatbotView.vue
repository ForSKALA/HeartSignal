<script setup>
import { nextTick, onBeforeUnmount, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { isRecordingSupported, isVoiceSupported, speak, startRecording, stopSpeaking, transcribe } from "../voice";

const router = useRouter();

const RAG_API_URL = import.meta.env.VITE_RAG_API_URL || "/rag-query";
const prompt = ref("");
const source = ref("pdf");
const isLoading = ref(false);
const messages = ref([]);

// 음성 질문: idle → recording → transcribing → idle. 음성으로 물은 질문만 답변을 읽어 준다
const micState = ref("idle");
const micError = ref("");
let stopRecording = null;

async function toggleMic() {
  micError.value = "";
  if (micState.value === "recording") {
    micState.value = "transcribing";
    try {
      const text = await transcribe(await stopRecording());
      if (!text) throw new Error("음성을 인식하지 못했습니다. 다시 말씀해 주세요.");
      prompt.value = text;
      await ask({ fromVoice: true });
    } catch (error) {
      if (error.status === 401) {
        await router.push("/login");
        return;
      }
      micError.value = error.message;
    } finally {
      stopRecording = null;
      micState.value = "idle";
    }
    return;
  }
  if (micState.value !== "idle" || isLoading.value) return;
  try {
    stopSpeaking(); // 이전 답변 읽기 중이면 멈추고 듣기
    stopRecording = await startRecording();
    micState.value = "recording";
  } catch {
    micError.value = "마이크를 사용할 수 없습니다. 브라우저의 마이크 권한을 확인해 주세요.";
  }
}

onBeforeUnmount(() => {
  stopRecording?.();
  stopSpeaking();
});

async function ask({ fromVoice = false } = {}) {
  const question = prompt.value.trim();
  if (!question || isLoading.value) return;

  messages.value.push({ role: "user", text: question, fromVoice });
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
      credentials: "include", // 로그인 쿠키(ACCESS_TOKEN)를 함께 보냄 — 없으면 401
      body: JSON.stringify({ prompt: question, source: source.value, top_k: 5 }),
    });
    const result = await response.json().catch(() => null);

    if (response.status === 401) {
      await router.push("/login");
      return;
    }
    if (!response.ok) {
      // 표준 오류 {"error": {code, message, request_id}} (AGENTS.md 7.2) 또는 베이스 detail
      const detail = result?.error?.message || result?.detail || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (typeof result?.response !== "string" || !result.response.trim()) {
      throw new Error("검색 서버에서 답변을 받지 못했습니다.");
    }
    answer.text = result.response;
    answer.handoff = result.handoff === true;       // 근거 없음 → 안전관리자 문의 안내
    answer.needsReview = result.needs_review === true;
    answer.sources = Array.isArray(result.sources) ? result.sources : [];
    if (fromVoice) {
      speak(answer.handoff ? `${answer.text} 안전관리자에게 직접 문의해 주세요.` : answer.text);
    }
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
  // 한글 IME 조합 중 Enter는 무시 — 조합 중인 마지막 글자가 v-model에 반영되기 전에 전송되는 문제 방지
  // (Safari는 조합 확정 Enter에서 isComposing=false, keyCode=229)
  if (event.isComposing || event.keyCode === 229) return;
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
            <p v-if="message.handoff" class="message-handoff">
              이 질문은 문서 근거로 답할 수 없습니다. 안전관리자에게 직접 문의해 주세요.
            </p>
            <p v-else-if="message.needsReview" class="message-review">⚠ 근거가 1건뿐이거나 수치 확인이 필요합니다. 원문을 확인하세요.</p>
            <ul v-if="message.sources && message.sources.length" class="message-sources" aria-label="출처">
              <li v-for="(src, i) in message.sources" :key="i">📄 {{ src.source }} <span v-if="src.section">{{ src.section }}</span></li>
            </ul>
          </div>
        </article>
      </section>

      <div class="composer-area">
        <form class="chat-composer" @submit.prevent="ask()">
          <!-- 음성 질문: 누르면 녹음, 다시 누르면 인식 후 바로 질문. 답변은 브라우저 음성으로 읽음 -->
          <button
            v-if="isRecordingSupported"
            type="button"
            class="mic-button"
            :class="`is-${micState}`"
            :aria-label="micState === 'recording' ? '녹음 끝내고 질문하기' : '음성으로 질문하기'"
            :aria-pressed="micState === 'recording'"
            :disabled="micState === 'transcribing' || (isLoading && micState === 'idle')"
            @click="toggleMic"
          >
            <!-- 대기: 파란 스피커 / 녹음 중: 정지 사각형 / 인식 중: 점 3개 -->
            <svg v-if="micState === 'idle'" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
              <path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z" fill="currentColor" />
              <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
            <svg v-else-if="micState === 'recording'" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" />
            </svg>
            <span v-else class="mic-dots" aria-hidden="true"><i></i><i></i><i></i></span>
          </button>
          <textarea
            v-model="prompt"
            rows="1"
            maxlength="500"
            placeholder="안전 관련 질문을 입력하세요..."
            aria-label="질문 입력"
            required
            @keydown="onInputKeydown"
          ></textarea>
          <button type="submit" aria-label="질문 보내기" :disabled="isLoading || !prompt.trim()">↑</button>
        </form>
        <p v-if="micState === 'recording'" class="mic-status" role="status">듣고 있습니다… 말씀을 마치면 ■ 버튼을 누르세요.</p>
        <p v-else-if="micState === 'transcribing'" class="mic-status" role="status">음성을 글자로 바꾸는 중입니다…</p>
        <p v-else-if="micError" class="mic-status is-error" role="alert">{{ micError }}</p>
        <p v-if="!isVoiceSupported && isRecordingSupported" class="mic-status">이 브라우저는 답변 음성 읽기를 지원하지 않아 글로만 표시됩니다.</p>
        <p class="chat-footnote">답변은 검색된 자료를 바탕으로 생성됩니다. 위급한 상황에서는 현장 안전 절차와 긴급 신고를 우선하세요.</p>
      </div>
    </main>
  </div>
</template>
