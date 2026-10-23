# HeartSignal P2 에이전트 — 도구 7개 (기획서 3.3, 명세서 5.3). 이 외의 도구는 만들지 않는다 (AGENTS.md 2장 2번).
# 모든 문장은 근거 청크에서 가져오고 출처를 붙인다. 근거가 없으면 고정 템플릿 문구 + fallback=True, 출처 없음.
# 119·방송은 모의 발송만: 로그와 반환값뿐, 외부로 보내지 않는다 (AGENTS.md 2장 5번).
# 경보 단계·상태·신고 발송 여부는 절대 바꾸지 않는다 — 입력 alarm 은 사본이며 읽기만 한다.

import logging
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from . import evidence as ev

logger = logging.getLogger("heartsignal.agent")
KST = timezone(timedelta(hours=9))

TOOLS = ("rag_search", "broadcast_tts", "notify_foreman", "notify_manager",
         "report_119", "display_board", "build_briefing")

ZONE_NAMES = {"loading_bay": "출하장", "distillation": "증류탑", "confined_tank": "밀폐공간·탱크"}
NEEDS_SOURCE = "근거 확인 필요"


def _names(alarm: dict) -> tuple[str, str]:
    zone = ZONE_NAMES.get(alarm.get("zone"), str(alarm.get("zone")))
    name, _ = ev.first(alarm.get("substance", ""), "name")
    return zone, (name or str(alarm.get("substance")))


def _record(tool: str, output, sources: list, fallback: bool, **extra) -> dict:
    return {"tool": tool, "ok": True, "fallback": fallback,
            "ts": datetime.now(KST).isoformat(timespec="seconds"),
            "sources": sources, "output": output, **extra}


def _dedupe(sources: list) -> list:
    out = []
    for s in sources:
        if s and s not in out:
            out.append(s)
    return out


# ---- 1. rag_search: 물질·상황별 근거 묶음 (다른 도구가 재사용) ----

def rag_search(alarm: dict) -> dict:
    substance = alarm.get("substance", "")
    bundle = {p: ev.find(substance, p) for p in ev.PURPOSE_SECTIONS}
    bundle["guides_respond"] = ev.find_guides(alarm.get("zone", ""), "respond")
    bundle["guides_resume"] = ev.find_guides(alarm.get("zone", ""), "resume")
    sources = _dedupe([src for hits in bundle.values() for _, src in hits])
    rec = _record("rag_search", {"hits": sum(len(h) for h in bundle.values())}, sources, fallback=not sources)
    rec["bundle"] = bundle
    return rec


# ---- 2. display_board: 전광판 3~4줄 + 출처 1건 ----

BOARD_TEMPLATES = json.loads((Path(__file__).resolve().parent.parent / "prompts" / "board_templates.json").read_text(encoding="utf-8"))


def display_board(alarm: dict, bundle: dict) -> dict:
    """문구는 prompts/board_templates.json (고정 템플릿, AGENTS.md 2장 4번). 근거가 있으면 이격거리 줄과 출처가 붙는다."""
    zone, substance = _names(alarm)
    stage, status = alarm.get("stage"), alarm.get("status")
    fmt = lambda t, **kw: t.format(zone=zone, substance=substance, **kw)
    T = BOARD_TEMPLATES
    if status == "cleared":
        lines = [fmt(t) for t in T["cleared"]["lines"]]
        resume = bundle.get("guides_resume") or []
        if resume:  # 재개 조건 근거(G-78 10.2(14) 등)가 있으면 전광판용 짧은 문구 + 출처
            lines[1] = fmt(T["cleared"]["resume_line"])
            return _record("display_board", {"lines": lines, "source": resume[0][1]}, [resume[0][1]], False)
        return _record("display_board", {"lines": lines, "source": None}, [], True)

    iso = bundle.get("isolation") or []
    if iso:
        dist = ev.isolation_distances(iso[0][0])
        radius = dist.get("소규모") or dist.get("대규모")
        I = T["isolation"]
        lines = [fmt(I["headline"][str(stage if stage in (2, 3) else 3)]),
                 fmt(I["radius"], radius=radius) if radius else fmt(I["no_radius"]),
                 *[fmt(t) for t in I["tail"]]]
        return _record("display_board", {"lines": lines[:4], "source": iso[0][1]}, [iso[0][1]], False)
    lines = [fmt(t) for t in T["stage"][str(stage or 3)]]
    return _record("display_board", {"lines": lines, "source": None}, [], True)


# ---- 3. notify_manager: 관리자 대응 지침 카드 ----

def notify_manager(alarm: dict, bundle: dict) -> dict:
    zone, substance = _names(alarm)
    immediate = [_short(t, 120) for t, _ in (bundle.get("guides_respond") or [])] + \
                [_short(t, 120) for t, _ in (bundle.get("leak_response") or [])[:1]]
    ppe = [_short(t, 120) for t, _ in (bundle.get("ppe") or [])[:1]]
    first_aid = [_short(t, 120) for t, _ in (bundle.get("first_aid_inhalation") or [])[:1]]
    cas = (bundle.get("cas") or [("", None)])[0][0]
    un = (bundle.get("un") or [("", None)])[0][0]
    signal = (bundle.get("ghs_signal") or [("", None)])[0][0]
    report_info = {"substance": substance, "zone": zone, "cas": cas, "un": un, "ghs_signal": signal}
    sources = _dedupe([src for key in ("guides_respond", "leak_response", "ppe", "first_aid_inhalation", "cas", "un", "ghs_signal")
                       for _, src in (bundle.get(key) or [])[:2]])
    card = {"immediate": immediate or [f"{zone} 출입 통제", "비상조치계획 확인"],
            "ppe": ppe, "first_aid": first_aid, "report_info": report_info, "sources": sources}
    if not sources:
        card["note"] = NEEDS_SOURCE
    return _record("notify_manager", card, sources, fallback=not sources)


# ---- 4. report_119: 모의 신고문 (발송 판단은 P3 타이머·관리자 보류가 함) ----

def report_119(alarm: dict, bundle: dict) -> dict:
    zone, substance = _names(alarm)
    cas = (bundle.get("cas") or [("", None)])[0][0]
    un = (bundle.get("un") or [("", None)])[0][0]
    iso = bundle.get("isolation") or []
    aid = bundle.get("first_aid_inhalation") or []
    hazard = bundle.get("ghs_hazard") or []
    headcount = (alarm.get("headcount") or {})
    parts = [f"[모의 119 신고] {alarm.get('issued_at', '')} {zone}에서 {substance} 누출, 경보 {alarm.get('stage')}단계 발령."]
    ident = ", ".join(x for x in (f"CAS {cas}" if cas else "", f"UN {un}" if un else "") if x)
    if ident:
        parts.append(f"물질 식별: {substance} ({ident}).")
    if hazard:
        parts.append(f"유해위험: {_short(hazard[0][0], 80)}.")
    if iso:
        dist = ev.isolation_distances(iso[0][0])
        parts.append("초기이격거리: " + ", ".join(f"{k} {v}" for k, v in dist.items()) + ".")
    if headcount.get("total"):
        parts.append(f"현장 인원 점검 {headcount.get('checked', 0)}/{headcount.get('total')}.")
    if aid:
        parts.append(f"흡입 시 응급조치: {_short(aid[0][0], 100)}.")
    if alarm.get("note"):
        parts.append(f"현장 메모: {alarm['note']}")
    sources = _dedupe([src for key in ("cas", "un", "ghs_hazard", "isolation", "first_aid_inhalation")
                       for _, src in (bundle.get(key) or [])[:1]])
    return _record("report_119", {"text": " ".join(parts), "sources": sources}, sources, fallback=not sources)


# ---- 5. notify_foreman: 작업반장 체크리스트 ----

def notify_foreman(alarm: dict, bundle: dict) -> dict:
    stage, status = alarm.get("stage"), alarm.get("status")
    items = []
    if status == "cleared":
        for text, src in bundle.get("guides_resume") or []:
            items.append({"item": _short(text, 100), "source": src})
        items += [{"item": "재측정 결과 보고", "source": None}, {"item": "작업 재개는 안전관리자 승인 후", "source": None}]
    else:
        for text, src in bundle.get("guides_respond") or []:
            items.append({"item": _short(text, 100), "source": src})
        for text, src in (bundle.get("ppe") or [])[:1]:
            items.append({"item": "보호구: " + _short(text, 80), "source": src})
        items += {1: [{"item": "휴대용 검지기로 재측정", "source": None}, {"item": "주변 점화원 확인", "source": None}],
                  2: [{"item": "작업 중지 지시", "source": None}, {"item": "대피 경로·집결지 확인", "source": None}, {"item": "인원 명단 준비", "source": None}],
                  3: [{"item": "대피 유도", "source": None}, {"item": "집결지 인원 점검 후 결과 입력", "source": None}, {"item": "부상자 확인 후 관리자 보고", "source": None}]}[stage or 3]
    sources = _dedupe([i["source"] for i in items if i["source"]])
    return _record("notify_foreman", {"checklist": items}, sources, fallback=not sources)


# ---- 6. broadcast_tts: 모의 방송 (voice 연동은 확장 — 지금은 문구·로그만) ----

def broadcast_tts(alarm: dict, board: dict | None) -> dict:
    zone, substance = _names(alarm)
    if alarm.get("status") == "cleared":
        text = f"{zone} 경보가 해제되었습니다. 작업 재개는 안전관리자 승인 후 진행하세요."
        sources = []
    elif board and board.get("lines"):
        text = " ".join(board["lines"])
        sources = [board["source"]] if board.get("source") else []
    else:
        text = f"{zone} {substance} 경보입니다. 작업반장 지시에 따르세요."
        sources = []
    bid = f"bc-{uuid.uuid4().hex[:8]}"
    logger.info('{"tool": "broadcast_tts", "mock": true, "broadcast_id": "%s", "len": %d}', bid, len(text))
    return _record("broadcast_tts", {"broadcast_id": bid, "text": text, "repeat": 2 if alarm.get("stage") == 3 else 1},
                   sources, fallback=not sources)


# ---- 7. build_briefing: 소방 인계 브리핑 카드 ----

def build_briefing(alarm: dict, bundle: dict) -> dict:
    zone, substance = _names(alarm)
    summary = [f"{zone} {substance} 누출, 경보 {alarm.get('stage')}단계 ({alarm.get('issued_at', '')})"]
    for key, label in (("ghs_hazard", "유해위험"), ("fire", "소화방법"), ("isolation", "초기이격거리"), ("protective_distance", "방호활동거리")):
        for text, _ in (bundle.get(key) or [])[:1]:
            summary.append(f"{label}: {_short(text, 100)}")
    first_aid = [_short(t, 120) for t, _ in (bundle.get("first_aid_inhalation") or [])[:1]] + \
                [_short(t, 120) for t, _ in (bundle.get("first_aid_skin") or [])[:1]]
    sources = _dedupe([src for key in ("ghs_hazard", "fire", "isolation", "protective_distance", "first_aid_inhalation", "first_aid_skin")
                       for _, src in (bundle.get(key) or [])[:1]])
    card = {"summary": summary, "first_aid": first_aid, "sources": sources}
    if not sources:
        card["note"] = NEEDS_SOURCE
    return _record("build_briefing", card, sources, fallback=not sources)


def _short(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
