#!/bin/bash
# HeartSignal heartsignal-auth 이미지 빌드
# 사용: ./docker-build.sh [VERSION]   (기본 1.0.0)
# - 클러스터 노드가 amd64이므로 linux/amd64로 빌드한다.

IMAGE_NAME="heartsignal-auth"
VERSION=${1:-1.0.0}
#IS_CACHE="--no-cache"

cd "$(dirname "$0")" || exit 1

# Docker 이미지 빌드
docker buildx build \
  --tag ${IMAGE_NAME}:${VERSION} \
  --file Dockerfile \
  --platform linux/amd64 \
  --load \
  ${IS_CACHE} .
