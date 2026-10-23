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
- auth: `CORS_ORIGINS`·`JWT_ISSUER`는 `heartsignal-config`(envFrom)에서 받습니다. `LOGIN_REDIRECT_URL`은 기본값 `/#/home`(같은 호스트의 web)으로 충분해서 설정하지 않습니다 ([#14](https://github.com/ForSKALA/HeartSignal/pull/14))

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

**0. 공통 완료 (2026-10-23):** `class-4`에 Secret `heartsignal-secret`(OPENAI_API_KEY·JWT_SECRET·DB_PASSWORD, NAVER_* 는 빈 값)과 ConfigMap `heartsignal-config`(JWT_ISSUER·LLM_MODEL·LLM_TIMEOUT_S·CORS_ORIGINS)를 적용했습니다. Secret 값은 루트 `.env`와 해시로 일치 확인했습니다. `DB_PASSWORD`는 DB가 처음 뜰 때 root 비밀번호로 고정되므로 이후 바꾸려면 PVC를 지우고 다시 띄워야 합니다. `JWT_SECRET`은 auth·rag·voice 공통 값입니다. 다음 단계는 P3의 DB → auth 배포입니다.

**TLS 확인:** 와일드카드 인증서는 클러스터에 이미 발급되어 있습니다 (2026-10-23 확인: Certificate `wildcard-class-4-skala-us-com` READY=True, Secret `wildcard-class-4-skala-us-com-tls`, ClusterIssuer `letsencrypt-prod`, `CN=*.class-4.skala-us.com`, Let's Encrypt 발급, 만료 2026-12-14 — cert-manager가 자동 갱신). 브라우저·curl이 `Kubernetes Ingress Controller Fake Certificate`를 받으면 인증서 문제가 아니라 **그 호스트의 Ingress가 아직 없다**는 뜻입니다.

```bash
kubectl get certificate -n class-4 wildcard-class-4-skala-us-com
echo | openssl s_client -connect heartsignal.class-4.skala-us.com:443 \
  -servername heartsignal.class-4.skala-us.com 2>/dev/null | openssl x509 -noout -subject -issuer
# 정상: subject=CN=*.class-4.skala-us.com, issuer=Let's Encrypt
```

### 6.1 시연 계정 시드 (P3, 배포 후 1회)

가입 화면은 항상 `worker`만 만들므로(AGENTS.md 7.1), 시연용 `admin1`·`foreman1`·`worker1`은 `db/seed-demo-users.sh`로 만듭니다. `/api/signup`으로 가입하고 DB에서 role을 부여한 뒤, 실제 로그인해 JWT `role`까지 확인합니다. 여러 번 실행해도 결과가 같습니다.

**선행 조건**
1. auth 이미지에 [#14](https://github.com/ForSKALA/HeartSignal/pull/14)(회원가입 JSON 응답)가 포함되어 있어야 합니다. 이전 이미지는 회원가입에 302를 돌려줘 스크립트가 `가입 실패 (HTTP 302)`로 멈춥니다.
2. DB(`heartsignal-db-0`)·auth·Ingress가 떠 있고, `https://heartsignal.class-4.skala-us.com/login`이 200이어야 합니다 (위 TLS 확인 참고).
3. `kubectl exec` 권한 (`class-4` 네임스페이스).

**실행**

```bash
# 비밀번호는 env 파일에만 둡니다 (기본 db/.env, 커밋 금지). 키 이름은 db/.env-example 참고
#   SEED_ADMIN_PASSWORD / SEED_FOREMAN_PASSWORD / SEED_WORKER_PASSWORD
AUTH_URL=https://heartsignal.class-4.skala-us.com db/seed-demo-users.sh k8s
```

정상 출력:

```
인증 서버: https://heartsignal.class-4.skala-us.com (모드: k8s)
[admin1] 가입 완료
[admin1] 로그인 확인 — JWT role=admin
...
시연 계정 3개 준비 완료
```

- 이미 있는 계정은 가입을 건너뛰고 role만 다시 맞춥니다. `로그인 실패 (HTTP 401)`이 나오면 그 계정이 env 파일과 다른 비밀번호로 이미 있다는 뜻입니다.
- 공개 저장소이므로 시연 비밀번호를 채팅·커밋으로 공유하지 않습니다. 발표가 끝나면 계정을 지우거나 비밀번호를 바꿉니다.

최종 확인은 AGENTS.md 9장 기준으로 ingress 주소에서 로그인 → 질의 → S1 시나리오입니다. 실행한 명령과 결과는 PR 본문에 붙입니다.

### 6.2 DB(MariaDB)가 k8s에서 동작하는 방식 (P3)

파일: `db/k8s/statefulset.yaml`, `db/k8s/service.yaml`, `db/k8s/create-init-configmap.sh`

```mermaid
flowchart TB
    A["auth (Java)"] --> S["Service heartsignal-db:3306<br/>headless · 클러스터 내부 전용"]
    R["rag (Python)"] --> S
    S --> P["Pod heartsignal-db-0<br/>StatefulSet · replicas 1 · mariadb:11.4"]
    PVC[("PVC data-heartsignal-db-0<br/>gp3 1Gi · 실제 데이터")] -->|/var/lib/mysql| P
    CM["ConfigMap heartsignal-db-init<br/>db/init/*.sql"] -->|/docker-entrypoint-initdb.d| P
    SEC["Secret heartsignal-secret<br/>DB_PASSWORD"] -->|MARIADB_ROOT_PASSWORD| P
```

| 리소스 | 역할 |
| --- | --- |
| StatefulSet `heartsignal-db` | MariaDB 파드 1개(`heartsignal-db-0`). 문자셋 옵션은 `db/docker-compose.yml`과 같음. 파드 이름과 디스크가 고정되어야 해서 Deployment 대신 StatefulSet 사용 |
| PVC (`volumeClaimTemplates`) | gp3 1Gi에 데이터 저장. **파드 재시작·StatefulSet 삭제에도 PVC는 남아** 데이터 유지 (로컬의 `heartsignal_mariadb_data` 볼륨에 해당) |
| headless Service `heartsignal-db` | auth는 `jdbc:mariadb://heartsignal-db:3306/sql_db`, rag는 `heartsignal-db:3306`으로 접속. **Ingress에 연결하지 않으므로 외부에서 접근 불가** |
| ConfigMap `heartsignal-db-init` | `db/init/*.sql`(users 테이블, role 마이그레이션)을 담음. 원본은 `db/init` 하나라 로컬과 같은 SQL 사용 |
| Secret `heartsignal-secret` | `DB_PASSWORD`를 root 비밀번호로 사용. auth·rag도 같은 값을 받음 |
| readiness·liveness probe | MariaDB 공식 `healthcheck.sh`로 접속·InnoDB 준비 확인. 준비 전에는 트래픽을 받지 않음 |

**처음 배포할 때 일어나는 일** (6장 "1. P3: DB → auth")
1. PVC가 새로 만들어집니다 (빈 디스크).
2. MariaDB가 빈 디스크를 보고 초기화합니다. Secret의 비밀번호로 root를 만들고 `sql_db`를 만든 뒤 `db/init/` SQL을 **이때 한 번만** 실행합니다.
3. probe를 통과하면 auth·rag가 접속할 수 있습니다. 그다음 `backend/k8s/`를 적용합니다.

**주의할 점**
1. **초기화 SQL은 빈 PVC에서 1회만 실행됩니다.** `db/init/`에 SQL을 추가하고 ConfigMap을 갱신해도 이미 초기화된 DB에는 적용되지 않습니다. 이 경우 직접 실행합니다.
   ```bash
   kubectl exec -i -n class-4 heartsignal-db-0 -c mariadb -- \
     sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" sql_db' < db/init/<파일>.sql
   ```
2. **root 비밀번호도 첫 초기화 때 고정됩니다.** 나중에 Secret의 `DB_PASSWORD`만 바꾸면 DB는 예전 비밀번호, auth·rag는 새 비밀번호를 써서 연결이 끊깁니다. 바꾸려면 DB 안에서 `ALTER USER`로 `root@'%'`와 `root@'localhost'`의 비밀번호를 먼저 바꾸고 Secret을 바꾼 뒤 auth·rag를 재시작합니다.
3. **처음부터 다시 만들려면 PVC를 지워야 합니다.** `kubectl delete -f db/k8s/`로는 PVC가 남습니다. 데이터를 완전히 지우려면 `kubectl delete pvc data-heartsignal-db-0 -n class-4`가 필요하며, **되돌릴 수 없으므로 팀 합의 후** 실행합니다. 다시 만든 뒤에는 시연 계정 시드(6.1)도 다시 실행합니다.
4. **복제본·백업이 없습니다.** 시연용이라 파드 1개·디스크 1개입니다. 경보 데이터는 RAG 서버 메모리에 있고 DB에는 회원 정보만 있어 시연 범위에서는 충분합니다.
5. **PVC는 한 노드에만 붙습니다(RWO).** 파드가 다른 노드로 옮겨지면 디스크를 다시 붙이느라 기동이 조금 늦어질 수 있습니다.

**로컬과 비교**

| | 로컬 (`db/docker-compose.yml`) | k8s |
| --- | --- | --- |
| 접속 주소 | `localhost:53301` | `heartsignal-db:3306` (클러스터 내부) |
| 비밀번호 | `db/.env`의 `DB_PASSWORD` (필수, [#14](https://github.com/ForSKALA/HeartSignal/pull/14)) | Secret `heartsignal-secret` |
| 데이터 | Docker 볼륨 `heartsignal_mariadb_data` | gp3 PVC `data-heartsignal-db-0` |
| 초기화 SQL | `./init` 폴더 직접 마운트 | ConfigMap으로 담아 마운트 |

**상태 확인**

```bash
kubectl get statefulset,pod,pvc -n class-4 -l part-of=heartsignal
kubectl logs -n class-4 heartsignal-db-0                       # 초기화 SQL 실행 로그 포함
kubectl exec -n class-4 heartsignal-db-0 -c mariadb -- \
  sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "SELECT username, role FROM sql_db.users"'
```

> 2026-10-23 `class-4`에 실제로 배포해 초기화 SQL 실행, `role` 컬럼, auth 연결까지 확인했습니다(8.1).

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

아직 확인하지 않은 것: Harbor push, 클러스터 실제 배포, DB 연결, OpenAI 호출, ingress 접속. → DB·auth는 8.1에서 확인

### 8.1 클러스터 실제 배포: DB·auth (2026-10-23, P3)

기준 커밋 `main` `fc26d40` (#14 회원가입 JSON·환경변수화, #27 공통 Secret 포함). Secret·ConfigMap은 P4가 6장 "0. 공통"으로 생성했습니다.

| 단계 | 명령 | 결과 |
| --- | --- | --- |
| auth 이미지 빌드 | `backend/docker-build.sh 1.0.0` | linux/amd64, 113MB |
| 이미지 로컬 확인 | amd64 에뮬레이션으로 실행 | `/login` 200, 회원가입 `{"ok":true}`, 로그인 `{"redirect":"/#/home"}` |
| Harbor push | `backend/docker-push.sh 1.0.0` | `class-4/heartsignal-auth:1.0.0`, digest `sha256:a5efce67…` |
| Secret·ConfigMap 확인 | 키 존재만 확인 (값 미출력) | `DB_PASSWORD`·`JWT_SECRET`·`OPENAI_API_KEY` 값 있음, `heartsignal-config` 4개 키 |
| DB 초기화 ConfigMap | `db/k8s/create-init-configmap.sh` | `heartsignal-db-init` (`01_users.sql`, `02_users_role.sql`) |
| 서버 dry-run | `kubectl apply --dry-run=server -f db/k8s/ -f backend/k8s/` | 통과 |
| DB 배포 | `kubectl apply -f db/k8s/` | `heartsignal-db-0` Running 1/1, PVC `data-heartsignal-db-0` Bound(gp3 1Gi) |
| auth 배포 | `kubectl apply -f backend/k8s/` | `heartsignal-auth` Running 1/1 |

**DB 확인** (`kubectl logs`, `kubectl exec`)
- 첫 기동 로그에 `running /docker-entrypoint-initdb.d/01_users.sql`, `02_users_role.sql`
- `users` 테이블에 `role varchar(20) NOT NULL DEFAULT 'worker'`
- `character_set_server=utf8mb4`, `lower_case_table_names=1`, 시간대 KST

**auth 확인** (Ingress 배포 전이라 `kubectl port-forward -n class-4 svc/heartsignal-auth 18081:8080`)

| 요청 | 결과 |
| --- | --- |
| `GET /login` | 200 |
| 회원가입 / 같은 계정 재가입 | 200 `{"ok":true}` / 409 |
| 틀린 비밀번호 / 정상 로그인 | 401 / 200 `{"ok":true,"redirect":"/#/home"}` |
| `GET /api/auth/check` (로그인 쿠키) | `{"ok":true,"via":"session",...,"role":"worker"}` |
| preflight `Origin: https://heartsignal.class-4.skala-us.com` | `Access-Control-Allow-Origin` 반환 → ConfigMap `CORS_ORIGINS` 적용 |
| JWT payload | `iss=simple-auth-server`, `role=worker` |
| DB 저장값 | `$2a$12$` bcrypt 해시, `role=worker` |

시험 계정은 확인 후 삭제했습니다(`users` 0건).

아직 확인하지 않은 것: rag·voice·web 배포, Ingress 접속(TLS), 시연 계정 시드(6.1), 로그인 → 질의 → S1 화면 흐름.

### 8.2 클러스터 실제 배포: rag (2026-10-23 15:20, P2)

기준 커밋 `main` `5249268` + 이 PR(`.dockerignore`·initContainer 시드 기준). 이미지 `class-4/heartsignal-rag:1.1.0`.

| 단계 | 명령 | 결과 |
| --- | --- | --- |
| 이미지 빌드 | `RAG/docker-build.sh 1.1.0` | linux/amd64, **201MB** (이전 788MB — 평가 결과·테스트·이전 인덱스·베이스 실습 인덱스를 `.dockerignore`로 제외) |
| 로컬 확인 (amd64 에뮬레이션) | `docker run --env-file RAG/.env -p 18020:8001` | 기동 2초, `VECTORSTORE_PDF/WEB 로드`·`에이전트 근거 조회 준비`, `/rag-query` 암모니아 30m/150m + 출처, S1 발령 도구 7개 `ok`, 메모리 177MB |
| Harbor push | `docker tag` + `docker push` | `class-4/heartsignal-rag:1.1.0`, digest `sha256:3a5dfb2e…` |
| 서버 dry-run | `kubectl apply --dry-run=server -f RAG/k8s/` | 통과 |
| 배포 | `kubectl apply -f RAG/k8s/` | `heartsignal-rag` **Running 1/1 (30초)**, PVC `heartsignal-rag-faiss` Bound(gp3 1Gi), initContainer가 `p1-complete`를 PVC에 시드 |
| 파드 로그 | `kubectl logs deploy/heartsignal-rag -c rag` | `VECTORSTORE_WEB/PDF 로드 완료`, `에이전트 근거 조회 준비`, `rank_bm25` 로드 |

**동작 확인** (`kubectl port-forward svc/heartsignal-rag 18082:8001`, `JWT_SECRET`으로 만든 worker·admin 토큰)

| 요청 | 결과 |
| --- | --- |
| `/rag-query` 암모니아 이격거리 / 황화수소 노출기준 | 200, 30m·150m / TWA 10·STEL 15 + 출처(절 단위), `handoff:false`, 3.2~3.3초 |
| `/rag-query` 염소 흡입 응급조치 ×4 | 2회 정답(`응급조치>흡입` 출처), 2회 `handoff:true` — 재작성 결과에 따라 검색 집합이 달라질 때 답변 LLM의 N/A 판정이 흔들리는 **알려진 편차**(`docs/eval_results.md` 9·10·16행). 클러스터 환경 문제 아님 |
| `POST /alarm` S1(출하장 프로판 3단계, admin) | 201, 에이전트 7개 도구 `ok`, 신고문에 CAS 74-98-6·UN 1978, 지침 카드 G-78 10.2(13) |
| `GET /board/current` (토큰 없음) | 200, 전광판 3줄 |
| `POST /alarm/{id}/clear` | 200 (시험 경보는 해제함) |
| **Ingress** `https://heartsignal.class-4.skala-us.com/openapi.json` / `/` | **200 / 200** (TLS 정상, P4가 Ingress 적용) |

아직 확인하지 않은 것: Ingress 경유 `/rag-query`(쿠키 포함) → web 화면 E2E, 시연 계정 시드(6.1)를 클러스터 DB에 적용, 확장 화면용 Ingress 경로 `/alarm`·`/board`(아직 없음), voice 배포.

### 8.3 시연 계정 시드 (2026-10-23 15:51, P3)

6.1 절차대로 Ingress 주소로 실행했습니다. 비밀번호는 `db/.env`(커밋 금지)에만 있고, 스크립트 실행 전 키 존재만 확인했습니다(값 미출력).

| 확인 | 결과 |
| --- | --- |
| Ingress TLS | `subject=CN=*.class-4.skala-us.com`, `issuer=Let's Encrypt` — 와일드카드 인증서 적용 |
| `GET https://heartsignal.class-4.skala-us.com/login` | 200 |
| `AUTH_URL=https://heartsignal.class-4.skala-us.com db/seed-demo-users.sh k8s` | exit 0 (출력 아래) |

```
인증 서버: https://heartsignal.class-4.skala-us.com (모드: k8s)
[admin1] 가입 완료
[admin1] 로그인 확인 — JWT role=admin
[foreman1] 가입 완료
[foreman1] 로그인 확인 — JWT role=foreman
[worker1] 가입 완료
[worker1] 로그인 확인 — JWT role=worker
시연 계정 3개 준비 완료
```

- DB 확인: `admin1`=admin, `foreman1`=foreman, `worker1`=worker. 가입 화면으로 만든 다른 계정은 모두 `worker`입니다(이름이 `admin`이어도 권한 없음).
- 시연은 `admin1`(경보 발령·보류·해제), `foreman1`(인원 점검), `worker1`(질의)로 로그인합니다. 비밀번호는 채팅·커밋에 올리지 않고 직접 전달합니다.
- role을 바꾼 뒤에는 **다시 로그인해야** 새 role이 JWT에 반영됩니다.

## 9. 남은 문제

- [x] **P3**: 로그인 성공 시 `http://localhost:8008/index.html`로 이동 → `LOGIN_REDIRECT_URL`(기본 `/#/home`)로 변경 ([#14](https://github.com/ForSKALA/HeartSignal/pull/14))
- [x] **음성**: `Voice-AI/app/main.py`의 `SECRET_KEY = "RANDOM_SECRET_KEY"` 하드코딩 → `JWT_SECRET` 환경변수로 변경 ([#8](https://github.com/ForSKALA/HeartSignal/pull/8))
- [ ] **음성**: torch CUDA 버전 설치로 이미지 3.49GB → CPU 전용 torch 권장
- [ ] **P4**: `Voice-AI/app/static/index.html`이 `http://localhost:8080/api/auth/check` 호출
- [ ] **P4**: AGENTS.md 5·6장에 k8s용 Service 이름·환경변수 값 추가 (6장 RAG 변수는 #23에서 반영)
- [ ] **P4**: 확장 화면(관리자·전광판·반장)용 Ingress 경로 `/alarm`, `/board` 추가 (rag 서비스)
- [ ] **전원**: Ingress 호스트 이름(안: `heartsignal.class-4.skala-us.com`), 이미지 태그 규칙, ArgoCD 사용 여부 확정
- [x] **P4·P3**: Ingress 배포 후 시연 계정 시드 실행 (6.1) → 2026-10-23 완료 (8.3)
