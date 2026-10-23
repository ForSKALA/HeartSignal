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
