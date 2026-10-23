# [P2] rag_answer.answer_with_sources — 가짜 검색·LLM 으로 응답 계약 확인
import json

import pytest
from langchain_core.documents import Document
from openai import APITimeoutError

from middleware import ApiError
from rag_answer import NO_EVIDENCE, answer_with_sources
from conftest import make_token


def _doc(text, source, section=""):
    return Document(page_content=text, metadata={"source": source, "section": section})


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def similarity_search_with_score(self, q, k):
        return self.rows[:k]


class _LLM:
    def __init__(self, text="TWA 10ppm, STEL 15ppm", usage=None, exc=None):
        self.text, self.usage, self.exc = text, usage, exc

    def invoke(self, messages):
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


def test_no_hits_is_handoff_without_llm_call():
    llm = _LLM(exc=AssertionError("LLM must not be called"))
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
