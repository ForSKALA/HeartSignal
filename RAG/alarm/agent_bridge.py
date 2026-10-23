# P2 에이전트(RAG/agent/) 호출 연결 (명세서 5.1)
#   async def run_agent(alarm: dict) -> list[dict]
#   - alarm 은 사본이다. 에이전트가 고쳐도 저장소에는 반영되지 않는다.
#   - 반환: 실행한 도구 기록. {"tool", "ok", "fallback", "ts", "sources"?, "output"?}
#     output 은 형태를 검사한 뒤 도구별로 아래 필드에 들어간다 (TOOL_FIELDS)
# P2 모듈이 아직 없거나 실패·지연되거나 출력 형태가 틀리면 고정 문구(fallback.py)를 유지하고 기록만 남긴다.

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
BOARD_MAX_LINES = 4

# LLM 호출이 여러 번 일어나므로 LLM 타임아웃의 3배까지 기다린다
AGENT_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20")) * 3


def _load_agent():
    """(run_agent, 사용 불가 사유). 에이전트 import 오류가 RAG 서버 기동을 막지 않게 하되, 원인은 로그로 드러낸다."""
    try:
        from agent import run_agent as fn  # P2
        return fn, None
    except ModuleNotFoundError as exc:
        if exc.name == "agent":
            return None, "agent_not_installed"
        logger.error("agent import failed: missing module %s", exc.name)
        return None, "agent_import_failed"
    except Exception as exc:
        logger.error("agent import failed: %s", type(exc).__name__)
        return None, "agent_import_failed"


run_agent, AGENT_UNAVAILABLE = _load_agent()


# ========= 출력 형태 검사 (틀리면 None → 고정 문구 유지) =========

def _is_source(value) -> bool:
    return value is None or (isinstance(value, dict) and isinstance(value.get("source"), str))


def _board(output):
    if not isinstance(output, dict):
        return None
    lines = output.get("lines")
    if not isinstance(lines, list) or not lines or not all(isinstance(line, str) for line in lines):
        return None
    if not _is_source(output.get("source")):
        return None
    return {"lines": lines[:BOARD_MAX_LINES], "source": output.get("source")}


def _checklist(output):
    items = output.get("checklist") if isinstance(output, dict) else None
    if not isinstance(items, list) or not items:
        return None
    if not all(isinstance(i, dict) and isinstance(i.get("item"), str) and _is_source(i.get("source")) for i in items):
        return None
    return items


def _report(output):
    if not isinstance(output, dict) or not isinstance(output.get("text"), str):
        return None
    sources = output.get("sources", [])
    if not isinstance(sources, list):
        return None
    return {"text": output["text"], "sources": sources}


def _dict(output):
    return output if isinstance(output, dict) else None


VALIDATORS = {
    "board": _board,
    "guide_card": _dict,
    "checklist": _checklist,
    "report": _report,
    "briefing": _dict,
}


def _collect(actions: list[dict]) -> tuple[dict, list[dict]]:
    """반영할 출력과 기록용 action 목록. 형태가 틀린 출력은 버리고 bad_output 으로 기록한다."""
    outputs: dict = {}
    records: list[dict] = []
    for action in actions:
        record = {k: v for k, v in action.items() if k != "output"}  # 본문은 각 필드에 들어감
        field = TOOL_FIELDS.get(action.get("tool"))
        if field and action.get("ok") and action.get("output") is not None:
            value = VALIDATORS[field](action["output"])
            if value is None:
                record.update(ok=False, fallback=True, reason="bad_output")
            else:
                outputs[field] = value
        records.append(record)
    return outputs, records


async def run_for(alarm_id: str, phase: str) -> None:
    """발령('issue')·해제('clear') 직후 백그라운드로 실행한다."""
    alarm = store.snapshot(store.get(alarm_id))
    ts = datetime.now(store.KST).isoformat(timespec="seconds")

    if run_agent is None:
        reason = AGENT_UNAVAILABLE or "agent_not_installed"
        store.apply_agent_output(alarm_id, phase, {}, [
            {"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": reason}])
        return

    try:
        actions = await asyncio.wait_for(run_agent(alarm), timeout=AGENT_TIMEOUT_S)
        actions = [a for a in (actions or []) if isinstance(a, dict)]
    except asyncio.TimeoutError:
        actions = [{"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": "timeout"}]
    except Exception as exc:  # 에이전트 장애가 경보를 멈추지 않게 한다
        logger.warning("agent failed: %s", type(exc).__name__)
        actions = [{"tool": "agent", "ok": False, "fallback": True, "ts": ts, "reason": type(exc).__name__}]

    outputs, records = _collect(actions)
    store.apply_agent_output(alarm_id, phase, outputs, records)
