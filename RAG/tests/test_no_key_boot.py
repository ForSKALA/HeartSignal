# [P2] OPENAI_API_KEY 없이 기동: 질의·업로드 503, 경보 에이전트는 템플릿·문서 근거로 동작 (AGENTS.md 2장 4번)
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import RAG_DIR, make_token


@pytest.fixture(scope="module")
def nokey_app(tmp_path_factory):
    env = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "RAG_INDEX_DIR")}
    os.environ["OPENAI_API_KEY"] = ""   # 빈 값: load_dotenv(RAG/.env) 가 덮어쓰지 않으므로 "키 없음" 재현
    os.environ["RAG_INDEX_DIR"] = str(tmp_path_factory.mktemp("no-index"))   # 인덱스 없이 (임베딩 호출 방지)
    for name in ("alarm.agent_bridge", "alarm.router", "alarm.store", "alarm", "agent"):
        sys.modules.pop(name, None)
    cwd = os.getcwd(); os.chdir(RAG_DIR)
    try:
        spec = importlib.util.spec_from_file_location("rag_app_nokey", RAG_DIR / "rag_external-web_pdf_closed_llm.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
        for k, v in env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    return module


def test_boots_without_key_and_marks_llm_unavailable(nokey_app):
    assert nokey_app.LLM_AVAILABLE is False


def test_query_and_upload_are_503_not_ready(nokey_app):
    client = TestClient(nokey_app.app)
    client.cookies.set("ACCESS_TOKEN", make_token("admin"))
    for call in (lambda: client.post("/rag-query", json={"prompt": "q", "source": "pdf"}),
                 lambda: client.post("/upload-topic", params={"topic": "x"}),
                 lambda: client.post("/upload-paper", files={"file": ("a.pdf", b"%PDF", "application/pdf")})):
        res = call()
        assert res.status_code == 503 and res.json()["error"]["code"] == "NOT_READY", res.text


def test_alarm_still_works_with_templates(nokey_app):
    client = TestClient(nokey_app.app)
    client.cookies.set("ACCESS_TOKEN", make_token("admin"))
    res = client.post("/alarm", json={"zone": "loading_bay", "substance": "propane", "stage": 3})
    assert res.status_code == 201, res.text
    alarm = client.get(f"/alarm/{res.json()['alarm_id']}").json()
    assert alarm["board"]["lines"] and alarm["report"]["text"].startswith("[모의 119 신고]")
    board = client.get("/board/current").json()
    assert board["lines"] and board["stage"] == 3
