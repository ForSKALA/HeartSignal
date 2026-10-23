# [P3] 오류 형식·로그 테스트: 500 메시지 비노출, 질문 원문 미기록, /rag-query 응답 확장 필드
import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.documents import Document

import middleware
from conftest import make_token


def _mini_app():
    app = FastAPI()
    middleware.install(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("비밀값 sk-live-123 이 들어간 예외")

    @app.get("/http500")
    async def http500():
        raise HTTPException(status_code=500, detail="DB password=hunter2")

    @app.get("/notready")
    async def notready():
        raise middleware.ApiError(503, "LLM_TIMEOUT", "LLM 응답이 지연되고 있습니다.")

    return app


def test_unhandled_exception_is_500_internal_without_detail(access_log):
    res = TestClient(_mini_app(), raise_server_exceptions=False).get("/boom")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL"
    assert "sk-live-123" not in res.text
    record = json.loads(access_log[-1])
    assert record["status"] == 500 and record["error_type"] == "RuntimeError"
    assert "sk-live-123" not in access_log[-1]


def test_http_500_detail_hidden(access_log):
    res = TestClient(_mini_app()).get("/http500")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL"
    assert "hunter2" not in res.text
    assert "hunter2" not in access_log[-1]


def test_api_error_503():
    res = TestClient(_mini_app()).get("/notready")
    assert res.status_code == 503
    assert res.json()["error"] == {
        "code": "LLM_TIMEOUT",
        "message": "LLM 응답이 지연되고 있습니다.",
        "request_id": res.headers["X-Request-ID"],
    }


class _FakeStore:
    def similarity_search_with_score(self, q, k):
        return [(Document(page_content="황화수소 TWA 10ppm", metadata={"source": "x.pdf"}), 0.1)]


class _FakeLLM:
    def __init__(self, *a, **kw):
        pass

    def invoke(self, messages):
        return type("Msg", (), {"content": "TWA 10ppm 입니다."})()


def test_rag_query_extended_fields_and_log(client, rag_module, monkeypatch, access_log):
    monkeypatch.setattr(rag_module, "VECTORSTORE_PDF", _FakeStore())
    monkeypatch.setattr(rag_module, "ChatOpenAI", _FakeLLM)
    prompt = "황화수소-원문-ABC 노출기준?"
    client.cookies.set("ACCESS_TOKEN", make_token("worker", sub="42"))

    res = client.post("/rag-query", json={"prompt": prompt, "source": "pdf"})

    assert res.status_code == 200, res.text
    body = res.json()
    # 기존 필드 유지 + 추가 필드
    assert body["prompt"] == prompt and body["response"] == "TWA 10ppm 입니다."
    assert body["sources"] == [{"source": "x.pdf", "section": ""}]  # [P2] 검색 청크 metadata 로 채움
    assert body["needs_review"] is False and body["handoff"] is False
    assert body["request_id"] == res.headers["X-Request-ID"]
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0

    record = json.loads(access_log[-1])
    assert record["request_id"] == body["request_id"]
    assert record["path"] == "/rag-query" and record["status"] == 200
    assert record["user_sub"] == "42" and record["role"] == "worker"
    assert record["prompt_len"] == len(prompt)
    assert "원문-ABC" not in access_log[-1]
