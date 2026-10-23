# AGENTS.md — HeartSignal 공통 작업 규칙

> 모든 작업 전 이 파일을 먼저 읽고 작업합니다.
> 기획 근거: [`docs/HeartSignal-Plan.md`](docs/HeartSignal-Plan.md)

## 1. 프로젝트 한 줄

비상상황(가스 누출·화재·노출) 경보를 **안전관리자가 발령**하면, **에이전트가 문서 근거로 정리·안내·연락 업무(전광판 대피 안내, 관리자 대응 지침, 방송, 체크리스트, 119 신고)를 수행**하며, **사람은 경보 발령·대피 지휘·설비 조작·보류·해제**를 맡는 정유·석유화학 현장 안전 서비스.

## 2. 절대 규칙 (모든 파트 공통)

1. **경보 발령·해제는 사람(안전관리자, `admin`)만 합니다.** 센서·자동 판정은 없습니다. LLM·에이전트 코드에서 단계를 정하거나 바꾸는 함수를 호출하지 않습니다.
2. **에이전트 도구는 기획서 3.3의 7개뿐입니다** (`rag_search`, `broadcast_tts`, `notify_foreman`, `notify_manager`, `report_119`, `display_board`, `build_briefing`). 설비 조작·대피 판단·의료 판단 도구를 만들지 않습니다.
3. **대응 문장은 검색된 문서에서만** 가져오고 출처를 붙입니다. 근거가 0건이면 LLM을 호출하지 않고 `handoff: true`.
4. **LLM 장애 시에도 경보·방송·신고는 고정 템플릿으로 동작**해야 합니다.
5. 119·문자 알림은 **모의 발송만** (로그 + 화면 표시). 실제 외부 발송 코드 금지.
6. **비밀값은 코드에 넣지 않습니다.** `OPENAI_API_KEY`, `JWT_SECRET`, `DB_PASSWORD`는 `.env`(커밋 금지)로만. `.env-example`에는 키 이름만.
7. **로그에 질문 원문·음성 원본을 저장하지 않습니다.** (길이·해시·request_id만)
8. 공개 문서만 사용합니다. 센서·농도값 같은 가상 데이터는 쓰지 않습니다. 사이트 자동 크롤링 금지, 수동 다운로드.

## 3. 베이스 코드 정책

- 베이스 코드는 교재 실습 코드입니다. **TODO 빈칸을 채우고 최소한으로 확장**합니다. 구조 재작성·프레임워크 교체(Spring 도입, Vite 전환 등)는 팀 합의 후에만.
- 저작권 머리말은 지우지 않습니다.
- 기존 필드·경로 이름은 유지하고 **필드 추가로만 확장**합니다. (예: `/rag-query` 응답 `prompt`·`response` 유지 + `sources`·`needs_review`·`handoff`·`request_id`·`latency_ms` 추가)
- 의존성 추가는 해당 `requirements*.txt` / `build.gradle`에 버전 범위와 함께 기록하고 PR에 이유를 적습니다.

## 4. 디렉터리 · 파트 소유권

| 경로                                                                                                                                  | 내용                                     | 소유 파트          |
| ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ------------------ |
| `안전지침/`, `RAG/scripts/ingest.py`, `RAG/faiss_db/`, `docs/data_sources.md`, `RAG/data/`                                            | 원본 자료, 적재 스크립트, 인덱스, 출처표 | **P1 데이터**      |
| `RAG/rag_external-web_pdf_closed_llm.py`의 검색·프롬프트·답변 로직, `RAG/prompts/`, `RAG/agent/`, `RAG/eval/`, `docs/eval_results.md` | RAG 체인, 프롬프트, 에이전트, 평가       | **P2 RAG·LLM**     |
| `backend/`, `db/`, `RAG/auth.py`, `RAG/middleware.py`, `RAG/alarm/`(`/alarm` 경보 발령·`/board/current` 전광판)                     | 인증, JWT 검증, 오류·로그, 경보 API      | **P3 인증·API**    |
| `*.html`(루트), `web/`, 루트 `docker-compose.yml`, `README.md`                                                                        | 화면, 배포                               | **P4 프론트·배포** |
| `Voice-AI/`                                                                                                                           | STT·TTS (확장)                           | 음성 담당          |

- **다른 파트 소유 파일을 고칠 때는 해당 담당자에게 PR 리뷰를 요청**합니다. AI 에이전트도 같습니다: 작업 지시받은 파트 밖 파일은 수정하지 말고 제안만 남깁니다.
- `RAG/rag_external-web_pdf_closed_llm.py`는 여러 파트가 만지므로, 새 로직은 **별도 모듈로 만들고 이 파일에서는 import·라우터 연결만** 합니다.

## 5. 포트 · 서비스 이름

| 서비스         | 포트         | compose 서비스명 |
| -------------- | ------------ | ---------------- |
| Vue 화면       | 5174         | `web`            |
| Java 인증 서버 | 8080         | `auth`           |
| RAG FastAPI    | 8001         | `rag`            |
| Voice-AI       | 8008         | `voice`          |
| MariaDB        | 53301 → 3306 | `db`             |

컨테이너 간 호출은 서비스명(`http://rag:8001`)을 쓰고, `localhost`를 하드코딩하지 않습니다 (환경변수로 주입).

## 6. 환경변수 (`.env`)

```
OPENAI_API_KEY=
JWT_SECRET=           # Java·Python 동일 값
JWT_ISSUER=simple-auth-server
DB_PASSWORD=
ASYNC_DB_URL=mysql+aiomysql://root:${DB_PASSWORD}@db:3306/sql_db?charset=utf8mb4
CORS_ORIGINS=http://localhost:5174   # 쉼표 구분. RAG·Java 인증 서버 공통
DB_URL=jdbc:mariadb://db:3306/sql_db  # Java 인증 서버 (로컬 기본: localhost:53301)
LOGIN_REDIRECT_URL=/#/home           # Java 로그인 성공 후 이동 주소 (web 과 같은 origin 기준)
LLM_MODEL=gpt-4o
LLM_TIMEOUT_S=20
```

새 변수를 추가하면 이 표와 해당 `.env-example`을 함께 고칩니다.

## 7. 공통 계약

### 7.1 JWT

- 발급: Java `JwtUtil` — HS256, `iss=simple-auth-server`, `sub`(user id), `username`, **`role`**(`worker`|`foreman`|`admin`), `exp`=1시간
- 전달: 브라우저는 쿠키 `ACCESS_TOKEN`
- 검증: 각 Python 서비스가 **독립적으로** 서명·만료·발급자·role 검증 (`Voice-AI/app/main.py`의 `get_current_user()` 패턴). 회원 DB에 접근하지 않습니다.
- `role` 클레임이 없으면 `worker`로 간주합니다. 프론트가 보낸 role 값은 신뢰하지 않습니다.

### 7.2 오류 응답

```json
{
    "error": {
        "code": "UNAUTHORIZED",
        "message": "토큰이 만료되었습니다.",
        "request_id": "a1b2c3"
    }
}
```

| HTTP | code                        | 상황                                           |
| ---- | --------------------------- | ---------------------------------------------- |
| 401  | `UNAUTHORIZED`              | 토큰 없음·만료·서명 오류                       |
| 403  | `FORBIDDEN`                 | role 불일치                                    |
| 422  | `VALIDATION_ERROR`          | 입력 스키마 오류                               |
| 503  | `NOT_READY` / `LLM_TIMEOUT` | 인덱스 미준비, LLM 타임아웃                    |
| 500  | `INTERNAL`                  | 그 외 (메시지에 스택트레이스·비밀값 노출 금지) |

### 7.3 청크 메타데이터 (P1 → P2)

| 필드        | 필수        | 예시                                         |
| ----------- | ----------- | -------------------------------------------- |
| `source`    | ✅          | `KOSHA GUIDE G-78-2021`, `안전지침/염소.pdf` |
| `section`   | ✅          | `10.2(13)`, `응급조치>흡입`, `제618조`       |
| `doc_type`  | ✅          | `emergency` / `guide` / `law`                |
| `substance` | 물질 문서만 | `chlorine`                                   |
| `cas`       | 물질 문서만 | `7782-50-5`                                  |
| `published` | 가능하면    | `2021-12`                                    |

- 물질 키는 **영문 snake_case** (`hydrogen_sulfide`, `propane`)로 메타데이터·경보 발령 입력(`substance`)에서 동일하게 씁니다.
- `"자료없음"` 항목은 청크로 만들지 않습니다.

### 7.4 출처 표기

응답·방송·신고문의 출처는 `{"source": ..., "section": ...}` 객체 배열. 화면에는 `source section` 형태로 표시합니다.

### 7.5 로그 필드 (JSON 한 줄)

- 공통: `ts`, `request_id`, `path`, `status`, `latency_ms`, `user_sub`, `role`
- RAG: `prompt_len`, `hits`, `top_score`, `needs_review`, `handoff`, `tokens_in`, `tokens_out`
- 경보 감사: `alarm_id`, `zone`, `substance`, `stage`, `tool`, `tool_result`, `actor`(`agent`|사람 sub)

## 8. 코드 스타일

- **Python:** FastAPI + Pydantic v2, 타입 힌트, `async` 라우터. 라우터는 얇게, 로직은 모듈 함수로. `print` 디버그는 커밋 전 `logging`으로 교체.
- **Java:** 베이스 구조(`HttpServer` + 내부 static class) 유지. 프레임워크 도입 금지.
- **Vue:** 베이스의 Vue 3 CDN 단일 HTML 패턴 유지. API base URL은 설정값 하나로 관리. API 키·JWT 비밀키를 프론트에 넣지 않습니다.
- 주석·커밋 메시지·문서는 **한국어**, 코드 식별자는 영어.

## 9. 테스트 · 완료 기준

| 파트 | 커밋 전 최소 확인                                                                    |
| ---- | ------------------------------------------------------------------------------------ |
| P1   | 적재 스크립트 재실행 시 같은 청크 수, 출처표 갱신, "자료없음" 청크 0건               |
| P2   | `RAG/eval/` 평가 스크립트 실행 결과를 `docs/eval_results.md`에 기록 (변경 1개당 1회) |
| P3   | 무토큰 401 · role 불일치 403 · 스키마 오류 422 · 경보 발령은 `admin`만 통과           |
| P4   | `docker compose up` 후 로그인 → 질의 → S1 시나리오 수동 확인                         |

- "된다"고 말하기 전에 **실제로 실행한 명령과 결과**를 PR에 붙입니다.
- 실패한 테스트는 숨기지 않고 PR 본문에 적습니다.

## 10. Git 작업 방식

- `main`에 직접 푸시하지 않습니다. 브랜치: `p1/data-*`, `p2/rag-*`, `p3/api-*`, `p4/web-*`
- 커밋 메시지: `[P3] /rag-query JWT 검증 의존성 추가` 처럼 파트 태그 + 한 줄 요약
- PR은 작게(한 기능), 본문에 **무엇·왜·확인 방법**. 공통 계약(7장)을 바꾸는 PR은 **전원 리뷰**.
- 대용량 원본(PDF·인덱스)은 출처표에 기록하고, 인덱스는 재생성 가능해야 합니다.

## 11. 실행 (로컬)

```bash
docker compose -f db/docker-compose.yml up -d                                  # DB
cd backend && ./gradlew run                                                     # 인증 :8080 (DB_PASSWORD, JWT_SECRET 필요)
cd RAG && pip install -r requirements-e.txt \
  && python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --reload # RAG :8001, Swagger /docs
```

통합 실행은 루트 `docker-compose.yml`(P4 작성 후)과 `README.md`를 기준으로 합니다.
