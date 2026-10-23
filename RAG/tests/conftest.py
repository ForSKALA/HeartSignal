# [P3] 테스트 공통 설정: 메인 앱을 실제 OpenAI 호출 없이 띄운다
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path

import jwt
import pytest

RAG_DIR = Path(__file__).resolve().parent.parent
TEST_SECRET = "test-secret-for-pytest-only-0123456789"
ISSUER = "simple-auth-server"

# 앱 import 전에 환경변수 지정 (실제 키 불필요, LLM 은 호출하지 않음)
os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
os.environ["JWT_SECRET"] = TEST_SECRET
os.environ["JWT_ISSUER"] = ISSUER
sys.path.insert(0, str(RAG_DIR))


@pytest.fixture(scope="session")
def rag_module():
    # 파일 이름에 '-' 가 있어 importlib 로 불러온다. 인덱스 상대경로 때문에 RAG 폴더에서 로드
    cwd = os.getcwd()
    os.chdir(RAG_DIR)
    try:
        spec = importlib.util.spec_from_file_location("rag_app", RAG_DIR / "rag_external-web_pdf_closed_llm.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
    return module


@pytest.fixture
def client(rag_module, monkeypatch):
    from fastapi.testclient import TestClient

    # 기본은 인덱스 미로딩 상태 (임베딩 API 호출 방지)
    monkeypatch.setattr(rag_module, "VECTORSTORE_WEB", None)
    monkeypatch.setattr(rag_module, "VECTORSTORE_PDF", None)
    return TestClient(rag_module.app)


def make_token(role="worker", *, sub="1", username="tester", secret=TEST_SECRET,
               issuer=ISSUER, exp_offset=3600, include_role=True):
    """Java JwtUtil.createToken 과 같은 모양의 토큰"""
    now = int(time.time())
    payload = {"iss": issuer, "iat": now, "exp": now + exp_offset, "sub": sub, "username": username}
    if include_role:
        payload["role"] = role
    return jwt.encode(payload, secret, algorithm="HS256")


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def access_log():
    logger = logging.getLogger("heartsignal.access")
    handler = _ListHandler()
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)
