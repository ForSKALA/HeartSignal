// 음성 안내: Voice-AI TTS API(/voice/tts/, OpenAI 음성 합성)로 MP3 를 만들어 재생한다.
// API 가 실패하면(OpenAI·Voice-AI 장애, 시간 초과) 브라우저 내장 음성(Web Speech API)으로 읽는다
// → 장애 시에도 경보 방송이 나간다 (AGENTS.md 2장 4번).
// 브라우저는 사용자가 화면을 한 번도 누르지 않았으면 소리를 막는다 → onBlocked 로 알려 주고, 다음 클릭 때 다시 읽는다.
// 여러 문장은 차례대로(큐) 읽는다. 겹쳐 읽지 않는다.

const VOICE_BASE = `${import.meta.env.VITE_API_BASE_URL || ""}/voice`;
const TTS_TIMEOUT_MS = 15000; // 이보다 늦으면 브라우저 음성으로 바로 읽는다 (경보 지연 방지)

const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

export const isVoiceSupported = typeof Audio !== "undefined" || Boolean(synth);

let queue = [];         // 읽을 문장 {text, repeat, onBlocked}
let blockedTexts = [];  // 소리가 막혀 못 읽은 문장 (다음 클릭 때 다시)
let playing = false;
let generation = 0;     // stopSpeaking() 때 증가 → 진행 중이던 재생·합성 결과를 버린다
let currentAudio = null;
let currentDone = null; // 재생 중인 소리를 멈출 때 기다리던 Promise 를 끝내는 함수

function koreanVoice() {
  return synth.getVoices().find((voice) => voice.lang?.toLowerCase().startsWith("ko"));
}

function blockedError() {
  const error = new Error("audio blocked");
  error.name = "NotAllowedError";
  return error;
}

// Voice-AI TTS → 재생할 MP3 의 object URL. 실패하면 null (브라우저 음성으로 대체)
async function synthesize(text) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TTS_TIMEOUT_MS);
  try {
    const form = new FormData();
    form.append("text", text);
    const response = await fetch(`${VOICE_BASE}/tts/`, {
      method: "POST", credentials: "include", body: form, signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || typeof data?.file_path !== "string") return null;
    // Voice-AI 는 같은 파일 이름(/uploads/openai_tts_output.mp3)을 덮어쓴다 → 바로 받아서 메모리에 둔다
    const audio = await fetch(`${VOICE_BASE}${data.file_path}`, { cache: "no-store", signal: controller.signal });
    if (!audio.ok) return null;
    return URL.createObjectURL(await audio.blob());
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function playUrl(url) {
  return new Promise((resolve, reject) => {
    const audio = new Audio(url);
    currentAudio = audio;
    currentDone = resolve;
    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error("audio error"));
    audio.play().catch(reject); // 자동재생 차단이면 NotAllowedError
  });
}

function speakLocal(text) {
  return new Promise((resolve, reject) => {
    if (!synth) return resolve();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ko-KR";
    utterance.voice = koreanVoice() || null;
    utterance.rate = 1;
    currentDone = resolve;
    utterance.onend = () => resolve();
    utterance.onerror = (event) => (event.error === "not-allowed" ? reject(blockedError()) : resolve());
    synth.speak(utterance);
  });
}

async function pump() {
  if (playing) return;
  playing = true;
  try {
    while (queue.length) {
      const item = queue.shift();
      const gen = generation;
      const url = await synthesize(item.text);
      if (gen !== generation) {
        if (url) URL.revokeObjectURL(url);
        continue;
      }
      try {
        for (let i = 0; i < item.repeat && gen === generation; i += 1) {
          try {
            await (url ? playUrl(url) : speakLocal(item.text));
          } catch (error) {
            if (error.name === "NotAllowedError") throw error;
            await speakLocal(item.text); // MP3 재생 오류 → 브라우저 음성
          }
        }
      } catch (error) {
        if (error.name !== "NotAllowedError") throw error;
        blockedTexts.push({ text: item.text, repeat: item.repeat });
        item.onBlocked?.();
      } finally {
        if (url) URL.revokeObjectURL(url);
        currentAudio = null;
        currentDone = null;
      }
    }
  } finally {
    playing = false;
  }
}

export function speak(text, { repeat = 1, onBlocked } = {}) {
  if (!text || !isVoiceSupported) return;
  queue.push({ text, repeat, onBlocked });
  pump();
}

// 사용자가 화면을 누른 뒤 막혔던 안내를 다시 읽는다
export function replayBlocked() {
  const pending = blockedTexts;
  blockedTexts = [];
  for (const { text, repeat } of pending) speak(text, { repeat });
  return pending.length > 0;
}

export function stopSpeaking() {
  generation += 1;
  queue = [];
  blockedTexts = [];
  currentAudio?.pause();
  synth?.cancel();
  currentDone?.(); // 멈춘 재생을 기다리던 pump 를 끝낸다
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
