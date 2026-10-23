# [P2] rag_answer.answer_with_sources — 가짜 검색·LLM 으로 응답 계약 확인
import json

import pytest
from langchain_core.documents import Document
from openai import APITimeoutError

from middleware import ApiError
from rag_answer import NO_EVIDENCE, answer_with_sources, detect_substance, retrieve, rewrite_queries
from conftest import make_token


def _doc(text, source, section=""):
    return Document(page_content=text, metadata={"source": source, "section": section})


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def similarity_search_with_score(self, q, k, filter=None, fetch_k=None):
        self.calls = getattr(self, "calls", []) + [(k, filter, fetch_k)]
        rows = self.rows
        if filter:
            rows = [r for r in rows if r[0].metadata.get("substance") == filter["substance"]]
        return rows[:k]


class _LLM:
    def __init__(self, text="TWA 10ppm, STEL 15ppm", usage=None, exc=None, rewrite_text=""):
        self.text, self.usage, self.exc, self.rewrite_text = text, usage, exc, rewrite_text

    def invoke(self, messages):
        if "검색어 2개로 바꾸세요" in messages[0].content:   # 재작성 요청
            return type("Msg", (), {"content": self.rewrite_text, "usage_metadata": None})()
        if self.exc:
            raise self.exc
        return type("Msg", (), {"content": self.text, "usage_metadata": self.usage})()


ROWS = [
    (_doc("황화수소 TWA 10ppm", "노출기준 고시 별표1", "황화수소"), 0.21),
    (_doc("STEL 15ppm", "노출기준 고시 별표1", "황화수소"), 0.25),   # 같은 출처 → 중복 제거
    (_doc("", "빈청크.pdf"), 0.30),                                     # 빈 본문 → 제외
    (_doc("응급조치: 신선한 공기", "안전지침/황화수소.pdf", "응급조치>흡입"), 0.40),
]


def test_sources_filled_deduped_and_in_order():
    out = answer_with_sources("황화수소 노출기준?", _Store(ROWS), _LLM(), top_k=5)
    assert out["response"] == "TWA 10ppm, STEL 15ppm"
    assert out["sources"] == [
        {"source": "노출기준 고시 별표1", "section": "황화수소"},
        {"source": "안전지침/황화수소.pdf", "section": "응급조치>흡입"},
    ]
    assert out["handoff"] is False and out["needs_review"] is False


def test_top_k_is_respected():
    store = _Store(ROWS)
    out = answer_with_sources("q", store, _LLM(), top_k=1)
    assert out["sources"] == [{"source": "노출기준 고시 별표1", "section": "황화수소"}]


def test_no_hits_is_handoff_without_answer_generation():
    llm = _LLM(exc=AssertionError("answer LLM must not be called"))   # 재작성 호출은 허용, 답변 생성은 금지
    out = answer_with_sources("3번 탱크 압력?", _Store([]), llm, top_k=5)
    assert out == {"response": NO_EVIDENCE, "sources": [], "needs_review": False, "handoff": True}


def test_llm_na_is_handoff_with_empty_sources():
    out = answer_with_sources("휴가 규정?", _Store(ROWS), _LLM(text="N/A"), top_k=5)
    assert out["handoff"] is True and out["sources"] == [] and out["response"] == NO_EVIDENCE


def test_llm_timeout_becomes_503_llm_timeout():
    with pytest.raises(ApiError) as exc:
        answer_with_sources("q", _Store(ROWS), _LLM(exc=APITimeoutError(request=None)), top_k=5)
    assert (exc.value.status, exc.value.code) == (503, "LLM_TIMEOUT")


def test_missing_metadata_gives_empty_strings():
    rows = [(Document(page_content="본문", metadata={}), 0.1)]
    out = answer_with_sources("q", _Store(rows), _LLM(), top_k=5)
    assert out["sources"] == [{"source": "", "section": ""}]


# ---- 메인 앱 경유: 로그 필드와 원문 미기록, 503 NOT_READY ----

def test_rag_query_logs_fields_without_prompt_text(client, rag_module, monkeypatch, access_log):
    monkeypatch.setattr(rag_module, "VECTORSTORE_PDF", _Store(ROWS))
    monkeypatch.setattr(rag_module, "ChatOpenAI", lambda *a, **kw: _LLM(usage={"input_tokens": 120, "output_tokens": 9}))
    client.cookies.set("ACCESS_TOKEN", make_token())
    prompt = "황화수소-원문-XYZ 노출기준?"

    res = client.post("/rag-query", json={"prompt": prompt, "source": "pdf", "top_k": 2})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sources"] == [{"source": "노출기준 고시 별표1", "section": "황화수소"}]
    record = json.loads(access_log[-1])
    assert record["prompt_len"] == len(prompt)
    assert (record["hits"], record["top_score"], record["handoff"]) == (2, 0.21, False)
    assert (record["tokens_in"], record["tokens_out"]) == (120, 9)
    assert "원문-XYZ" not in access_log[-1] and "TWA" not in access_log[-1]


def test_index_not_loaded_is_503_not_ready(client):
    client.cookies.set("ACCESS_TOKEN", make_token())
    res = client.post("/rag-query", json={"prompt": "q", "source": "pdf"})
    assert res.status_code == 503 and res.json()["error"]["code"] == "NOT_READY"


@pytest.mark.parametrize("payload", [{"prompt": "q", "source": "pdf", "top_k": 11}, {"prompt": "x" * 501, "source": "pdf"}])
def test_request_limits_are_422(client, payload):
    client.cookies.set("ACCESS_TOKEN", make_token())
    assert client.post("/rag-query", json=payload).status_code == 422


# ---- 물질 인식·검색 제한 (평가 3행) ----

def _sdoc(text, source, section, substance=None):
    return Document(page_content=text, metadata={"source": source, "section": section, "substance": substance})


@pytest.mark.parametrize("prompt,key", [
    ("염소 들이마신 사람 응급조치는?", "chlorine"),
    ("H2S 몇 ppm까지 괜찮아?", "hydrogen_sulfide"),
    ("황화수소 노출기준이 몇 ppm이야?", "hydrogen_sulfide"),   # '수소'(hydrogen) 보다 긴 이름 우선
    ("메탄올 증기 흡입하면?", "methanol"),                     # '메탄'(methane) 보다 긴 이름 우선
    ("염산 누출 시 조치", "hydrogen_chloride"),
    ("경보 꺼지면 바로 작업 재개해도 돼?", None),
])
def test_detect_substance(prompt, key):
    assert detect_substance(prompt) == key


def test_retrieve_without_substance_is_plain_search():
    store = _Store(ROWS)
    rows, key = retrieve(store, "경보 꺼지면 재개해도 돼?", 5)
    assert key is None and store.calls == [(5, None, None)] and len(rows) == 4


def test_retrieve_merges_substance_chunks_and_general_docs_but_drops_other_substances():
    rows = [
        (_sdoc("염산 응급조치", "안전지침/염화수소(염산).pdf", "응급조치", "hydrogen_chloride"), 0.20),  # 다른 물질 → 제외
        (_sdoc("G-78 일반 절차", "KOSHA GUIDE G-78-2021", "10.2(13)", None), 0.30),                 # 일반 문서 → 포함
        (_sdoc("염소 흡입 응급조치", "안전지침/염소.pdf", "응급조치>흡입", "chlorine"), 0.35),          # 해당 물질 → 포함
        (_sdoc("염소 흡입 응급조치", "안전지침/염소.pdf", "응급조치>흡입", "chlorine"), 0.35),          # 중복 → 제거
    ]
    store = _Store(rows)
    merged, key = retrieve(store, "염소 들이마신 사람 응급조치는?", 5)
    assert key == "chlorine"
    assert [d.metadata["source"] for d, _ in merged] == ["KOSHA GUIDE G-78-2021", "안전지침/염소.pdf"]
    # 물질 필터 검색은 fetch_k 를 크게 주고, 일반 검색은 4배 넓게 본다
    assert (5, {"substance": "chlorine"}, 10_000) in store.calls and (20, None, None) in store.calls


def test_substance_is_logged(client, rag_module, monkeypatch, access_log):
    monkeypatch.setattr(rag_module, "VECTORSTORE_PDF", _Store(ROWS))
    monkeypatch.setattr(rag_module, "ChatOpenAI", lambda *a, **kw: _LLM())
    client.cookies.set("ACCESS_TOKEN", make_token())
    assert client.post("/rag-query", json={"prompt": "황화수소 노출기준?", "source": "pdf"}).status_code == 200
    assert json.loads(access_log[-1])["substance"] == "hydrogen_sulfide"


def test_extra_store_results_are_merged_by_distance():
    law = _Store([(_sdoc("제618조 적정공기 산소 18% 이상", "산업안전보건기준에 관한 규칙", "제618조(정의)", None), 0.15)])
    merged, _ = retrieve(_Store(ROWS), "밀폐공간 들어가도 되는 공기 기준은?", 5, extra_stores=(law, None))
    assert merged[0][0].metadata["source"] == "산업안전보건기준에 관한 규칙"
    assert len(merged) == 1 + 4   # 법령 1 + ROWS 4 (빈 본문 제외는 답변 단계에서), None 저장소는 무시


# ---- 검색어 재작성 (평가 5행) ----

def test_rewrite_queries_parses_two_lines_and_drops_numbering():
    llm = _LLM(rewrite_text="1. 출하장 인화성 물질 누출 시 조치\n2) 탱크로리 출하작업 가스 누출 출하 중단\n3. 세 번째는 버림")
    assert rewrite_queries("출하 중에 프로판이 새면 뭐부터 해?", llm) == [
        "출하장 인화성 물질 누출 시 조치", "탱크로리 출하작업 가스 누출 출하 중단"]


def test_rewrite_failure_returns_empty_and_search_still_runs():
    class Boom:
        def invoke(self, messages):
            raise RuntimeError("down")
    assert rewrite_queries("q", Boom()) == []


def test_retrieve_searches_each_rewrite_and_widens_cap():
    store = _Store(ROWS)
    merged, _ = retrieve(store, "경보 꺼지면 재개해도 돼?", 2, rewrites=("경보 해제 후 작업 재개 조건",))
    assert [c[0] for c in store.calls] == [2, 2]          # 원문 + 재작성 각 1회
    assert len(merged) == 2                                # 가짜 저장소는 두 질의에 같은 2건 → 중복 제거


def test_rewrite_count_is_logged(client, rag_module, monkeypatch, access_log):
    monkeypatch.setattr(rag_module, "VECTORSTORE_PDF", _Store(ROWS))
    monkeypatch.setattr(rag_module, "ChatOpenAI", lambda *a, **kw: _LLM(rewrite_text="황화수소 노출기준 TWA STEL"))
    client.cookies.set("ACCESS_TOKEN", make_token())
    assert client.post("/rag-query", json={"prompt": "황화수소 노출기준?", "source": "pdf"}).status_code == 200
    assert json.loads(access_log[-1])["rewrites"] == 1


# ---- 프롬프트 게이트·인용 (평가 6행) ----

def test_citations_narrow_sources_and_are_stripped_from_text():
    llm = _LLM(text="TWA 10ppm [문서 1], STEL 15ppm입니다. [문서 2]")
    out = answer_with_sources("황화수소 노출기준?", _Store(ROWS), llm, top_k=5)
    assert out["response"] == "TWA 10ppm, STEL 15ppm입니다."
    assert out["sources"] == [{"source": "노출기준 고시 별표1", "section": "황화수소"}]   # 문서 4(응급조치)는 인용 안 됨


def test_without_citations_all_retrieved_sources_are_kept():
    out = answer_with_sources("황화수소 노출기준?", _Store(ROWS), _LLM(text="TWA 10ppm"), top_k=5)
    assert len(out["sources"]) == 2


def test_prompt_contains_scope_gate_rules():
    from rag_answer import PROMPT
    for must in ("의료적 판단", "실시간 측정값", "N/A", "근거 원문 그대로", "[문서 n]"):
        assert must in PROMPT
