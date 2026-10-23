"""Voice 화면과 음성 API가 공유하는 JWT 검증·인증 주소 설정."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, HTTPException, Request
from jose import JWTError, jwt

load_dotenv(Path(__file__).resolve().parent / ".env")

SECRET_KEY = os.getenv("JWT_SECRET")
ISSUER = os.getenv("JWT_ISSUER", "simple-auth-server")
ALGORITHM = "HS256"
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET 환경변수가 설정되지 않았습니다.")

def auth_config(request: Request) -> dict[str, str]:
    """배포는 같은 origin의 인증 API와 Vue 로그인을 사용한다."""
    local = request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    return {
        "auth_base_url": "http://localhost:8080" if local else "",
        "login_url": "http://localhost:5174/#/login" if local else "/#/login",
    }


def get_current_user(
    access_token: str | None = Cookie(default=None, alias="ACCESS_TOKEN"),
) -> dict[str, str]:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            access_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require_exp": True, "require_sub": True, "require_iss": True},
        )
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id or not isinstance(username, str) or not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    role = payload.get("role", "worker")
    if not isinstance(role, str) or role not in {"worker", "foreman", "admin"}:
        role = "worker"
    return {"id": user_id, "username": username, "role": role}
