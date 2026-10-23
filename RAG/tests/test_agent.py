# [P2] 에이전트: 도구 7개 고정·경계(발령/해제·단계 변경 없음)·P3 형태 검사 통과·S1 시나리오
import asyncio
import copy
import inspect
import json
import re
from pathlib import Path

import pytest
from langchain_core.documents import Document

import agent
from agent import evidence, runner, tools
from alarm import agent_bridge

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"


def _doc(text, source, section, substance=None, doc_type="emergency"):
    return Document(page_content=text, metadata={"source": source, "section": section, "substance": substance, "doc_type": doc_type})


class _DS:
    def __init__(self, docs):
        self._dict = {str(i): d for i, d in enumerate(docs)}


class _Store:
    def __init__(self, docs):
        self.docstore = _DS(docs)


CORPUS = [
    _doc("프로판 | 기본 물질 정보>물질명 프로판", "안전지침/프로판.pdf", "기본 물질 정보>물질명", "propane"),
    _doc("프로판 | 기본 물질 정보>CAS번호 74-98-6", "안전지침/프로판.pdf", "기본 물질 정보>CAS번호", "propane"),
    _doc("프로판 | 기본 물질 정보>UN번호 1978", "안전지침/프로판.pdf", "기본 물질 정보>UN번호", "propane"),
    _doc("프로판 | GHS정보>신호어 위험", "안전지침/프로판.pdf", "GHS정보>신호어", "propane"),
    _doc("프로판 | GHS정보>유해위험문구 극인화성 가스", "안전지침/프로판.pdf", "GHS정보>유해위험문구", "propane"),
    # 프로판 안전지침에는 누출·응급조치 항목이 없다 → MSDS 보완 원문으로 대체
    _doc("안전보건공단 MSDS 프로판 | 4. 응급조치요령>다. 흡입했을 때\n신선한 공기가 있는 곳으로 옮기고 호흡하기 쉬운 자세로 안정을 취한다.",
         "안전보건공단 MSDS 프로판", "4. 응급조치요령>다. 흡입했을 때", "propane"),
    _doc("안전보건공단 MSDS 프로판 | 6. 누출사고시 대처방법>가. 인체를 보호하기 위해 필요한 조치사항 및 보호구\n점화원을 제거하고 누출 지역을 환기시킨다.",
         "안전보건공단 MSDS 프로판", "6. 누출사고시 대처방법>가. 인체를 보호하기 위해 필요한 조치사항 및 보호구", "propane"),
    _doc("안전보건공단 MSDS 프로판 | 8. 노출방지 및 개인보호구>다. 개인보호구\n공기호흡기, 내화학성 장갑", "안전보건공단 MSDS 프로판", "8. 노출방지 및 개인보호구>다. 개인보호구", "propane"),
    _doc("암모니아 | 누출 시 대처요령>초기이격거리 • 소규모: 반경 30m • 대규모: 반경 150m", "안전지침/암모니아.pdf", "누출 시 대처요령>초기이격거리", "ammonia"),
    _doc("암모니아 | 기본 물질 정보>물질명 암모니아", "안전지침/암모니아.pdf", "기본 물질 정보>물질명", "ammonia"),
    _doc("암모니아 | 응급조치>흡입 신선한 공기, 산소 공급", "안전지침/암모니아.pdf", "응급조치>흡입", "ammonia"),
    _doc("유해·위험물 탱크로리 기술지침 | 10.2(13)\n출하장에서 인화성 물질이 누출되었을 경우에는 출하를 중단하고 운행중인 전 차량 및 내연기관의 시동을 끄고 점화원을 제거한다.",
         "KOSHA GUIDE G-78-2021", "10.2(13)", None, "guide"),
    _doc("유해·위험물 탱크로리 기술지침 | 10.2(14)\n출하중 인화성 물질이 누출되었을 때에는 반드시 가스 감지기로 가스 농도를 측정하여 안전여부를 확인한 후 다음 작업을 진행한다.",
         "KOSHA GUIDE G-78-2021", "10.2(14)", None, "guide"),
]


@pytest.fixture(autouse=True)
def _configured():
    agent.configure(_Store(CORPUS))
    yield
    agent.configure()


def _alarm(**over):
    base = {"alarm_id": "al-1", "zone": "loading_bay", "substance": "propane", "stage": 3, "note": "3번 출하대",
            "status": "active", "issued_by": "17", "issued_at": "2026-10-23T14:02:11+09:00",
            "report": {"report_id": "r-1", "status": "pending", "send_at": "..."}, "headcount": {"checked": 12, "total": 12}, "actions": []}
    base.update(over)
    return base


# ---- 경계 ----

def test_exactly_seven_tools_from_the_plan():
    assert set(tools.TOOLS) == {"rag_search", "broadcast_tts", "notify_foreman", "notify_manager", "report_119", "display_board", "build_briefing"}
    assert len(tools.TOOLS) == 7
    assert all(tool in tools.TOOLS for order in runner.ORDER.values() for tool in order)


def test_agent_package_never_imports_alarm_or_calls_issue_clear():
    for path in AGENT_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+alarm", src, re.M), path.name
        assert not re.search(r"\b(create|clear|hold_report|set_headcount|apply_agent_output)\s*\(", src), path.name


def test_run_agent_does_not_mutate_alarm_stage_status_or_report():
    alarm = _alarm()
    before = copy.deepcopy(alarm)
    asyncio.run(runner.run_agent(alarm))
    assert alarm == before


# ---- S1: 출하장 프로판 3단계 ----

def test_s1_stage3_runs_all_tools_in_order_with_sources():
    actions = asyncio.run(runner.run_agent(_alarm()))
    assert [a["tool"] for a in actions] == list(runner.ORDER[3])
    by = {a["tool"]: a for a in actions}
    assert all(a["ok"] for a in actions)
    # 출처: 전광판(프로판은 이격거리 항목 없음 → 템플릿·fallback), 신고문(CAS·UN·GHS), 지침 카드(G-78 10.2(13))
    assert by["display_board"]["fallback"] is True and by["display_board"]["output"]["source"] is None
    report = by["report_119"]["output"]
    assert "CAS 74-98-6" in report["text"] and "UN 1978" in report["text"] and "12/12" in report["text"]
    assert {"source": "안전지침/프로판.pdf", "section": "기본 물질 정보>CAS번호"} in report["sources"]
    card = by["notify_manager"]["output"]
    assert any("출하를 중단" in s for s in card["immediate"])
    assert {"source": "KOSHA GUIDE G-78-2021", "section": "10.2(13)"} in card["sources"]
    assert card["first_aid"] and "신선한 공기" in card["first_aid"][0]   # MSDS 대체 근거
    checklist = by["notify_foreman"]["output"]["checklist"]
    assert checklist[0]["source"] == {"source": "KOSHA GUIDE G-78-2021", "section": "10.2(13)"}
    assert by["broadcast_tts"]["output"]["broadcast_id"].startswith("bc-")


def test_outputs_pass_p3_validators():
    actions = asyncio.run(runner.run_agent(_alarm()))
    outputs, records = agent_bridge._collect(actions)
    assert set(outputs) == {"report", "board", "guide_card", "briefing", "checklist"}
    assert not any(r.get("reason") == "bad_output" for r in records)
    assert len(outputs["board"]["lines"]) <= agent_bridge.BOARD_MAX_LINES


def test_ammonia_board_uses_isolation_distance_with_source():
    actions = asyncio.run(runner.run_agent(_alarm(substance="ammonia", stage=3)))
    board = next(a for a in actions if a["tool"] == "display_board")
    assert board["fallback"] is False
    assert any("30m" in line for line in board["output"]["lines"])
    assert board["output"]["source"] == {"source": "안전지침/암모니아.pdf", "section": "누출 시 대처요령>초기이격거리"}


def test_cleared_phase_gives_resume_checklist_from_g78():
    actions = asyncio.run(runner.run_agent(_alarm(status="cleared")))
    assert [a["tool"] for a in actions] == list(runner.ORDER["cleared"])
    checklist = next(a for a in actions if a["tool"] == "notify_foreman")["output"]["checklist"]
    assert checklist[0]["source"] == {"source": "KOSHA GUIDE G-78-2021", "section": "10.2(14)"}
    board = next(a for a in actions if a["tool"] == "display_board")["output"]
    assert "해제" in board["lines"][0]


def test_unconfigured_agent_falls_back_to_templates_without_sources():
    agent.configure()
    actions = asyncio.run(runner.run_agent(_alarm()))
    assert all(a["ok"] and a["fallback"] for a in actions)
    assert all(a["sources"] == [] for a in actions)
    outputs, records = agent_bridge._collect(actions)
    assert "board" in outputs and not any(r.get("reason") == "bad_output" for r in records)


def test_tool_failure_is_recorded_and_others_continue(monkeypatch):
    def boom(alarm, bundle):
        raise RuntimeError("x")
    monkeypatch.setattr(tools, "notify_manager", boom)
    actions = asyncio.run(runner.run_agent(_alarm()))
    failed = next(a for a in actions if a["tool"] == "notify_manager")
    assert failed["ok"] is False and failed["reason"] == "RuntimeError"
    assert len(actions) == len(runner.ORDER[3])


def test_isolation_distance_parser():
    assert evidence.isolation_distances("초기이격거리 • 소규모: 반경 30m • 대규모: 반경 150m") == {"소규모": "30m", "대규모": "150m"}
    assert evidence.isolation_distances("자료없음") == {}


# ---- 지침 카드 상세 섹션 (RAG 답변 7개, LLM 없으면 빈 목록) · 전광판 템플릿 파일 ----

def test_sections_empty_without_llm_and_board_lines_come_from_template_file():
    from agent import sections
    sections.configure_llm(None, ())
    actions = asyncio.run(runner.run_agent(_alarm(substance="ammonia", stage=3)))
    card = next(a for a in actions if a["tool"] == "notify_manager")
    assert card["output"]["sections"] == [] and card["sections_n"] == 0
    templates = json.loads((AGENT_DIR.parent / "prompts" / "board_templates.json").read_text(encoding="utf-8"))
    board = next(a for a in actions if a["tool"] == "display_board")["output"]
    assert board["lines"][2:] == templates["isolation"]["tail"]       # 문구는 파일에서 온다
    outputs, records = agent_bridge._collect(actions)
    assert outputs["guide_card"]["sections"] == []                      # P3 검사기 통과, 필드 그대로 전달


def test_sections_fill_seven_answers_with_sources_when_llm_present(monkeypatch):
    import rag_answer
    from agent import sections
    seen = []

    def fake_answer(prompt, store, llm, top_k, extra_stores=(), rewrite_llm=None):
        seen.append(prompt)
        if "보호구" in prompt:
            return {"response": rag_answer.NO_EVIDENCE, "sources": [], "needs_review": False, "handoff": True}
        return {"response": f"답: {prompt[:10]} [문서 1]", "sources": [{"source": "안전지침/암모니아.pdf", "section": "x"}],
                "needs_review": False, "handoff": False}

    monkeypatch.setattr(rag_answer, "answer_with_sources", fake_answer)
    sections.configure_llm(object(), (object(), object()))
    try:
        actions = asyncio.run(runner.run_agent(_alarm(substance="ammonia", stage=3)))
    finally:
        sections.configure_llm(None, ())
    card = next(a for a in actions if a["tool"] == "notify_manager")
    secs = card["output"]["sections"]
    assert [s["id"] for s in secs] == ["substance_info", "initial_response", "evacuation_info", "protective_equipment",
                                       "exposure_response", "report_119", "restart_conditions"]
    assert all("암모니아" in s["question"] for s in secs) and "출하장" in secs[-1]["question"]
    assert card["sections_n"] == 7 and card["sections_handoff"] == 1
    ppe = next(s for s in secs if s["id"] == "protective_equipment")
    assert ppe["handoff"] is True and ppe["sources"] == []
    assert secs[0]["sources"][0]["source"] == "안전지침/암모니아.pdf"
    assert len(seen) == 7


def test_sections_are_skipped_on_clear():
    from agent import sections
    sections.configure_llm(object(), (object(),))
    try:
        actions = asyncio.run(runner.run_agent(_alarm(status="cleared")))
    finally:
        sections.configure_llm(None, ())
    assert all("sections" not in a.get("output", {}) for a in actions if isinstance(a.get("output"), dict))
