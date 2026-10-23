# HeartSignal 쿠버네티스 배포 가이드

> 기준일: 2026-10-23 · 관련 PR: [#2](https://github.com/ForSKALA/HeartSignal/pull/2) · 명령 요약: [`web/k8s/README.md`](../web/k8s/README.md)
> 참고 샘플: `skala-ddive-kube`의 `00.sample-container`(빌드·push), `14.ingress`(Ingress·TLS)

HeartSignal 전체(web·auth·rag·voice·db)를 Harbor 이미지로 `class-4` 네임스페이스에 올리고, Ingress 호스트 하나에서 path로 나눠 서비스합니다. 호스트가 하나이므로 화면 코드를 고칠 필요가 없고(`external_index.html`은 localhost가 아니면 `location.origin`을 API 주소로 씀), `ACCESS_TOKEN` 쿠키도 같은 도메인 안에서 오갑니다.

## 1. 구성

```mermaid
flowchart TB
    B[브라우저] --> I["Ingress · P4 단독 관리<br/>heartsignal.class-4.skala-us.com (안)<br/>와일드카드 TLS"]
    I -->|/| W["web · P4<br/>nginx :80"]
    I -->|/api /login /signup /static /home| A["auth · P3<br/>Java :8080"]
    I -->|/rag-query /upload-* /docs /openapi.json| R["rag · P2<br/>FastAPI :8001"]
    V2[브라우저] -->|heartsignal-voice.class-4.skala-us.com| V["voice · 음성 (선택)<br/>FastAPI :8008"]
    A --> D[("db · P3<br/>MariaDB StatefulSet :3306<br/>PVC")]
    R --> D
```

- 모든 이미지는 Harbor `skala-registry.skala-us.com/class-4/heartsignal-*`에서 받습니다.
- 컨테이너 사이는 Service 이름으로 연결합니다 (`localhost` 하드코딩 금지, AGENTS.md 5장).
- voice는 `/`, `/index.html` 경로가 web과 겹치므로 **별도 호스트**로 연결합니다.

## 2. 팀 공통 이름·포트·경로 규칙

리소스와 이미지 이름은 개인 학번(`sk110` 등) 대신 팀 접두사 `heartsignal-`로 통일합니다. 샘플처럼 `{{USER_NAME}}`을 붙이면 사람마다 이름이 달라져 서비스 간 연결이 끊깁니다.

| 서비스 | 담당 | 폴더 | Harbor 이미지 | Service 이름:포트 |
| --- | --- | --- | --- | --- |
| web | P4 | `web/` | `class-4/heartsignal-web` | `heartsignal-web:80` |
| auth | P3 | `backend/` | `class-4/heartsignal-auth` | `heartsignal-auth:8080` |
| rag | P2 | `RAG/` | `class-4/heartsignal-rag` | `heartsignal-rag:8001` |
| voice | 음성 | `Voice-AI/` | `class-4/heartsignal-voice` | `heartsignal-voice:8008` |
| db | P3 | `db/` | 공식 `mariadb:11.4` | `heartsignal-db:3306` (headless) |

| Ingress path | 연결 서비스 |
| --- | --- |
| `/` | web |
| `/api`, `/login`, `/signup`, `/static`, `/home` | auth |
| `/rag-query`, `/upload-paper`, `/upload-topic`, `/docs`, `/openapi.json` | rag |
| 별도 호스트 `heartsignal-voice.class-4.skala-us.com` | voice |

## 3. 파트별 역할

| 파트 | 맡는 것 |
| --- | --- |
| P1 데이터 | `faiss_db` 인덱스 재생성 방법. 기본 인덱스는 rag 이미지에 포함 |
| P2 RAG·LLM | `RAG/Dockerfile`, rag 이미지 빌드·push, `RAG/k8s/` |
| P3 인증·API | `backend/Dockerfile`, auth 이미지, `backend/k8s/`, `db/k8s/` |
| P4 프론트·배포 | web 이미지, `web/k8s/`의 **Ingress**, 공통 Secret·ConfigMap, 적용 순서 |
| 음성 담당 | `Voice-AI/` 이미지, `Voice-AI/k8s/` (선택 배포) |

**Ingress는 P4 한 사람만 관리**합니다. 경로 추가가 필요하면 P4에게 PR로 요청합니다.

## 4. 파일 구성

```
web/       Dockerfile, Dockerfile.dockerignore, default.conf, docker-build.sh, docker-push.sh
web/k8s/   deployment.yaml, service.yaml, ingress.yaml, configmap.yaml, create-secret.sh, README.md
RAG/       Dockerfile, .dockerignore, docker-build.sh, docker-push.sh
RAG/k8s/   deployment.yaml, service.yaml, pvc.yaml
backend/   Dockerfile, .dockerignore, docker-build.sh, docker-push.sh
backend/k8s/  deployment.yaml, service.yaml
Voice-AI/  (기존 Dockerfile), .dockerignore, docker-build.sh, docker-push.sh
Voice-AI/k8s/ deployment.yaml, service.yaml
db/k8s/    statefulset.yaml, service.yaml, create-init-configmap.sh
```

| 리소스 | 내용 |
| --- | --- |
| Secret `heartsignal-secret` | `OPENAI_API_KEY`, `JWT_SECRET`, `DB_PASSWORD`(+선택 `NAVER_CLIENT_*`). 루트 `.env`에서 `web/k8s/create-secret.sh`로 생성, yaml로 커밋하지 않음 |
| ConfigMap `heartsignal-config` | `JWT_ISSUER`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `CORS_ORIGINS` |
| ConfigMap `heartsignal-db-init` | `db/init/*.sql`을 `create-init-configmap.sh`로 생성 (원본은 `db/init` 하나) |
| rag PVC `heartsignal-rag-faiss` | gp3 1Gi, `/app/faiss_db`에 마운트. 비어 있으면 initContainer가 이미지의 기본 인덱스를 복사. RWO라 replicas 1 + `Recreate` |
| db | StatefulSet + `volumeClaimTemplates`(gp3 1Gi). StatefulSet을 지워도 PVC는 남음 |
| 공통 | 모든 Deployment에 `imagePullSecrets: harbor-registry-secret`. TLS는 기존 `wildcard-class-4-skala-us-com-tls` 사용 |

컨테이너 간 연결 값:

- rag: `ASYNC_DB_URL=mysql+aiomysql://root:$(DB_PASSWORD)@heartsignal-db:3306/sql_db?charset=utf8mb4`
- auth: `DB_URL=jdbc:mariadb://heartsignal-db:3306/sql_db` (`SimpleAuthServer`가 환경변수로 읽고, 없으면 로컬 기본값)

## 5. 이미지 빌드와 Harbor push

각 서비스 폴더의 스크립트를 씁니다. 클러스터 노드가 amd64이므로 `linux/amd64`로 빌드합니다.

```bash
<서비스폴더>/docker-build.sh 1.0.0
<서비스폴더>/docker-push.sh 1.0.0   # DOCKER_REGISTRY, DOCKER_REGISTRY_USER, DOCKER_REGISTRY_PASSWORD, CLASS_NAME 필요
```

- web은 루트의 `*.html`을 넣기 위해 저장소 루트를 빌드 컨텍스트로 쓰고, `web/Dockerfile.dockerignore`로 필요한 파일만 넣습니다.
- auth는 `gradle-wrapper.jar`가 저장소에 없으므로(`*.jar` ignore) `gradle:9.0.0-jdk17` 이미지로 빌드합니다.
- **태그는 매번 새로** 붙이고(`1.0.1`, git short sha 등), 해당 `k8s/deployment.yaml`의 `image:` 태그도 PR로 함께 바꿉니다.
- Harbor robot 계정은 공용이므로 자기 서비스 이미지 이름으로만 push합니다.

## 6. 적용 순서

```bash
# 0. 공통 (P4, 1회)
web/k8s/create-secret.sh
kubectl apply -f web/k8s/configmap.yaml

# 1. P3: DB → auth
db/k8s/create-init-configmap.sh
kubectl apply -f db/k8s/
kubectl rollout status statefulset/heartsignal-db -n class-4
kubectl apply -f backend/k8s/

# 2. P2: rag   /   음성: voice (선택)
kubectl apply -f RAG/k8s/
kubectl apply -f Voice-AI/k8s/

# 3. P4: web + ingress
kubectl apply -f web/k8s/
```

확인:

```bash
kubectl get pods,svc,ingress,pvc -n class-4 -l part-of=heartsignal
kubectl logs -n class-4 deploy/heartsignal-rag
kubectl describe pod -n class-4 <파드이름>     # ImagePullBackOff 등 원인 확인
curl -I https://heartsignal.class-4.skala-us.com/
curl -s https://heartsignal.class-4.skala-us.com/openapi.json | head -c 200
```

최종 확인은 AGENTS.md 9장 기준으로 ingress 주소에서 로그인 → 질의 → S1 시나리오입니다. 실행한 명령과 결과는 PR 본문에 붙입니다.

## 7. 협업 규칙

1. **git이 기준입니다.** 매니페스트 변경은 PR로 머지한 뒤 적용합니다. 각자 PC에서 같은 파일을 apply하면 마지막 사람의 것이 남습니다.
2. **자기 서비스 폴더만 apply합니다.** 예: P2는 `kubectl apply -f RAG/k8s/`만 실행합니다.
3. **이미지 태그는 매번 새로** 붙입니다.
4. **Secret은 P4 한 사람이 만들고** 나머지는 참조만 합니다. `JWT_SECRET`은 Java·Python이 같은 값을 써야 합니다(AGENTS.md 7.1). 값은 채팅·커밋으로 공유하지 않습니다.
5. **폴더 전체 삭제 금지.** `kubectl delete -f`는 자기 서비스 폴더만 합니다.

클러스터에 `argocd` 네임스페이스가 있으므로, 수업에서 허용하면 ArgoCD로 git과 동기화해 1·2번 문제를 없앨 수 있습니다.

## 8. 검증 결과 (PR #2 시점)

| 항목 | 결과 |
| --- | --- |
| 매니페스트 13개 `kubectl apply --dry-run=server` | 모두 통과 (클러스터에 생성하지 않음) |
| 이미지 빌드 (linux/amd64) | web 93.7MB, auth 433MB, rag 788MB, voice 3.49GB 모두 성공 |
| web 로컬 실행 | `/` 200, `/external_index.html` 200, `/healthz` ok |
| rag 로컬 실행 | `/openapi.json` 200, `/upload-topic`·`/upload-paper`·`/rag-query` 등록 |
| auth 로컬 실행 | `/login` 200 |
| voice 로컬 실행 | `/` 401(JWT 필요) → readinessProbe를 tcpSocket으로 변경 |

아직 확인하지 않은 것: Harbor push, 클러스터 실제 배포, DB 연결, OpenAI 호출, ingress 접속.

## 9. 남은 문제

- [ ] **P3**: 로그인 성공 시 `http://localhost:8008/index.html`로 이동 (`SimpleAuthServer.java:287`, `login.html:58`)
- [ ] **음성**: `Voice-AI/app/main.py`의 `SECRET_KEY = "RANDOM_SECRET_KEY"` 하드코딩 → `JWT_SECRET`과 달라 토큰 검증 실패
- [ ] **음성**: torch CUDA 버전 설치로 이미지 3.49GB → CPU 전용 torch 권장
- [ ] **P4**: `Voice-AI/app/static/index.html`이 `http://localhost:8080/api/auth/check` 호출
- [ ] **P4**: AGENTS.md 5·6장에 k8s용 Service 이름·환경변수 값 추가
- [ ] **전원**: Ingress 호스트 이름(안: `heartsignal.class-4.skala-us.com`), 이미지 태그 규칙, ArgoCD 사용 여부 확정
