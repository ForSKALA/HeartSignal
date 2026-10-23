# HeartSignal P3 — request_id·표준 오류 응답·JSON 한 줄 로그
# - 모든 오류 본문: {"error": {"code", "message", "request_id"}} (AGENTS.md 7.2)
# - 로그: ts, request_id, path, status, latency_ms, user_sub, role + 라우터가 넣은 필드 (AGENTS.md 7.5)
# - 질문 원문·요청 본문은 로그에 남기지 않는다 (AGENTS.md 2장 7번)

import json
import logging
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_started_at: ContextVar[float] = ContextVar("started_at", default=0.0)
_log_extra: ContextVar[dict | None] = ContextVar("log_extra", default=None)

# HTTP 상태 → 오류 코드 (표에 없는 상태는 범위로 판단)
_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: "VALIDATION_ERROR",
    503: "NOT_READY",
}

logger = logging.getLogger("heartsignal.access")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class ApiError(Exception):
    """표준 오류 응답으로 바뀌는 예외. 예: raise ApiError(403, "FORBIDDEN", "권한이 없습니다.")"""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def current_request_id() -> str:
    return _request_id.get()


def elapsed_ms() -> int:
    started = _started_at.get()
    return int((time.perf_counter() - started) * 1000) if started else 0


def log_extra(**fields) -> None:
    """현재 요청의 로그 줄에 필드를 더한다. 예: log_extra(prompt_len=12, hits=5)"""
    extra = _log_extra.get()
    if extra is not None:
        extra.update(fields)


def error_response(status: int, code: str, message: str) -> JSONResponse:
    rid = current_request_id()
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": rid}},
        headers={REQUEST_ID_HEADER: rid},
    )


def _code_for(status: int) -> str:
    if status in _STATUS_CODES:
        return _STATUS_CODES[status]
    return "INTERNAL" if status >= 500 else "BAD_REQUEST"


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message)


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 500 계열 detail 에는 예외 원문(str(e))이 들어 있을 수 있으므로 노출하지 않는다
    if exc.status_code >= 500 and exc.status_code != 503:
        log_extra(error_detail_len=len(str(exc.detail)))
        return error_response(exc.status_code, "INTERNAL", "서버 오류가 발생했습니다.")
    message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    return error_response(exc.status_code, _code_for(exc.status_code), message)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 입력값(질문 원문)은 응답에 되돌려 주지 않고 위치와 사유만 알린다
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        parts.append(f"{loc}: {err.get('msg', '')}" if loc else err.get("msg", ""))
    return error_response(422, "VALIDATION_ERROR", "입력값이 올바르지 않습니다. " + "; ".join(parts))


def _error_origin(exc: Exception) -> str:
    """예외 메시지 대신 발생 위치만 남긴다 (메시지에 질문·비밀값이 섞일 수 있음)."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "-"
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1]}:{last.lineno}"


def install(app: FastAPI) -> None:
    """앱에 오류 처리기와 요청 로그 미들웨어를 연결한다."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        _request_id.set(rid)
        _started_at.set(time.perf_counter())
        extra: dict = {}
        _log_extra.set(extra)
        request.state.request_id = rid

        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = rid
        except Exception as exc:  # 처리기가 잡지 못한 예외 → 500 INTERNAL
            extra.update(error_type=type(exc).__name__, error_at=_error_origin(exc))
            response = error_response(500, "INTERNAL", "서버 오류가 발생했습니다.")

        user = getattr(request.state, "user", None)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": rid,
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "latency_ms": elapsed_ms(),
            "user_sub": user.sub if user else None,
            "role": user.role if user else None,
            **extra,
        }
        logger.info(json.dumps(record, ensure_ascii=False))
        return response
