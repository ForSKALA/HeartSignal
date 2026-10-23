#!/bin/bash
# db/init/*.sql 을 heartsignal-db-init ConfigMap으로 만든다 (원본은 db/init 하나로 유지).
# 다시 실행하면 덮어쓴다. 이미 초기화된 DB에는 다시 실행되지 않는다.

INIT_DIR="$(dirname "$0")/../init"

kubectl create configmap heartsignal-db-init \
  --namespace class-4 \
  --from-file="${INIT_DIR}" \
  --dry-run=client -o yaml | kubectl apply -f -
