<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { apiFetch } from "../api";
import { isVoiceSupported, replayBlocked, speak, stopSpeaking } from "../voice";

// 경보 상태는 서버(/alarm/status, /board/current)가 기준이다. 화면은 조회·표시와 사람 조작 요청만 한다.
// 권한 검사는 서버가 하며, role 에 따라 버튼을 숨기는 것은 편의 기능이다.
const POLL_MS = 2500;
const REPORT_HOLD_S = 30; // 서버 store.REPORT_HOLD_S 와 같은 값 (타이머 링 비율 계산용)
const TIMER_CIRCUMFERENCE = 2 * Math.PI * 44; // 타이머 링(r=44) 둘레

// 서버 키(snake_case) → 화면 표시명 (RAG/alarm/models.py 와 같은 키)
const ZONES = { loading_bay: "출하장", distillation: "증류탑", confined_tank: "밀폐공간·탱크" };
// 물질 키는 P1 RAG/data/sources.json 의 substance (안전지침/ PDF 22종, 가나다순)
const SUBSTANCES = {
  n_hexane: "노르말헥산",
  methanol: "메탄올",
  methane: "메테인",
  benzene: "벤젠",
  butadiene: "부타디엔",
  hydrogen_fluoride: "불화수소(불산)",
  sodium_hydroxide: "수산화나트륨",
  hydrogen: "수소",
  styrene: "스티렌 모노머",
  acetylene: "아세틸렌",
  ammonia: "암모니아",
  ethylene: "에틸렌",
  ethylbenzene: "에틸벤젠",
  chlorine: "염소",
  hydrogen_chloride: "염화수소(염산)",
  sulfur_dioxide: "이산화황",
  carbon_monoxide: "일산화탄소",
  xylene: "자일렌",
  toluene: "톨루엔",
  propane: "프로판",
  sulfuric_acid: "황산",
  hydrogen_sulfide: "황화수소",
};
const STAGES = { 1: "주의", 2: "경고", 3: "위험" };
const ROLES = { admin: "안전관리자", foreman: "작업반장", worker: "작업자" };
const HEADLINES = { 1: "주의하세요", 2: "작업을 중지하세요", 3: "대피해주세요" };

const router = useRouter();
const user = ref(null); // { username, role } — /api/auth/check 응답
const alarms = ref([]);
const board = ref(null);
const loadError = ref("");
const notice = ref("");
const busy = ref(false);
const now = ref(Date.now());

const isIssueOpen = ref(false);
const issueForm = ref({ zone: "loading_bay", substance: "propane", stage: 2, note: "" });
const headcounts = ref({}); // alarm_id → { checked, total } 입력값
const confirmClearId = ref(null);
const dismissedReports = ref(new Set()); // 사용자가 닫은 119 신고 창 (report_id)

// 음성 안내: 켜짐 여부는 이 브라우저에만 기억한다
const voiceOn = ref(readVoicePref());
const voiceBlocked = ref(false); // 브라우저가 클릭 전 음성을 막은 상태
const announced = new Set(); // 이미 읽은 경보 (alarm_id, cleared:alarm_id)

function readVoicePref() {
  try {
    return localStorage.getItem("hs-voice") !== "off";
  } catch {
    return true;
  }
}

const role = computed(() => user.value?.role || "worker");
const isAdmin = computed(() => role.value === "admin");
const isForeman = computed(() => role.value === "foreman");

// 진행 중 경보 중 가장 높은 단계 (같으면 최근 발령)
const topAlarm = computed(() =>
  alarms.value.reduce((top, alarm) => (!top || alarm.stage > top.stage ? alarm : top), null),
);
const isCleared = computed(() => !topAlarm.value && board.value?.status === "cleared");
const boardLines = computed(() => board.value?.lines || []);

// 119 신고 대기 창: 서버 report.status 가 pending 인 경보 (3단계에서만 생김)
const pendingReportAlarm = computed(() =>
  alarms.value.find(
    (alarm) => alarm.report?.status === "pending" && !dismissedReports.value.has(alarm.report.report_id),
  ),
);

function zoneName(key) {
  return ZONES[key] || key;
}
function substanceName(key) {
  return SUBSTANCES[key] || key;
}
function secondsUntil(iso) {
  return Math.max(0, Math.ceil((Date.parse(iso) - now.value) / 1000));
}
function timeOf(iso) {
  return iso ? new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "";
}
function reportLabel(report) {
  if (report.status === "pending") return `119 신고 대기 · ${secondsUntil(report.send_at)}초 후 발송 (모의)`;
  if (report.status === "held") return "119 신고 보류됨";
  return "119 신고 발송됨 (모의 — 실제 발송 없음)";
}

// 401 → 로그인 화면, 403 → 권한 없음, 그 외 서버 메시지
function handleError(error) {
  if (error.status === 401) {
    router.push("/login");
    return;
  }
  notice.value = error.status === 403 ? "권한이 없습니다." : error.message;
}

let polling = false;
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const [status, current] = await Promise.allSettled([apiFetch("/alarm/status"), apiFetch("/board/current")]);
    if (status.status === "rejected" && status.reason.status === 401) {
      router.push("/login");
      return;
    }
    if (status.status === "fulfilled") {
      alarms.value = status.value.alarms || [];
      // 인원 점검 입력칸은 처음 본 경보만 서버 값으로 채운다 (입력 중인 값은 덮어쓰지 않음)
      for (const alarm of alarms.value) {
        headcounts.value[alarm.alarm_id] ??= { checked: alarm.headcount?.checked || 0, total: alarm.headcount?.total || 0 };
      }
    }
    if (current.status === "fulfilled") board.value = current.value;
    const failed = [status, current].find((result) => result.status === "rejected");
    loadError.value = failed ? `서버 상태를 불러오지 못했습니다. (${failed.reason.message})` : "";
    announceChanges();
  } finally {
    polling = false;
  }
}

// 새 경보·해제를 전광판 문구로 읽는다 (서버 broadcast_tts 문구 = 전광판 문구, 3단계는 2회)
function announceChanges() {
  if (!voiceOn.value) return;
  const onBlocked = () => (voiceBlocked.value = true);
  for (const alarm of [...alarms.value].reverse()) {
    if (announced.has(alarm.alarm_id)) continue;
    announced.add(alarm.alarm_id);
    const head = `${zoneName(alarm.zone)} ${substanceName(alarm.substance)} ${alarm.stage}단계 ${STAGES[alarm.stage]} 경보입니다.`;
    const lines = alarm.board?.lines || [];
    speak([head, ...lines].join(" "), { repeat: alarm.stage === 3 ? 2 : 1, onBlocked });
  }
  const current = board.value;
  if (current?.status === "cleared" && current.alarm_id && !announced.has(`cleared:${current.alarm_id}`)) {
    announced.add(`cleared:${current.alarm_id}`);
    speak(current.lines.join(" "), { onBlocked });
  }
}

function toggleVoice() {
  voiceOn.value = !voiceOn.value;
  try {
    localStorage.setItem("hs-voice", voiceOn.value ? "on" : "off");
  } catch {
    // 저장이 막힌 브라우저면 이번 화면에서만 적용
  }
  voiceBlocked.value = false;
  if (!voiceOn.value) {
    stopSpeaking();
    return;
  }
  if (!replayBlocked()) speak("음성 안내를 켰습니다.");
  announceChanges();
}

// 브라우저가 음성을 막았으면 화면을 처음 누를 때 다시 읽는다
function onPagePointerDown() {
  if (!voiceBlocked.value) return;
  voiceBlocked.value = false;
  replayBlocked();
}

// 사람이 하는 조작 (발령·보류·해제·인원 점검). 성공하면 바로 다시 조회한다
async function act(path, body, successMessage) {
  if (busy.value) return false;
  busy.value = true;
  try {
    await apiFetch(path, { method: "POST", body });
    notice.value = successMessage;
    await refresh();
    return true;
  } catch (error) {
    handleError(error);
    return false;
  } finally {
    busy.value = false;
  }
}

async function issueAlarm() {
  const { zone, substance, stage, note } = issueForm.value;
  const ok = await act(
    "/alarm",
    { zone, substance, stage: Number(stage), note: note.trim() || null },
    `${zoneName(zone)} ${substanceName(substance)} ${stage}단계 경보를 발령했습니다.`,
  );
  if (ok) {
    isIssueOpen.value = false;
    issueForm.value.note = "";
  }
}

function holdReport(alarm) {
  return act(`/alarm/${alarm.alarm_id}/hold-report`, undefined, "119 신고를 보류했습니다.");
}

async function clearAlarm(alarm) {
  if (confirmClearId.value !== alarm.alarm_id) {
    confirmClearId.value = alarm.alarm_id; // 한 번 더 눌러야 해제
    return;
  }
  confirmClearId.value = null;
  await act(`/alarm/${alarm.alarm_id}/clear`, {}, `${zoneName(alarm.zone)} 경보를 해제했습니다.`);
}

function submitHeadcount(alarm) {
  const { checked, total } = headcounts.value[alarm.alarm_id];
  return act(
    `/alarm/${alarm.alarm_id}/headcount`,
    { checked: Number(checked), total: Number(total) },
    `인원 점검 결과(${checked}/${total})를 입력했습니다.`,
  );
}

function dismissReport(alarm) {
  dismissedReports.value = new Set(dismissedReports.value).add(alarm.report.report_id);
}

let pollTimer = null;
let clockTimer = null;

onMounted(async () => {
  try {
    user.value = await apiFetch("/api/auth/check");
  } catch (error) {
    if (error.status === 401) {
      router.push("/login");
      return;
    }
    loadError.value = `로그인 정보를 확인하지 못했습니다. (${error.message})`;
  }
  document.addEventListener("pointerdown", onPagePointerDown);
  await refresh();
  pollTimer = setInterval(refresh, POLL_MS);
  clockTimer = setInterval(() => (now.value = Date.now()), 1000);
});

onBeforeUnmount(() => {
  clearInterval(pollTimer);
  clearInterval(clockTimer);
  document.removeEventListener("pointerdown", onPagePointerDown);
  stopSpeaking();
});
</script>

<template>
  <main
    class="status-page"
    :class="{
      'is-caution': topAlarm?.stage === 1,
      'is-exposure-risk': topAlarm && topAlarm.stage >= 2,
    }"
  >
    <header class="status-topbar">
      <RouterLink class="site-brand" to="/home">HeartSignal</RouterLink>
      <div class="status-actions">
        <span v-if="user" class="user-chip">{{ user.username }} · {{ ROLES[role] || role }}</span>
        <button
          v-if="isVoiceSupported"
          type="button"
          class="voice-toggle"
          :class="{ 'is-off': !voiceOn, 'is-blocked': voiceBlocked }"
          :aria-pressed="voiceOn"
          @click="toggleVoice"
        >
          {{ voiceBlocked ? "🔊 눌러서 음성 듣기" : voiceOn ? "🔊 음성 안내" : "🔇 음성 꺼짐" }}
        </button>
        <RouterLink class="chat-link" to="/chatbot">안전 정보 묻기</RouterLink>
        <span class="level-badge">
          <span class="level-dot"></span>
          {{ topAlarm ? `${topAlarm.stage}단계 · ${STAGES[topAlarm.stage]}` : "평상시" }}
        </span>
      </div>
    </header>

    <section class="status-card" aria-live="polite">
      <div class="status-icon" aria-hidden="true">{{ topAlarm ? "!" : "✓" }}</div>
      <p class="eyebrow">CURRENT STATUS</p>
      <h1>{{ topAlarm ? HEADLINES[topAlarm.stage] : isCleared ? "경보 해제" : "평상시" }}</h1>
      <p v-if="topAlarm" class="status-subtitle">
        {{ zoneName(topAlarm.zone) }} · {{ substanceName(topAlarm.substance) }} · {{ topAlarm.stage }}단계
        {{ STAGES[topAlarm.stage] }}
      </p>
      <!-- 전광판 문구 (/board/current) — 진행 중 경보 또는 해제 후 60초 -->
      <ul v-if="boardLines.length" class="board-lines">
        <li v-for="(line, i) in boardLines" :key="i">{{ line }}</li>
      </ul>
      <p v-else class="status-description">
        현재 위험 상황이 아닙니다.<br />주변을 살피며 평소처럼 이용해 주세요.
      </p>
      <p class="status-note">
        <template v-if="loadError">{{ loadError }}</template>
        <template v-else-if="topAlarm">
          진행 중 경보 {{ alarms.length }}건 · 안전관리자·작업반장 지시에 따르세요
        </template>
        <template v-else>위험 신호 없음 · 서버 경보 상태를 {{ POLL_MS / 1000 }}초마다 확인합니다</template>
      </p>
    </section>

    <!-- 진행 중 경보 목록: 작업자는 상태만, 작업반장은 체크리스트·인원 점검, 안전관리자는 보류·해제 -->
    <section v-if="alarms.length" class="alarm-list" aria-label="진행 중 경보">
      <article v-for="alarm in alarms" :key="alarm.alarm_id" class="alarm-item" :class="`stage-${alarm.stage}`">
        <!-- 왼쪽: 경보 정보·조작 / 오른쪽: 체크리스트 (좁은 화면에서는 위아래) -->
        <div class="alarm-item-main">
          <header class="alarm-item-head">
            <span class="alarm-stage">{{ alarm.stage }}단계 · {{ STAGES[alarm.stage] }}</span>
            <h2>{{ zoneName(alarm.zone) }} · {{ substanceName(alarm.substance) }}</h2>
            <span class="alarm-time">{{ timeOf(alarm.issued_at) }} 발령</span>
          </header>
          <p v-if="alarm.note" class="alarm-note">{{ alarm.note }}</p>

          <p v-if="alarm.report" class="alarm-report" :class="`is-${alarm.report.status}`">
            {{ reportLabel(alarm.report) }}
          </p>
          <p class="alarm-headcount">인원 점검 {{ alarm.headcount?.checked ?? 0 }} / {{ alarm.headcount?.total ?? 0 }}</p>

          <form
            v-if="isForeman && headcounts[alarm.alarm_id]"
            class="headcount-form"
            @submit.prevent="submitHeadcount(alarm)"
          >
            <label>
              확인 인원
              <input v-model.number="headcounts[alarm.alarm_id].checked" type="number" min="0" max="10000" required />
            </label>
            <label>
              전체 인원
              <input v-model.number="headcounts[alarm.alarm_id].total" type="number" min="0" max="10000" required />
            </label>
            <button type="submit" :disabled="busy">인원 점검 입력</button>
          </form>

          <div v-if="isAdmin" class="alarm-actions">
            <button
              v-if="alarm.report?.status === 'pending'"
              type="button"
              class="btn-hold"
              :disabled="busy"
              @click="holdReport(alarm)"
            >
              119 신고 보류
            </button>
            <button type="button" class="btn-clear" :disabled="busy" @click="clearAlarm(alarm)">
              {{ confirmClearId === alarm.alarm_id ? "정말 해제할까요? 한 번 더 누르세요" : "경보 해제" }}
            </button>
          </div>
        </div>

        <div v-if="isForeman || isAdmin" class="alarm-checklist">
          <p class="alarm-section-title">체크리스트</p>
          <ul>
            <li v-for="(entry, i) in alarm.checklist" :key="i">
              {{ entry.item }}
              <span v-if="entry.source" class="alarm-source">
                {{ entry.source.source }} {{ entry.source.section }}
              </span>
            </li>
          </ul>
        </div>

        <!-- 관리자 대응 지침 (P2 에이전트 guide_card.sections, 각 섹션은 RAG 답변 + 출처) -->
        <section v-if="isAdmin && alarm.guide_card?.sections?.length" class="alarm-guide" aria-label="관리자 대응 지침">
          <p class="alarm-section-title">관리자 대응 지침</p>
          <div class="guide-sections">
            <article
              v-for="section in alarm.guide_card.sections"
              :key="section.id"
              class="guide-section"
              :class="{ 'is-handoff': section.handoff }"
            >
              <h3>
                {{ section.title }}
                <span v-if="section.needs_review" class="guide-review">검토 필요</span>
              </h3>
              <!-- handoff 이면 answer 에 "확인된 자료가 없습니다" 문구가 이미 들어 있음 -->
              <p class="guide-answer">{{ section.answer }}</p>
              <ul v-if="section.sources?.length" class="guide-sources" aria-label="출처">
                <li v-for="(src, i) in section.sources" :key="i">📄 {{ src.source }} {{ src.section }}</li>
              </ul>
            </article>
          </div>
        </section>
      </article>
    </section>

    <button v-if="isAdmin" class="emergency-button" type="button" @click="isIssueOpen = true">
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <path d="M10 21h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      경보 발령
    </button>

    <p v-if="notice" class="emergency-notice" role="status" @click="notice = ''">{{ notice }}</p>

    <!-- 경보 발령 (안전관리자) -->
    <div v-if="isIssueOpen" class="report-dialog-backdrop" @click.self="isIssueOpen = false">
      <form class="report-dialog issue-dialog" aria-labelledby="issue-dialog-title" @submit.prevent="issueAlarm">
        <h2 id="issue-dialog-title">경보 발령</h2>
        <label>
          구역
          <select v-model="issueForm.zone">
            <option v-for="(name, key) in ZONES" :key="key" :value="key">{{ name }}</option>
          </select>
        </label>
        <label>
          물질
          <select v-model="issueForm.substance">
            <option v-for="(name, key) in SUBSTANCES" :key="key" :value="key">{{ name }}</option>
          </select>
        </label>
        <fieldset class="stage-picker">
          <legend>단계</legend>
          <label v-for="(name, stage) in STAGES" :key="stage" :class="`stage-${stage}`">
            <input v-model.number="issueForm.stage" type="radio" name="stage" :value="Number(stage)" />
            {{ stage }}단계 {{ name }}
          </label>
        </fieldset>
        <p v-if="issueForm.stage === 3" class="issue-hint">3단계는 발령 30초 뒤 119 모의 신고가 발송됩니다.</p>
        <label>
          메모 (선택)
          <textarea v-model="issueForm.note" rows="2" maxlength="200"></textarea>
        </label>
        <div class="report-dialog-actions">
          <button type="button" class="report-cancel" @click="isIssueOpen = false">취소</button>
          <button type="submit" class="report-confirm" :disabled="busy">발령</button>
        </div>
      </form>
    </div>

    <!-- 119 신고 대기 (서버 report.status = pending, 3단계에서만) -->
    <div v-if="pendingReportAlarm && !isIssueOpen" class="report-dialog-backdrop">
      <div
        class="report-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="report-dialog-title"
        aria-describedby="report-dialog-desc"
      >
        <!-- 원형 카운트다운 타이머: send_at 까지 남은 시간만큼 링이 줄어듦 -->
        <div
          class="report-timer"
          role="timer"
          :aria-label="`${secondsUntil(pendingReportAlarm.report.send_at)}초 남음`"
        >
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle class="report-timer-track" cx="50" cy="50" r="44" />
            <circle
              class="report-timer-progress"
              cx="50"
              cy="50"
              r="44"
              :stroke-dasharray="TIMER_CIRCUMFERENCE"
              :stroke-dashoffset="
                TIMER_CIRCUMFERENCE * (1 - secondsUntil(pendingReportAlarm.report.send_at) / REPORT_HOLD_S)
              "
            />
          </svg>
          <span class="report-timer-value">
            {{ secondsUntil(pendingReportAlarm.report.send_at) }}<small>초</small>
          </span>
        </div>
        <h2 id="report-dialog-title">잠시 후 119 신고가 접수됩니다</h2>
        <p id="report-dialog-desc">
          {{ zoneName(pendingReportAlarm.zone) }} {{ substanceName(pendingReportAlarm.substance) }} 3단계 경보<br />
          (모의 신고 — 실제로 발송되지 않습니다)
        </p>
        <div class="report-dialog-actions">
          <button type="button" class="report-cancel" @click="dismissReport(pendingReportAlarm)">닫기</button>
          <button
            v-if="isAdmin"
            type="button"
            class="report-confirm"
            :disabled="busy"
            @click="holdReport(pendingReportAlarm)"
          >
            신고 보류
          </button>
        </div>
      </div>
    </div>
  </main>
</template>
