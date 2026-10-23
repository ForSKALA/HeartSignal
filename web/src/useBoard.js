// 비상 상태 공용 모듈 — rag `/board/current`를 주기적으로 읽고, 새 경보가 뜨면 대피 문구를 음성으로 읽는다.
// 경보 발령·해제는 안전관리자(Swagger /docs)가 한다. 화면은 보여 주고 읽어 줄 뿐이다 (AGENTS.md 2장 1번).
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const BOARD_API_URL = import.meta.env.VITE_BOARD_API_URL || "/board/current";
const POLL_MS = 3000;
const STAGE_LABEL = { 1: "1단계 · 주의", 2: "2단계 · 경고", 3: "3단계 · 위험" };

// 모듈 단위 상태: 어느 화면에서 써도 폴링은 하나만 돈다
const board = ref(null);          // /board/current 응답 (경보 없으면 lines: [])
const lastError = ref("");
let timer = null;
let users = 0;
let spokenFor = "";               // 마지막으로 읽어 준 alarm_id+status (같은 경보를 반복해서 읽지 않음)

async function poll() {
  try {
    const res = await fetch(BOARD_API_URL, { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    board.value = await res.json();
    lastError.value = "";
    autoSpeak();
  } catch (error) {
    lastError.value = error.message;
  }
}

function speechText(b) {
  if (!b || !b.lines?.length) return "";
  const head = b.status === "cleared" ? "경보가 해제되었습니다." : "비상상황입니다.";
  return `${head} ${b.lines.join(". ")}`;
}

// 대피 음성: Voice-AI의 OpenAI TTS(/tts/)로 mp3를 만들어 재생한다. 같은 origin으로 프록시되므로 로그인 쿠키가 그대로 간다.
// Voice-AI 장애·미인증이면 브라우저 TTS(Web Speech)로 대체한다 — 음성 안내는 끊기면 안 된다 (AGENTS.md 2장 4번).
const VOICE_TTS_URL = import.meta.env.VITE_VOICE_TTS_URL || "/tts/";
let player = null;

function speakBrowser(text) {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "ko-KR";
  utter.rate = 0.95;
  window.speechSynthesis.speak(utter);
  return true;
}

async function speak(text) {
  if (!text) return false;
  try {
    const body = new FormData();
    body.append("text", text);
    const res = await fetch(VOICE_TTS_URL, { method: "POST", body, credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { file_path } = await res.json();
    // shortcut: Voice-AI가 파일명을 고정(openai_tts_output.mp3)으로 돌려주므로 캐시를 피하려 시각을 붙인다, 파일명이 요청별로 바뀌면 제거
    const src = new URL(`${file_path}?t=${Date.now()}`, new URL(VOICE_TTS_URL, window.location.origin));
    player?.pause();
    player = new Audio(src.href);
    await player.play();
    return true;
  } catch (error) {
    console.warn("Voice-AI TTS 실패, 브라우저 TTS로 대체:", error.message);
    return speakBrowser(text);
  }
}

function autoSpeak() {
  const b = board.value;
  if (!b?.alarm_id) return;
  const key = `${b.alarm_id}:${b.status}`;
  if (key === spokenFor) return;
  spokenFor = key;
  speak(speechText(b));
}

export function useBoard() {
  onMounted(() => {
    users += 1;
    if (!timer) {
      poll();
      timer = setInterval(poll, POLL_MS);
    }
  });
  onBeforeUnmount(() => {
    users -= 1;
    if (users <= 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  });

  const isActive = computed(() => board.value?.status === "active" && (board.value?.lines?.length ?? 0) > 0);
  const isCleared = computed(() => board.value?.status === "cleared");
  const stageLabel = computed(() => (isActive.value ? STAGE_LABEL[board.value.stage] || `${board.value.stage}단계` : isCleared.value ? "경보 해제" : "1단계 · 평상시"));
  const sourceText = computed(() => {
    const s = board.value?.source;
    return s ? `${s.source}${s.section ? " " + s.section : ""}` : "";
  });
  const replay = () => speak(speechText(board.value));

  return { board, isActive, isCleared, stageLabel, sourceText, lastError, replay };
}
