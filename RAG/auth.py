# HeartSignal P3 — JWT 검증·role 권한 의존성
# Java 인증 서버(JwtUtil)가 발급한 ACCESS_TOKEN 쿠키를 이 서비스가 독립적으로 검증한다 (AGENTS.md 7.1).
# 회원 DB 는 조회하지 않는다. 패턴 출처: Voice-AI/app/main.py get_current_user()

import os
from dataclasses import dataclass
from typing import Callable

import jwt
from fastapi import Cookie, Depends, Request

from middleware import ApiError

ALGORITHM = "HS256"
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ISSUER = os.getenv("JWT_ISSUER", "simple-auth-server")

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET이 설정되지 않았습니다.")

DEFAULT_ROLE = "worker"
ROLES = {"worker", "foreman", "admin"}


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str
    role: str


def decode_token(token: str) -> CurrentUser:
    """서명·만료·발급자를 검증하고 사용자 정보를 돌려준다. 실패하면 401."""
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "UNAUTHORIZED", "토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise ApiError(401, "UNAUTHORIZED", "유효하지 않은 토큰입니다.")

    username = payload.get("username")
    if not username:
        raise ApiError(401, "UNAUTHORIZED", "토큰에 사용자 정보가 없습니다.")

    # role 클레임이 없거나 모르는 값이면 worker 로 간주 (Java JwtUtil.roleOf 와 같은 규칙)
    role = payload.get("role")
    if role not in ROLES:
        role = DEFAULT_ROLE

    return CurrentUser(sub=str(payload["sub"]), username=username, role=role)


async def get_current_user(
    request: Request,
    access_token: str | None = Cookie(default=None, alias="ACCESS_TOKEN"),
) -> CurrentUser:
    """로그인 사용자 의존성. 쿠키가 없거나 검증에 실패하면 401."""
    if not access_token:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다.")
    user = decode_token(access_token)
    # 요청 로그(user_sub, role)용
    request.state.user = user
    return user


def require_role(*allowed: str) -> Callable:
    """허용된 role 만 통과시키는 의존성을 만든다. 예: Depends(require_role("admin"))"""
    unknown = set(allowed) - ROLES
    if unknown:
        raise ValueError(f"알 수 없는 role: {unknown}")

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise ApiError(403, "FORBIDDEN", "권한이 없습니다.")
        return user

    return checker
