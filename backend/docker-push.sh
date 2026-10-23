#!/bin/bash
# HeartSignal heartsignal-auth 이미지를 Harbor에 push
# 사용: ./docker-push.sh [VERSION]   (기본 1.0.0, docker-build.sh와 같은 값)
# 필요 환경변수: DOCKER_REGISTRY, DOCKER_REGISTRY_USER, DOCKER_REGISTRY_PASSWORD, CLASS_NAME

IMAGE_NAME="heartsignal-auth"
VERSION=${1:-1.0.0}
PROJECT_NAME=${CLASS_NAME:-class-4}

DOCKER_REGISTRY=${DOCKER_REGISTRY:?DOCKER_REGISTRY 환경변수가 필요합니다}


# 1. Docker 레지스트리에 로그인 (옵션: 이 스크립트를 실행하기 전에 미리 로그인해두어도 됩니다)
echo ${DOCKER_REGISTRY_PASSWORD} | docker login ${DOCKER_REGISTRY} \
	-u ${DOCKER_REGISTRY_USER}  --password-stdin \
   	|| { echo "Docker 로그인 실패"; exit 1; }

# 2. harbor 로 push 하기 위해 tag 추가
docker tag  ${IMAGE_NAME}:${VERSION} ${DOCKER_REGISTRY}/${PROJECT_NAME}/${IMAGE_NAME}:${VERSION}


# Docker 이미지 푸시
docker push ${DOCKER_REGISTRY}/${PROJECT_NAME}/${IMAGE_NAME}:${VERSION}
