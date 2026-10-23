<script setup>
import { ref } from "vue";
import { RouterLink } from "vue-router";

const isExposureRisk = ref(false);
const isReportDialogOpen = ref(false);
const reportNotice = ref("");

function raiseExposureRisk() {
  if (isExposureRisk.value) return; // 이미 2단계면 다시 묻지 않음
  isExposureRisk.value = true;
  reportNotice.value = "";
  isReportDialogOpen.value = true;
}

// 119 신고는 모의 발송만 (AGENTS.md 2장 5번) — 실제 외부 발송 없음
function answerReport(confirmed) {
  isReportDialogOpen.value = false;
  reportNotice.value = confirmed
    ? "119 신고(모의)가 접수되었습니다. 실제로 발송되지는 않습니다."
    : "119 신고를 하지 않았습니다. 필요하면 안전관리자에게 알려 주세요.";
}
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
      @click="raiseExposureRisk"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M10 21h4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      </svg>
      {{ isExposureRisk ? "2단계 · 노출위험" : "위급 상황" }}
    </button>

    <p v-if="reportNotice" class="emergency-notice" role="status">{{ reportNotice }}</p>

    <div v-if="isReportDialogOpen" class="report-dialog-backdrop">
      <div
        class="report-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="report-dialog-title"
        aria-describedby="report-dialog-desc"
      >
        <div class="report-dialog-icon" aria-hidden="true">
          <!-- 구급차 아이콘 -->
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 17V6H3a1 1 0 0 0-1 1v10h3"/>
            <path d="M14 9h4l4 4v4h-2"/>
            <path d="M9 17h7"/>
            <circle cx="7" cy="17" r="2"/>
            <circle cx="18" cy="17" r="2"/>
            <path d="M8 8.5v5M5.5 11h5"/>
          </svg>
        </div>
        <h2 id="report-dialog-title">119에 신고할까요?</h2>
        <p id="report-dialog-desc">2단계 노출위험 상황입니다.</p>
        <div class="report-dialog-actions">
          <button type="button" class="report-no" @click="answerReport(false)">아니오</button>
          <button type="button" class="report-yes" autofocus @click="answerReport(true)">예</button>
        </div>
      </div>
    </div>
  </main>
</template>
