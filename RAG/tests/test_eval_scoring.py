# P2 평가 스크립트 점수 계산 확인 (서버·LLM 불필요)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from run_eval import load_questions, score, summarize  # noqa: E402

CORE = {"id": "Q3", "type": "core", "keywords": ["10", "15"], "expected_sources": ["노출기준"], "expected_sections": ["728 황화수소"]}
HANDOFF = {"id": "H1", "type": "handoff"}


def test_correct_and_grounded():
    body = {"response": "TWA 10ppm, STEL 15ppm입니다.", "sources": [{"source": "노출기준 고시 별표1", "section": "황화수소"}]}
    assert score(CORE, body) == {"correct": True, "keyword_recall": 1.0, "grounded": True, "section_match": False, "ungrounded_answer": False, "needs_review": False}


def test_section_match_requires_expected_section():
    body = {"response": "10 15", "sources": [{"source": "고용노동부고시 제2020-48호 별표1", "section": "별표1>728 황화수소"}]}
    s = score(CORE, body)
    assert s["grounded"] is False and s["section_match"] is True   # 문서 이름은 다르지만 절은 일치


def test_answer_without_sources_is_ungrounded():
    # 베이스 서버처럼 sources 필드가 없으면 근거성 0, 무근거 답변으로 센다
    s = score(CORE, {"response": "TWA 10ppm입니다."})
    assert s["keyword_recall"] == 0.5 and not s["correct"] and s["ungrounded_answer"]


def test_refusal_is_not_ungrounded():
    s = score(CORE, {"response": "PDF 지식베이스에서 답을 찾을 수 없습니다."})
    assert not s["grounded"] and not s["ungrounded_answer"]


def test_handoff_hit_by_flag_or_phrase():
    assert score(HANDOFF, {"response": "...", "handoff": True}) == {"handoff_hit": True}
    assert score(HANDOFF, {"response": "확인된 자료가 없습니다."}) == {"handoff_hit": True}
    assert score(HANDOFF, {"response": "3번 탱크 압력은 2bar입니다."}) == {"handoff_hit": False}


def test_summary_skips_errors():
    rows = [
        {"type": "core", "latency_ms": 100, **score(CORE, {"response": "10 15", "sources": [{"source": "노출기준"}]})},
        {"type": "core", "latency_ms": 300, "error": "ConnectError"},
        {"type": "handoff", "latency_ms": 200, "handoff_hit": True},
    ]
    s = summarize(rows)
    assert (s["core_n"], s["accuracy_pct"], s["handoff_hit_pct"], s["errors"], s["latency_ms_avg"]) == (1, 100.0, 100.0, 1, 200)


def test_questions_file_is_valid():
    qs = load_questions(Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl")
    assert sum(q["type"] == "core" for q in qs) == 10 and sum(q["type"] == "handoff" for q in qs) == 3
    assert sum(q["type"] == "variant" for q in qs) == 10 and all(q["base"] in {c["id"] for c in qs} for q in qs if q["type"] == "variant")
    assert all(q["keywords"] and q["expected_sources"] and q["expected_sections"] for q in qs if q["type"] in ("core", "variant"))
