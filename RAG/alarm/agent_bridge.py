# P2 에이전트(RAG/agent/) 호출 연결 (명세서 5.1)
#   async def run_agent(alarm: dict) -> list[dict]
#   - alarm 은 사본이다. 에이전트가 고쳐도 저장소에는 반영되지 않는다.
#   - 반환: 실행한 도구 기록. {"tool", "ok", "fallback", "ts", "output"?}
#     output 은 도구별로 아래 필드에 들어간다 (TOOL_FIELDS)
# P2 모듈이 아직 없거나 실패·지연되면 고정 문구(fallback.py)를 유지하고 기록만 남긴다.

import asyncio
import logging
import os
from datetime import datetime

from . import store

logger = logging.getLogger("heartsignal.alarm")

# 도구 출력 → 경보 객체 필드
TOOL_FIELDS = {
    "display_board": "board",
    "notify_manager": "guide_card",
    "notify_foreman": "checklist",
    "report_119": "report",
    "build_briefing": "briefing",
}

# LLM 호출이 여러 번 일어나므로 LLM 타임아웃의 3배까지 기다린다
AGENT_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20")) * 3

try:
    from agent import run_agent  # P2
except ImportError:
    run_agent = None


def _outputs_from(actions: list[dict]) -> dict:
    outputs: dict = {}
    for action in actions:
        field = TOOL_FIELDS.get(action.get("tool"))
        output = action.get("output")
        if not field or not action.get("ok") or output is None:
            continue
        if field == "checklist" and isinstance(output, dict):
            output = output.get("checklist")
        outputs[field] = output
    return outputs


def _strip_output(action: dict) -> dict:
    """actions 기록에는 출력 본문을 빼고 남긴다 (본문은 각 필드에 들어감)"""
    return {k: v for k, v in action.items() if k != "output"}


async def run_for(alarm_id: str, phase: str) -> None:
    """발령('issue')·해제('clear') 직후 백그라운드로 실행한다."""
    alarm = store.snapshot(store.get(alarm_id))
    ts = datetime.now(store.KST).isoformat(timespec="seconds")

    if run_agent is None:
        actions = [{"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": "agent_not_installed"}]
        store.apply_agent_output(alarm_id, phase, {}, actions)
        return

    try:
        actions = await asyncio.wait_for(run_agent(alarm), timeout=AGENT_TIMEOUT_S)
        actions = [a for a in (actions or []) if isinstance(a, dict)]
    except asyncio.TimeoutError:
        actions = [{"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": "timeout"}]
    except Exception as exc:  # 에이전트 장애가 경보를 멈추지 않게 한다
        logger.warning("agent failed: %s", type(exc).__name__)
        actions = [{"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": type(exc).__name__}]

    store.apply_agent_output(alarm_id, phase, _outputs_from(actions), [_strip_output(a) for a in actions])
