// 화면 → 서버 API 호출 공통 처리
// 주소는 같은 origin 을 기본으로 쓴다 (로컬: vite proxy, 배포: Ingress). 바꿀 때만 VITE_API_BASE_URL 설정
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// 표준 오류 {"error": {code, message, request_id}} (AGENTS.md 7.2) 를 ApiError 로 바꿔 던진다
export async function apiFetch(path, { method = "GET", body } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: "include", // 로그인 쿠키(ACCESS_TOKEN)를 함께 보냄
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : null;
    const message = data?.error?.message || detail || `요청에 실패했습니다. (${response.status})`;
    throw new ApiError(response.status, data?.error?.code || "", message);
  }
  return data;
}
