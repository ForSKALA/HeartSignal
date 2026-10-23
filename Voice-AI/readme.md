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
./docker-build.sh 1.0.2
./docker-push.sh 1.0.2
kubectl --context skala-admin-sa@class-4 -n class-4 apply -f k8s/
kubectl --context skala-admin-sa@class-4 -n class-4 rollout status deployment/heartsignal-voice --timeout=180s
```

Harbor 인증 환경변수와 배포 대상은 팀 배포 가이드를 따릅니다. 이미 사용된 태그를 덮어쓰지 말고 새 태그와 Deployment 이미지 설정을 함께 갱신합니다.

## CPU 추론 의존성

`faster-whisper`는 CTranslate2로 추론하므로 `torch`와 그에 따라 설치되던 CUDA 패키지를 제외합니다. Whisper small 모델과 FFmpeg는 계속 이미지에 포함됩니다.

### 이미지 크기 검증

동일한 로컬 Docker에서 컨테이너 실행 후 `docker image ls heartsignal-voice`로 비교했습니다.

| 태그 | 구성 | 표시 크기 |
| --- | --- | --- |
| 1.0.0 | Whisper small 포함 + torch/CUDA 의존성 | 11.1GB |
| 1.0.1 | Whisper small 포함, torch/CUDA 제외 | 2.56GB |

약 77% 감소했습니다. `--network none` 컨테이너에서 한국어 STT와 API 기동, `pip check`를 검증했습니다. Docker 저장소·크기 표시 방식에 따라 실제 표시값은 달라질 수 있습니다.

## Voice 화면 로그인

- 로컬·배포 인증 주소는 `app/auth.py`에서 관리하며, 홈 화면은 `/auth-config.js`를 사용합니다.
- 배포 인증 주소는 `https://heartsignal.class-4.skala-us.com`입니다. API 키나 JWT는 공개 설정에 포함하지 않습니다.
- 인증되지 않은 HTML 탐색은 로그인으로 이동하며 `/stt/`, `/tts/`, `/stt-tts/`의 미인증 요청은 401을 유지합니다.
- 활성 음성 API와 화면은 `app/auth.py`의 JWT 검증을 공유합니다. `.env`는 라우터 import 전에 로드합니다.
- 로그인 서버가 `return_to`를 지원하기 전에는 로그인 후 기본 메인 화면으로 이동합니다. 쿠키 공유·CORS가 적용된 뒤 Voice에 다시 접근할 수 있습니다.
- 별도 Voice 호스트 로그인 완료에는 P3의 쿠키·CORS·복귀 URL 처리가 필요합니다. 요청안은 `docs/p3-auth-request.md`를 참고하세요.
- 인증 테스트: `python -m unittest discover -s tests -v` (모델·외부 API 모의 처리).

홈 스크립트 테스트: `node tests/test_login_script.cjs` (Node.js 사용 가능한 개발 환경).
