# 경보 상태 저장소 (메모리, 시연용 — 서버 재시작 시 사라짐. 명세서 4.2)
# - 발령·인원 점검·보류·해제는 사람이 호출하는 라우터만 이 모듈 함수를 부른다.
# - 에이전트 결과는 apply_agent_output() 으로만 들어오며, stage·status·report.status 는 바꿀 수 없다.

import asyncio
import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from itertools import count

from middleware import ApiError
from . import fallback

KST = timezone(timedelta(hours=9))
REPORT_HOLD_S = 30          # 119 신고 보류 가능 시간 (명세서 9장: 30초)
CLEARED_BOARD_TTL_S = 60    # 해제 후 전광판에 해제 문구를 보여 주는 시간

_alarms: dict[str, dict] = {}
_seq = count(1)
_report_seq = count(1)
_tasks: set[asyncio.Task] = set()

audit = logging.getLogger("heartsignal.audit")
if not audit.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    audit.addHandler(_handler)
    audit.setLevel(logging.INFO)
    audit.propagate = False


def now() -> datetime:
    return datetime.now(KST)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def audit_log(alarm: dict, tool: str, tool_result: str, actor: str) -> None:
    """경보 감사 로그 한 줄 (AGENTS.md 7.5). actor: 'agent' 또는 사람 sub"""
    audit.info(json.dumps({
        "ts": _iso(now()),
        "alarm_id": alarm["alarm_id"],
        "zone": alarm["zone"],
        "substance": alarm["substance"],
        "stage": alarm["stage"],
        "tool": tool,
        "tool_result": tool_result,
        "actor": actor,
    }, ensure_ascii=False))


def spawn(coro) -> None:
    """백그라운드 작업 실행 (참조를 잡아 두어 중간에 사라지지 않게 한다)"""
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reset() -> None:
    """테스트용 초기화"""
    _alarms.clear()


def _get(alarm_id: str) -> dict:
    alarm = _alarms.get(alarm_id)
    if alarm is None:
        raise ApiError(404, "NOT_FOUND", "경보를 찾을 수 없습니다.")
    _refresh_report(alarm)
    return alarm


def snapshot(alarm: dict) -> dict:
    """외부(응답·에이전트)에는 사본만 넘긴다"""
    return copy.deepcopy(alarm)


# ========= 119 신고 (모의 발송) =========

def _new_report(alarm: dict, issued: datetime) -> dict:
    return {
        "report_id": f"r-{next(_report_seq):04d}",
        "status": "pending",
        # 초 단위로 자르면 보류 시간이 최대 1초 짧아지므로 밀리초까지 둔다
        "send_at": (issued + timedelta(seconds=REPORT_HOLD_S)).isoformat(timespec="milliseconds"),
        "text": fallback.report_text(alarm),
        "sources": [],
        "headcount": None,
        "followups": [],
    }


def _refresh_report(alarm: dict) -> None:
    """보류 시간이 지난 pending 신고를 sent 로 바꾼다. 타이머와 조회 양쪽에서 불러도 한 번만 발송된다."""
    report = alarm.get("report")
    if not report or report["status"] != "pending":
        return
    if now() >= datetime.fromisoformat(report["send_at"]):
        report["status"] = "sent"
        report["sent_at"] = _iso(now())
        # 실제 외부 발송 없음 (AGENTS.md 2장 5번): 로그 + 화면 표시만
        audit_log(alarm, "report_119", f"sent {report['report_id']} (mock)", "system")


async def _report_timer(alarm_id: str) -> None:
    await asyncio.sleep(REPORT_HOLD_S)
    alarm = _alarms.get(alarm_id)
    if alarm:
        _refresh_report(alarm)


# ========= 사람이 하는 일 =========

def create(zone: str, substance: str, stage: int, note: str | None, actor: str) -> dict:
    issued = now()
    alarm_id = f"al-{issued:%Y%m%d}-{next(_seq):04d}"
    alarm = {
        "alarm_id": alarm_id,
        "zone": zone,
        "substance": substance,
        "stage": stage,
        "note": note,
        "status": "active",
        "issued_by": actor,
        "issued_at": _iso(issued),
        "cleared_by": None,
        "cleared_at": None,
        "board": None,
        "guide_card": None,
        "checklist": [],
        "briefing": None,
        "report": None,
        "headcount": {"checked": 0, "total": 0},
        "actions": [],
    }
    # 에이전트가 끝나기 전에도 화면이 비지 않도록 고정 문구를 먼저 넣는다
    alarm["board"] = {"lines": fallback.board_lines(alarm), "source": None}
    alarm["guide_card"] = fallback.guide_card(alarm)
    alarm["checklist"] = fallback.checklist(alarm)
    if stage == 3:
        alarm["report"] = _new_report(alarm, issued)

    _alarms[alarm_id] = alarm
    audit_log(alarm, "issue", "active", actor)
    if alarm["report"]:
        spawn(_report_timer(alarm_id))
    return alarm


def get(alarm_id: str) -> dict:
    return _get(alarm_id)


def list_active() -> list[dict]:
    active = [a for a in _alarms.values() if a["status"] == "active"]
    for alarm in active:
        _refresh_report(alarm)
    return sorted(active, key=lambda a: a["issued_at"], reverse=True)


def set_headcount(alarm_id: str, checked: int, total: int, actor: str) -> dict:
    alarm = _get(alarm_id)
    if alarm["status"] != "active":
        raise ApiError(409, "CONFLICT", "해제된 경보입니다.")
    alarm["headcount"] = {"checked": checked, "total": total}
    report = alarm.get("report")
    if report:
        if report["status"] == "sent":
            # 이미 발송된 신고에는 후속 보고로 덧붙인다 (모의)
            report["followups"].append({"headcount": f"{checked}/{total}", "ts": _iso(now())})
        report["headcount"] = f"{checked}/{total}"
    audit_log(alarm, "headcount", f"{checked}/{total}", actor)
    return alarm


def hold_report(alarm_id: str, actor: str) -> dict:
    alarm = _get(alarm_id)
    report = alarm.get("report")
    if not report:
        raise ApiError(409, "CONFLICT", "보류할 119 신고가 없습니다. (3단계 경보에서만 신고)")
    if report["status"] == "sent":
        raise ApiError(409, "CONFLICT", "이미 발송된 신고입니다.")
    if report["status"] == "pending":
        report["status"] = "held"
        report["held_by"] = actor
        report["held_at"] = _iso(now())
        audit_log(alarm, "hold_report", f"held {report['report_id']}", actor)
    return alarm


def clear(alarm_id: str, note: str | None, actor: str) -> dict:
    alarm = _get(alarm_id)
    if alarm["status"] != "active":
        raise ApiError(409, "CONFLICT", "이미 해제된 경보입니다.")
    alarm["status"] = "cleared"
    alarm["cleared_by"] = actor
    alarm["cleared_at"] = _iso(now())
    if note:
        alarm["clear_note"] = note
    # 해제 전 발송되지 않은 신고는 더 이상 보내지 않는다
    report = alarm.get("report")
    if report and report["status"] == "pending":
        report["status"] = "held"
        report["held_by"] = actor
        report["held_at"] = alarm["cleared_at"]
        audit_log(alarm, "hold_report", f"held {report['report_id']} (cleared)", actor)
    alarm["board"] = {"lines": fallback.board_lines(alarm), "source": None}
    audit_log(alarm, "clear", "cleared", actor)
    return alarm


# ========= 에이전트 결과 반영 =========

def apply_agent_output(alarm_id: str, phase: str, outputs: dict, actions: list[dict]) -> None:
    """에이전트 결과 중 허용된 필드만 반영한다. stage·status·report.status 는 여기서 바뀌지 않는다.
    phase: 'issue'(발령 대응) | 'clear'(해제 대응). 해제 뒤 늦게 도착한 발령 대응 결과는 버린다."""
    alarm = _alarms.get(alarm_id)
    if alarm is None:
        return
    if phase == "issue" and alarm["status"] != "active":
        return

    if outputs.get("board"):
        alarm["board"] = outputs["board"]
    if outputs.get("guide_card"):
        alarm["guide_card"] = outputs["guide_card"]
    if outputs.get("checklist"):
        alarm["checklist"] = outputs["checklist"]
    if outputs.get("briefing"):
        alarm["briefing"] = outputs["briefing"]
    report_out = outputs.get("report")
    if report_out and alarm.get("report"):
        # 신고문·출처만 갱신. 발송 여부는 타이머와 관리자 보류만 결정한다
        alarm["report"]["text"] = report_out.get("text", alarm["report"]["text"])
        alarm["report"]["sources"] = report_out.get("sources", alarm["report"]["sources"])

    for action in actions:
        alarm["actions"].append(action)
        audit_log(alarm, action.get("tool", "?"),
                  ("ok" if action.get("ok") else "fail") + (" fallback" if action.get("fallback") else ""),
                  "agent")


# ========= 전광판 =========

def board_for(zone: str | None) -> dict:
    """구역(생략 시 전체)에서 가장 높은 단계의 진행 중 경보 문구. 없으면 최근 해제 문구, 그것도 없으면 빈 줄."""
    candidates = [a for a in _alarms.values() if zone is None or a["zone"] == zone]
    active = [a for a in candidates if a["status"] == "active"]
    if active:
        alarm = max(active, key=lambda a: (a["stage"], a["issued_at"]))
    else:
        limit = now() - timedelta(seconds=CLEARED_BOARD_TTL_S)
        recent = [a for a in candidates
                  if a["status"] == "cleared" and datetime.fromisoformat(a["cleared_at"]) >= limit]
        alarm = max(recent, key=lambda a: a["cleared_at"]) if recent else None

    if alarm is None:
        return {"zone": zone, "lines": [], "source": None, "stage": None, "status": None,
                "alarm_id": None, "updated_at": _iso(now())}
    board = alarm["board"] or {"lines": [], "source": None}
    return {
        "zone": alarm["zone"],
        "lines": board.get("lines", []),
        "source": board.get("source"),
        "stage": alarm["stage"],
        "status": alarm["status"],
        "alarm_id": alarm["alarm_id"],
        "updated_at": _iso(now()),
    }
