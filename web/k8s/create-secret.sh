#!/bin/bash
# HeartSignal 공통 Secret(heartsignal-secret) 생성·갱신 (P4 한 사람만 실행)
# - 값은 저장소 루트 .env(커밋 금지)에서 읽는다. yaml로 커밋하지 않는다.
# - 다시 실행하면 같은 이름으로 덮어쓴다(apply).

ENV_FILE="$(dirname "$0")/../../.env"
[ -f "${ENV_FILE}" ] || { echo ".env 파일이 없습니다: ${ENV_FILE}"; exit 1; }

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

: "${OPENAI_API_KEY:?OPENAI_API_KEY가 .env에 없습니다}"
: "${JWT_SECRET:?JWT_SECRET가 .env에 없습니다}"
: "${DB_PASSWORD:?DB_PASSWORD가 .env에 없습니다}"

kubectl create secret generic heartsignal-secret \
  --namespace class-4 \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --from-literal=JWT_SECRET="${JWT_SECRET}" \
  --from-literal=DB_PASSWORD="${DB_PASSWORD}" \
  --from-literal=NAVER_CLIENT_ID="${NAVER_CLIENT_ID:-}" \
  --from-literal=NAVER_CLIENT_SECRET="${NAVER_CLIENT_SECRET:-}" \
  --dry-run=client -o yaml | kubectl apply -f -
