# HeartSignal P2 에이전트 — 고정 순서 실행기 (명세서 5.2). LLM 이 도구를 고르지 않는다.
# 입력 alarm 은 사본이며 읽기만 한다. 단계·상태·신고 발송 여부를 바꾸는 코드는 없다 (AGENTS.md 2장 1번).
# 도구 하나가 실패해도 다음 도구는 계속 실행하고, 실패는 기록으로 남긴다.

import logging
from datetime import datetime

from . import tools as T
from .tools import KST

logger = logging.getLogger("heartsignal.agent")

# 단계별 도구 순서 (기획서 3.2). 해제는 status == "cleared" 로 판단
ORDER = {
    1: ("rag_search", "broadcast_tts", "notify_foreman", "notify_manager"),
    2: ("rag_search", "broadcast_tts", "notify_foreman", "notify_manager", "display_board"),
    3: ("rag_search", "report_119", "display_board", "notify_manager", "broadcast_tts", "build_briefing", "notify_foreman"),
    "cleared": ("rag_search", "broadcast_tts", "display_board", "notify_foreman"),
}


def _failed(tool: str, exc: Exception) -> dict:
    logger.warning("agent tool %s failed: %s", tool, type(exc).__name__)
    return {"tool": tool, "ok": False, "fallback": True, "ts": datetime.now(KST).isoformat(timespec="seconds"),
            "reason": type(exc).__name__}


async def run_agent(alarm: dict) -> list[dict]:
    """경보 사본을 받아 단계별 순서대로 도구를 실행하고 기록 목록을 돌려준다."""
    key = "cleared" if alarm.get("status") == "cleared" else int(alarm.get("stage") or 3)
    order = ORDER.get(key, ORDER[3])
    actions: list[dict] = []
    bundle: dict = {}
    board: dict | None = None
    for tool in order:
        try:
            if tool == "rag_search":
                rec = T.rag_search(alarm)
                bundle = rec.pop("bundle", {})
            elif tool == "display_board":
                rec = T.display_board(alarm, bundle)
                board = rec["output"]
            elif tool == "broadcast_tts":
                if board is None and alarm.get("status") != "cleared" and alarm.get("stage") in (2, 3):
                    board = T.display_board(alarm, bundle)["output"]   # 방송 문구는 전광판 문구와 같은 근거
                rec = T.broadcast_tts(alarm, board)
            else:
                rec = getattr(T, tool)(alarm, bundle)
        except Exception as exc:  # 도구 장애가 경보를 멈추지 않게 한다
            rec = _failed(tool, exc)
        actions.append(rec)
    return actions
