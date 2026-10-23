# Install ffmpeg (Linux Ubuntu)
sudo apt update
sudo apt install -y ffmpeg pkg-config

# Install ffmpeg (MacOS)
brew install ffmpeg
ffmpeg -version

# With virtual environment activated
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

## 컨테이너의 Whisper 모델

- Docker 빌드 중 Whisper `small` 모델을 `/opt/whisper-model`에 다운로드합니다.
- 이미지의 `WHISPER_MODEL` 기본값은 이 로컬 경로입니다. 기존 STT 코드를 그대로 사용하며 파드 시작 시 모델을 다운로드하지 않습니다.
- Python 직접 실행 시에는 기존처럼 `WHISPER_MODEL=small` 또는 로컬 모델 경로를 설정할 수 있습니다.
- 컨테이너의 `WHISPER_MODEL`을 모델 이름으로 덮어쓰면 다시 네트워크 다운로드가 필요할 수 있습니다. 배포 시 기본 경로를 유지하세요.
- OpenAI API 키와 JWT 비밀키는 이미지에 포함하지 않습니다. Kubernetes에서는 준비된 Secret으로 주입합니다.
- 컨테이너 간 API 통신과 TTS에는 별도 네트워크 연결이 필요합니다. 모델 포함은 STT 모델 다운로드 의존성만 제거합니다.

## 이미지 빌드 및 배포

```bash
./docker-build.sh 1.0.0
./docker-push.sh 1.0.0
kubectl --context skala-admin-sa@class-4 -n class-4 apply -f k8s/
kubectl --context skala-admin-sa@class-4 -n class-4 rollout status deployment/heartsignal-voice --timeout=180s
```

Harbor 인증 환경변수와 배포 대상은 팀 배포 가이드를 따릅니다. 이미 사용된 태그를 덮어쓰지 말고 새 태그와 Deployment 이미지 설정을 함께 갱신합니다.
