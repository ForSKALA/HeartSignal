// 브라우저 내장 음성(Web Speech API)으로 경보 문구를 읽어 준다.
// 서버·LLM 없이 동작하므로 장애 시에도 방송이 나간다 (AGENTS.md 2장 4번).
// 브라우저는 사용자가 화면을 한 번도 누르지 않았으면 음성을 막는다 → onBlocked 로 알려 주고, 다음 클릭 때 다시 읽는다.

const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

export const isVoiceSupported = Boolean(synth);

let blockedTexts = [];

function koreanVoice() {
  return synth.getVoices().find((voice) => voice.lang?.toLowerCase().startsWith("ko"));
}

export function speak(text, { repeat = 1, onBlocked } = {}) {
  if (!synth || !text) return;
  for (let i = 0; i < repeat; i += 1) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ko-KR";
    utterance.voice = koreanVoice() || null;
    utterance.rate = 1;
    utterance.onerror = (event) => {
      if (event.error === "not-allowed" && i === 0) {
        blockedTexts.push({ text, repeat });
        onBlocked?.();
      }
    };
    synth.speak(utterance);
  }
}

// 사용자가 화면을 누른 뒤 막혔던 안내를 다시 읽는다
export function replayBlocked() {
  const pending = blockedTexts;
  blockedTexts = [];
  for (const { text, repeat } of pending) speak(text, { repeat });
  return pending.length > 0;
}

export function stopSpeaking() {
  blockedTexts = [];
  synth?.cancel();
}

// ---- 음성 질문: 마이크 녹음 → Voice-AI /voice/stt/ (서버 내 faster-whisper, OpenAI 키 불필요) ----
// 녹음 원본은 화면·서버 어디에도 남기지 않는다 (Voice-AI 는 변환 후 파일 삭제, AGENTS.md 2장 7번).

const STT_URL = `${import.meta.env.VITE_API_BASE_URL || ""}/voice/stt/`;

export const isRecordingSupported =
  typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";

// 녹음을 시작하고, 호출하면 녹음을 끝내고 Blob 을 돌려주는 stop 함수를 돌려준다
export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.start();
  return () =>
    new Promise((resolve) => {
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop()); // 마이크 표시등 끄기
        resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.stop();
    });
}

// 녹음 Blob → 텍스트. 실패하면 Error (status 401 이면 로그인 필요)
export async function transcribe(blob) {
  const form = new FormData();
  // Voice-AI 는 .webm 확장자를 기준으로 wav 파일명을 만든다. ffmpeg 가 실제 형식(Safari mp4 포함)을 알아서 읽는다
  form.append("audio", blob, "question.webm");
  const response = await fetch(STT_URL, { method: "POST", credentials: "include", body: form });
  const data = await response.json().catch(() => null);
  if (!response.ok || data?.error) {
    // Voice-AI 는 변환 실패도 200 + {"error"} 로 준다 → 5xx 는 대개 서버 미실행·연결 실패 (vite proxy 500, Ingress 502·503)
    const message = response.ok
      ? "음성을 인식하지 못했습니다. 다시 말씀해 주세요."
      : response.status >= 500
        ? `음성 인식 서버(Voice-AI)에 연결할 수 없습니다. (${response.status})`
        : `음성 인식 요청에 실패했습니다. (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return (data?.text || "").trim();
}
