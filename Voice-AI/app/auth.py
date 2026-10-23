"""Voice 화면과 음성 API가 공유하는 JWT 검증·인증 주소 설정."""

import os
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import Cookie, HTTPException, Request
from jose import JWTError, jwt

load_dotenv(Path(__file__).resolve().parent / ".env")

SECRET_KEY = os.getenv("JWT_SECRET")
ISSUER = os.getenv("JWT_ISSUER", "simple-auth-server")
ALGORITHM = "HS256"
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET 환경변수가 설정되지 않았습니다.")

# 브라우저가 접근하는 공개 주소이다. 컨테이너 간 통신 주소와 구분한다.
AUTH_ORIGINS = {
    "local": "http://localhost:8080",
    "deployed": "https://heartsignal.class-4.skala-us.com",
}
VOICE_ORIGINS = {
    "local": "http://localhost:8008",
    "deployed": "https://heartsignal-voice.class-4.skala-us.com",
}


def auth_config(request: Request, return_path: str = "/index.html") -> dict[str, str]:
    """로컬·배포 환경의 주소를 한 곳에서 관리하며 JWT는 노출하지 않는다."""
    environment = "local" if request.url.hostname in {"localhost", "127.0.0.1", "::1"} else "deployed"
    auth_origin = AUTH_ORIGINS[environment]
    return_to = VOICE_ORIGINS[environment] + return_path
    return {
        "auth_base_url": auth_origin,
        "login_url": auth_origin + "/login?" + urlencode({"return_to": return_to}),
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
        raise HTTPException(status_code=403, detail="Invalid role")
    return {"id": user_id, "username": username, "role": role}
