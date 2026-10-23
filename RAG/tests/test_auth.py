# [P3] 인증·권한 테스트: 무토큰 401, role 불일치 403, 스키마 오류 422
import pytest

from conftest import make_token

QUERY = {"prompt": "황화수소 노출기준은?", "source": "pdf", "top_k": 5}


def _assert_error(res, status, code):
    assert res.status_code == status, res.text
    err = res.json()["error"]
    assert err["code"] == code
    assert err["message"]
    assert err["request_id"] == res.headers["X-Request-ID"]
    return err


def test_no_token_401(client):
    _assert_error(client.post("/rag-query", json=QUERY), 401, "UNAUTHORIZED")


def test_expired_token_401(client):
    client.cookies.set("ACCESS_TOKEN", make_token(exp_offset=-10))
    err = _assert_error(client.post("/rag-query", json=QUERY), 401, "UNAUTHORIZED")
    assert "만료" in err["message"]


@pytest.mark.parametrize("token_kwargs", [
    {"secret": "wrong-secret-0123456789-0123456789"},
    {"issuer": "someone-else"},
])
def test_invalid_token_401(client, token_kwargs):
    client.cookies.set("ACCESS_TOKEN", make_token(**token_kwargs))
    _assert_error(client.post("/rag-query", json=QUERY), 401, "UNAUTHORIZED")


def test_garbage_token_401(client):
    client.cookies.set("ACCESS_TOKEN", "not-a-jwt")
    _assert_error(client.post("/rag-query", json=QUERY), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("role", ["worker", "foreman", "admin"])
def test_any_logged_in_role_can_query(client, role):
    # 인증 통과 확인용: 잘못된 source 는 기존 로직대로 400
    client.cookies.set("ACCESS_TOKEN", make_token(role))
    _assert_error(client.post("/rag-query", json={**QUERY, "source": "nope"}), 400, "BAD_REQUEST")


@pytest.mark.parametrize("role", ["worker", "foreman"])
def test_upload_paper_non_admin_403(client, role):
    client.cookies.set("ACCESS_TOKEN", make_token(role))
    res = client.post("/upload-paper", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    _assert_error(res, 403, "FORBIDDEN")


def test_upload_topic_worker_403(client):
    client.cookies.set("ACCESS_TOKEN", make_token("worker"))
    _assert_error(client.post("/upload-topic", params={"topic": "x"}), 403, "FORBIDDEN")


def test_upload_no_token_401(client):
    res = client.post("/upload-paper", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    _assert_error(res, 401, "UNAUTHORIZED")


def test_upload_paper_admin_passes_auth(client):
    # admin 은 권한 검사 통과 → 기존 로직의 확장자 검사(400)까지 도달
    client.cookies.set("ACCESS_TOKEN", make_token("admin"))
    res = client.post("/upload-paper", files={"file": ("a.txt", b"hello", "text/plain")})
    _assert_error(res, 400, "BAD_REQUEST")


@pytest.mark.parametrize("token_kwargs", [{"include_role": False}, {"role": "root"}, {"role": "device"}])
def test_missing_or_unknown_role_is_worker(client, token_kwargs):
    client.cookies.set("ACCESS_TOKEN", make_token(**token_kwargs))
    # 질의는 가능(worker), 업로드는 403
    _assert_error(client.post("/rag-query", json={**QUERY, "source": "nope"}), 400, "BAD_REQUEST")
    _assert_error(client.post("/upload-topic", params={"topic": "x"}), 403, "FORBIDDEN")


@pytest.mark.parametrize("prompt", ["", "   "])
def test_empty_prompt_422(client, prompt):
    client.cookies.set("ACCESS_TOKEN", make_token())
    err = _assert_error(client.post("/rag-query", json={**QUERY, "prompt": prompt}), 422, "VALIDATION_ERROR")
    assert "prompt" in err["message"]


def test_validation_error_does_not_echo_input(client):
    client.cookies.set("ACCESS_TOKEN", make_token())
    res = client.post("/rag-query", json={"prompt": "비밀질문-XYZ", "source": "pdf", "top_k": 0})
    err = _assert_error(res, 422, "VALIDATION_ERROR")
    assert "비밀질문-XYZ" not in res.text
    assert "top_k" in err["message"]


def test_auth_checked_before_validation(client):
    # 토큰 없이 잘못된 본문을 보내도 401 (스키마 정보 노출 방지)
    _assert_error(client.post("/rag-query", json={"prompt": ""}), 401, "UNAUTHORIZED")


def test_index_not_loaded_message_kept(client):
    # 인덱스 미로딩은 기존 로직(400) 유지 — 503 NOT_READY 전환은 P2 와 협의
    client.cookies.set("ACCESS_TOKEN", make_token())
    _assert_error(client.post("/rag-query", json=QUERY), 400, "BAD_REQUEST")
