#!/bin/bash
# HeartSignal 시연 계정 시드: admin1(admin) · foreman1(foreman) · worker1(worker)
#
# - 가입은 인증 서버 /api/signup 으로 한다 (비밀번호 해시는 서버의 bcrypt 그대로).
# - role 은 가입 화면에서 받지 않으므로(AGENTS.md 7.1) DB 에서 직접 부여한다.
# - 비밀번호는 env 파일(커밋 금지)에서만 읽는다. 여러 번 실행해도 결과가 같다.
#
# 사용법
#   db/seed-demo-users.sh            # 로컬: docker compose DB + 인증 서버 :8080
#   db/seed-demo-users.sh k8s        # k8s: heartsignal-db-0 파드 + AUTH_URL(Ingress 주소)
#
# 환경변수 (env 파일 또는 셸)
#   SEED_ADMIN_PASSWORD, SEED_FOREMAN_PASSWORD, SEED_WORKER_PASSWORD   (필수)
#   ENV_FILE      기본 db/.env
#   AUTH_URL      기본 로컬 http://localhost:8080 / k8s 는 필수 (예: https://heartsignal.class-4.skala-us.com)
#   DB_CONTAINER  로컬 DB 컨테이너 이름 (기본 heartsignal-mariadb)
#   K8S_NAMESPACE, DB_POD   (기본 class-4, heartsignal-db-0)

set -euo pipefail

MODE="${1:-local}"
if [ "${MODE}" != "local" ] && [ "${MODE}" != "k8s" ]; then
  echo "사용법: $0 [local|k8s]" >&2
  exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

: "${SEED_ADMIN_PASSWORD:?SEED_ADMIN_PASSWORD 가 없습니다 (${ENV_FILE})}"
: "${SEED_FOREMAN_PASSWORD:?SEED_FOREMAN_PASSWORD 가 없습니다 (${ENV_FILE})}"
: "${SEED_WORKER_PASSWORD:?SEED_WORKER_PASSWORD 가 없습니다 (${ENV_FILE})}"

case "${MODE}" in
  local)
    AUTH_URL="${AUTH_URL:-http://localhost:8080}"
    DB_CONTAINER="${DB_CONTAINER:-heartsignal-mariadb}"
    run_sql() { docker exec -i "${DB_CONTAINER}" sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" sql_db'; }
    ;;
  k8s)
    : "${AUTH_URL:?k8s 모드에서는 AUTH_URL(Ingress 주소)이 필요합니다}"
    K8S_NAMESPACE="${K8S_NAMESPACE:-class-4}"
    DB_POD="${DB_POD:-heartsignal-db-0}"
    run_sql() { kubectl exec -i -n "${K8S_NAMESPACE}" "${DB_POD}" -c mariadb -- sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" sql_db'; }
    ;;
esac
AUTH_URL="${AUTH_URL%/}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

# 비밀번호는 명령줄 인자(ps 에 보임) 대신 표준입력으로 curl 에 넘긴다
post_form() {  # post_form <path> <username> <password> <cookie_jar> → HTTP 상태 출력
  : > "${TMP_DIR}/body"
  printf '%s' "$3" | curl -s -o "${TMP_DIR}/body" -w '%{http_code}' -c "$4" \
    --data-urlencode "username=$2" --data-urlencode "password@-" "${AUTH_URL}$1" || true
}

jwt_role() {  # 쿠키 파일의 ACCESS_TOKEN 에서 role 클레임을 꺼낸다
  local payload
  payload="$(awk '$6=="ACCESS_TOKEN"{print $7}' "$1" | cut -d. -f2 | tr '_-' '/+')"
  while [ $(( ${#payload} % 4 )) -ne 0 ]; do payload="${payload}="; done
  printf '%s' "${payload}" | base64 --decode 2>/dev/null | sed -n 's/.*"role":"\([a-z]*\)".*/\1/p'
}

seed() {  # seed <username> <role> <password>
  local user="$1" role="$2" password="$3" jar="${TMP_DIR}/$1.cookies" status

  status="$(post_form /api/signup "${user}" "${password}" /dev/null)"
  case "${status}" in
    200) echo "[${user}] 가입 완료" ;;
    409) echo "[${user}] 이미 있음 — 가입 건너뜀" ;;
    000) echo "[${user}] 인증 서버(${AUTH_URL})에 연결할 수 없습니다." >&2; return 1 ;;
    *)   echo "[${user}] 가입 실패 (HTTP ${status}): $(cat "${TMP_DIR}/body")" >&2; return 1 ;;
  esac

  # 사용자 이름·role 은 이 스크립트의 고정값이라 SQL 에 그대로 넣어도 안전하다
  printf "UPDATE users SET role = '%s' WHERE username = '%s';\n" "${role}" "${user}" | run_sql

  status="$(post_form /api/login "${user}" "${password}" "${jar}")"
  if [ "${status}" != "200" ]; then
    echo "[${user}] 로그인 실패 (HTTP ${status}). 이미 있던 계정이면 비밀번호가 env 파일 값과 다릅니다." >&2
    return 1
  fi
  local got
  got="$(jwt_role "${jar}")"
  if [ "${got}" != "${role}" ]; then
    echo "[${user}] JWT role 불일치: 기대 ${role}, 실제 ${got:-없음}" >&2
    return 1
  fi
  echo "[${user}] 로그인 확인 — JWT role=${got}"
}

echo "인증 서버: ${AUTH_URL} (모드: ${MODE})"
failed=0
seed admin1   admin   "${SEED_ADMIN_PASSWORD}"   || failed=1
seed foreman1 foreman "${SEED_FOREMAN_PASSWORD}" || failed=1
seed worker1  worker  "${SEED_WORKER_PASSWORD}"  || failed=1

if [ "${failed}" -ne 0 ]; then
  echo "일부 계정 시드에 실패했습니다." >&2
  exit 1
fi
echo "시연 계정 3개 준비 완료"
