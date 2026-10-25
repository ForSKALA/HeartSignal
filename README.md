![GitHub Repo Banner](https://ghrb.waren.build/render/banner?header=Heart+Signal&bg=EC4899-F2B9F1&color=FFFFFF&headerfont=La+Belle+Aurore&support=false&bgcontrast=80&bgsaturation=135)

## 🚀 About

정유•화학 유출 비상 대응 AI 에이전트 프로젝트

## 🏗️ Architecture

| 서비스 | 포트 | 역할 |
| --- | --- | --- |
| `web` (Vue 3 + Vite) | 5174 | 홈(경보 발령·현황), 챗봇, 로그인 화면 |
| `auth` (Java HttpServer) | 8080 | 회원가입·로그인, JWT(`ACCESS_TOKEN` 쿠키) 발급 |
| `rag` (FastAPI) | 8001 | `/rag-query` 문서 근거 질의, `/alarm`·`/board/current` 경보 API, 에이전트 |
| `voice` (FastAPI) | 8008 | STT·TTS |
| `db` (MariaDB) | 53301 → 3306 | 회원 정보 |

> 다이어그램 원본(`.mmd`)과 이미지(`.png`)는 [`docs/diagrams/`](docs/diagrams/)에 있습니다.

### 클래스 다이어그램

경보 발령·해제는 사람(`admin`)만 하고, 에이전트는 `agent.tools`의 7개 도구로 문서 근거 기반 안내·연락 업무만 수행합니다. 에이전트 결과는 `alarm.store.apply_agent_output()`을 거쳐 반영되며 단계(stage)·상태(status)는 바꿀 수 없습니다.

```mermaid
classDiagram
    direction LR

    namespace Web_Vue {
        class HomeView {
            +loadStatus() /alarm/status, /board/current
            +issueAlarm() POST /alarm
            +checkAuth() /api/auth/check
        }
        class ChatbotView {
            +ask() POST /rag-query
        }
        class ApiClient {
            +apiFetch(path, method, body)
        }
    }

    namespace Auth_Java {
        class SimpleAuthServer {
            +main() /api/login, /api/signup, /api/auth/check, /api/logout
        }
        class AuthService {
            +signUp(username, rawPassword)
            +login(username, rawPassword) User
        }
        class UserRepository {
            <<interface>>
            +save(User)
            +findByUsername(String) User
        }
        class JdbcUserRepository
        class JwtUtil {
            +createToken(User)$ String
            +verifyToken(String)$ DecodedJWT
            +roleOf(DecodedJWT)$ String
        }
        class User {
            -Long id
            -String username
            -String password
            -String role  worker|foreman|admin
        }
    }

    namespace RAG_FastAPI {
        class RagApp {
            <<rag_external-web_pdf_closed_llm>>
            +rag_query(RAGRequest) AnswerResponse
            +upload_paper() admin
            +upload_topic() admin
        }
        class RagAnswer {
            <<rag_answer>>
            +retrieve(vectorstore, prompt, top_k)
            +rewrite_queries(prompt, llm)
            +answer_with_sources(...) dict
            +needs_review_flag(...) bool
        }
        class AuthPy {
            <<auth.py>>
            +decode_token(token) CurrentUser
            +get_current_user() CurrentUser
            +require_role(*roles)
        }
        class CurrentUser {
            +sub
            +username
            +role
        }
        class Middleware {
            <<middleware.py>>
            +install(app)
            +log_extra(**fields)
        }
        class ApiError {
            +status
            +code
            +message
        }
        class AlarmRouter {
            <<alarm.router>>
            +issue_alarm(AlarmCreate) admin
            +alarm_status()
            +headcount(HeadcountIn) foreman
            +hold_report() admin
            +clear_alarm(ClearIn) admin
            +board_current(zone)
        }
        class AlarmStore {
            <<alarm.store>>
            -dict _alarms
            +create(zone, substance, stage, note, actor)
            +set_headcount() / hold_report() / clear()
            +apply_agent_output(alarm_id, phase, outputs, actions)
            +board_for(zone)
            +audit_log(...)
        }
        class AgentBridge {
            <<alarm.agent_bridge>>
            +run_for(alarm_id, phase)
        }
        class Fallback {
            <<alarm.fallback>>
            +board_lines() / checklist()
            +guide_card() / report_text()
        }
        class AlarmCreate {
            +Zone zone
            +str substance
            +int stage 1~3
            +str note
        }
    }

    namespace Agent {
        class Runner {
            <<agent.runner>>
            +ORDER 단계별 도구 순서
            +run_agent(alarm) list~action~
        }
        class Tools {
            <<agent.tools · 7개 도구>>
            +rag_search()
            +display_board()
            +notify_manager()
            +notify_foreman()
            +report_119()
            +broadcast_tts()
            +build_briefing()
        }
        class Evidence {
            <<agent.evidence>>
            +find(substance, purpose)
            +find_guides(zone, phase)
            +isolation_distances(text)
        }
        class Sections {
            <<agent.sections>>
            +build_sections(substance, zone)
        }
    }

    class FAISS {
        <<VectorStore>>
        faiss_db/p1-complete/web|pdf
    }
    class OpenAI {
        <<LLM>>
        gpt-4o / gpt-4o-mini
    }
    class MariaDB {
        <<DB>>
        users
    }

    HomeView --> ApiClient
    ChatbotView --> ApiClient
    ApiClient ..> SimpleAuthServer : 쿠키 ACCESS_TOKEN
    ApiClient ..> RagApp
    ApiClient ..> AlarmRouter

    SimpleAuthServer --> AuthService
    SimpleAuthServer --> JwtUtil
    AuthService --> UserRepository
    JdbcUserRepository ..|> UserRepository
    JdbcUserRepository --> MariaDB
    UserRepository --> User

    RagApp --> AuthPy
    RagApp --> Middleware
    RagApp --> RagAnswer
    RagApp --> AlarmRouter : include_router
    RagAnswer --> FAISS
    RagAnswer --> OpenAI
    AuthPy --> CurrentUser
    AuthPy ..> ApiError
    Middleware --> ApiError

    AlarmRouter --> AuthPy
    AlarmRouter --> AlarmStore
    AlarmRouter --> AgentBridge
    AlarmRouter --> AlarmCreate
    AlarmStore --> Fallback
    AgentBridge --> Runner
    AgentBridge --> AlarmStore : apply_agent_output
    Runner --> Tools
    Runner --> Sections
    Tools --> Evidence
    Evidence --> FAISS
    Sections --> RagAnswer
```

🖼️ 이미지: [`docs/diagrams/class-diagram.png`](docs/diagrams/class-diagram.png)

### 시퀀스 다이어그램 — 경보 발령 · 에이전트 대응

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 안전관리자(admin)
    participant Web as Vue 화면(web)
    participant Router as alarm.router
    participant Auth as auth.py
    participant Store as alarm.store
    participant Bridge as agent_bridge
    participant Runner as agent.runner
    participant Tools as agent.tools(7개)
    participant FAISS as FAISS 인덱스
    participant LLM as OpenAI LLM
    actor Foreman as 작업반장(foreman)
    participant Board as 전광판(/board/current)

    Admin->>Web: 구역·물질·단계 선택 후 경보 발령
    Web->>Router: POST /alarm {zone, substance, stage} (쿠키 JWT)
    Router->>Auth: require_role("admin")
    Auth-->>Router: CurrentUser (아니면 401/403)
    Router->>Store: create(zone, substance, stage, actor=sub)
    Note over Store: 고정 템플릿(fallback)으로 전광판·체크리스트·신고문 즉시 작성<br/>119 신고 30초 타이머 시작
    Router->>Bridge: spawn(run_for(alarm_id, "issue"))
    Router-->>Web: 201 경보 스냅샷

    par 백그라운드 에이전트
        Bridge->>Runner: run_agent(alarm) (타임아웃 적용)
        loop ORDER[stage] 순서대로 도구 실행
            Runner->>Tools: rag_search / report_119 / display_board / notify_manager / broadcast_tts / build_briefing / notify_foreman
            Tools->>FAISS: evidence.find(substance, purpose)
            FAISS-->>Tools: 근거 청크 + 출처(source, section)
            Tools-->>Runner: action 기록 (근거 없으면 fallback)
        end
        Runner->>LLM: sections.build_sections() 지침 카드 상세 (LLM 있을 때만)
        LLM-->>Runner: 섹션 (근거 0건이면 handoff)
        Runner-->>Bridge: actions
        Bridge->>Store: apply_agent_output() — stage·status는 변경 불가
        Note over Store: 감사 로그 (alarm_id, tool, tool_result, actor=agent)
    and 사람의 대응
        Admin->>Router: POST /alarm/{id}/hold-report (30초 내 보류 가능)
        Foreman->>Router: POST /alarm/{id}/headcount {checked, total}
    end

    loop 폴링
        Web->>Router: GET /alarm/status, /board/current
        Router-->>Web: 진행 경보 · 지침 카드 · 체크리스트 · 119 모의 신고 상태
        Board->>Router: GET /board/current?zone= (로그인 불필요)
        Router-->>Board: 대피 안내 문구
    end

    Admin->>Router: POST /alarm/{id}/clear
    Router->>Store: clear() → status=cleared
    Router->>Bridge: spawn(run_for(alarm_id, "clear"))
```

🖼️ 이미지: [`docs/diagrams/sequence-alarm.png`](docs/diagrams/sequence-alarm.png)

### 시퀀스 다이어그램 — 로그인 · 챗봇 질의(RAG)

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant Web as Vue 화면(web)
    participant Java as Java 인증 서버(auth)
    participant DB as MariaDB
    participant RAG as RAG FastAPI(/rag-query)
    participant Auth as auth.py
    participant Ans as rag_answer
    participant FAISS as FAISS 인덱스
    participant LLM as OpenAI LLM

    User->>Web: 아이디·비밀번호 입력
    Web->>Java: POST /api/login
    Java->>DB: findByUsername()
    DB-->>Java: User(role)
    Java-->>Web: Set-Cookie ACCESS_TOKEN (JWT HS256, role, exp 1h)

    User->>Web: 챗봇 질문
    Web->>RAG: POST /rag-query {prompt} (쿠키 JWT)
    RAG->>Auth: get_current_user() — 서명·만료·발급자 독립 검증
    Auth-->>RAG: CurrentUser (실패 시 401)
    RAG->>Ans: answer_with_sources(prompt)
    Ans->>LLM: rewrite_queries() (REWRITE_MODEL)
    Ans->>FAISS: retrieve() 벡터 + BM25 하이브리드 검색
    FAISS-->>Ans: 근거 청크(source, section, doc_type)
    alt 근거 0건
        Ans-->>RAG: handoff=true (LLM 호출 안 함)
    else 근거 있음
        Ans->>LLM: 근거 블록 + 질문 (LLM_MODEL)
        LLM-->>Ans: 답변
        Ans-->>RAG: response, sources, needs_review
    end
    RAG-->>Web: {prompt, response, sources, needs_review, handoff, request_id, latency_ms}
    Note over RAG: 로그엔 prompt_len·hits·top_score만 (질문 원문 저장 안 함)
```

🖼️ 이미지: [`docs/diagrams/sequence-rag.png`](docs/diagrams/sequence-rag.png)

## ⚡Quick Start

## 📦 How to Install
