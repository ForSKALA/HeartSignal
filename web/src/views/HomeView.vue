<script setup>
import { RouterLink } from "vue-router";
import { useBoard } from "../useBoard";

// 상태는 안전관리자가 발령한 경보(rag /board/current)로만 바뀐다. 화면에서 발령하지 않는다.
const { board, isActive, isCleared, stageLabel, sourceText, lastError, replay } = useBoard();
</script>

<template>
  <main class="status-page" :class="{ 'is-exposure-risk': isActive, 'is-cleared': isCleared }">
    <header class="status-topbar">
      <RouterLink class="site-brand" to="/home">HeartSignal</RouterLink>
      <div class="status-actions">
        <RouterLink class="chat-link" to="/chatbot">안전 정보 묻기</RouterLink>
        <span class="level-badge">
          <span class="level-dot"></span>
          {{ stageLabel }}
        </span>
      </div>
    </header>

    <section class="status-card" aria-live="assertive">
      <div class="status-icon" aria-hidden="true">{{ isActive ? "!" : "✓" }}</div>
      <p class="eyebrow">{{ isActive ? "EMERGENCY" : "CURRENT STATUS" }}</p>
      <h1>{{ isActive ? "비상상황" : isCleared ? "경보 해제" : "평상시" }}</h1>

      <template v-if="isActive || isCleared">
        <ul class="board-lines" aria-label="대피 안내">
          <li v-for="(line, i) in board.lines" :key="i">{{ line }}</li>
        </ul>
        <p v-if="sourceText" class="board-source">📄 근거: {{ sourceText }}</p>
        <p v-else class="board-source is-fallback">근거 확인 필요 — 고정 안내 문구입니다</p>
        <button class="replay-button" type="button" @click="replay">🔊 대피 안내 다시 듣기</button>
      </template>
      <template v-else>
        <p class="status-description">현재 위험 상황이 아닙니다.<br>주변을 살피며 평소처럼 이용해 주세요.</p>
        <p class="status-note">위험 신호 없음 · 1단계 안전 상태</p>
      </template>
      <p v-if="lastError" class="board-error">경보 서버 연결 확인 중 ({{ lastError }})</p>
    </section>
  </main>
</template>
