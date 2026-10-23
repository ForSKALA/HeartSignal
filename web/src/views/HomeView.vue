<script setup>
import { ref } from "vue";
import { RouterLink } from "vue-router";

const isExposureRisk = ref(false);
</script>

<template>
  <main class="status-page" :class="{ 'is-exposure-risk': isExposureRisk }">
    <header class="status-topbar">
      <RouterLink class="site-brand" to="/home">HeartSignal</RouterLink>
      <div class="status-actions">
        <RouterLink class="chat-link" to="/chatbot">안전 정보 묻기</RouterLink>
        <span class="level-badge">
          <span class="level-dot"></span>
          {{ isExposureRisk ? "2단계 · 노출위험" : "1단계 · 평상시" }}
        </span>
      </div>
    </header>

    <section class="status-card" aria-live="polite">
      <div class="status-icon" aria-hidden="true">{{ isExposureRisk ? "!" : "✓" }}</div>
      <p class="eyebrow">CURRENT STATUS</p>
      <h1>{{ isExposureRisk ? "대피해주세요" : "평상시" }}</h1>
      <p class="status-description">
        <template v-if="isExposureRisk">
          노출 위험 상황입니다.<br>위험 지역에서 벗어나 안전한 곳으로 대피해 주세요.
        </template>
        <template v-else>
          현재 위험 상황이 아닙니다.<br>주변을 살피며 평소처럼 이용해 주세요.
        </template>
      </p>
      <p class="status-note">
        {{ isExposureRisk ? "노출 위험 · 즉시 안전한 곳으로 대피" : "위험 신호 없음 · 1단계 안전 상태" }}
      </p>
    </section>

    <button
      class="emergency-button"
      type="button"
      :aria-pressed="isExposureRisk"
      @click="isExposureRisk = true"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M10 21h4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      </svg>
      {{ isExposureRisk ? "2단계 · 노출위험" : "위급 상황" }}
    </button>
  </main>
</template>
