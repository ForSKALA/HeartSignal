# HeartSignal 쿠버네티스 배포 순서

> 팀 공유 가이드: https://claude.ai/artifact/W1dLUXnTtA4reRMuppJwLc
> 네임스페이스 `class-4`, 이미지 `skala-registry.skala-us.com/class-4/heartsignal-<서비스>:<VERSION>`

## 0. 공통 (P4, 1회)

```bash
web/k8s/create-secret.sh                 # 루트 .env → heartsignal-secret
kubectl apply -f web/k8s/configmap.yaml  # heartsignal-config
```

## 1. 이미지 빌드·push (각 파트)

```bash
<서비스폴더>/docker-build.sh 1.0.0
<서비스폴더>/docker-push.sh 1.0.0       # DOCKER_REGISTRY, DOCKER_REGISTRY_USER, DOCKER_REGISTRY_PASSWORD 필요
```

| 서비스 | 폴더 | 담당 |
| --- | --- | --- |
| rag | `RAG/` | P2 |
| auth | `backend/` | P3 |
| web | `web/` | P4 |
| voice | `Voice-AI/` | 음성 (선택) |

VERSION을 바꾸면 해당 `k8s/deployment.yaml`의 `image:` 태그도 같이 바꿔 PR로 올립니다.

## 2. 적용 (자기 서비스 폴더만 apply)

```bash
# P3: DB → auth
db/k8s/create-init-configmap.sh
kubectl apply -f db/k8s/
kubectl rollout status statefulset/heartsignal-db -n class-4
kubectl apply -f backend/k8s/

# P2: rag
kubectl apply -f RAG/k8s/

# 음성(선택): voice
kubectl apply -f Voice-AI/k8s/

# P4: web + ingress
kubectl apply -f web/k8s/
```

## 3. 확인

```bash
kubectl get pods,svc,ingress,pvc -n class-4 -l part-of=heartsignal
kubectl logs -n class-4 deploy/heartsignal-rag
curl -I https://heartsignal.class-4.skala-us.com/
curl -s https://heartsignal.class-4.skala-us.com/openapi.json | head -c 200
```

## 주의

- `kubectl delete -f` 는 자기 서비스 폴더만. `db/k8s` 삭제 후에도 PVC(`data-heartsignal-db-0`)는 남습니다.
- Secret 값은 채팅·커밋으로 공유하지 않습니다.
