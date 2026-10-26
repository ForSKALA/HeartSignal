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
./docker-build.sh 1.0.4
./docker-push.sh 1.0.4
kubectl --context skala-admin-sa@class-4 -n class-4 apply -f k8s/
kubectl --context skala-admin-sa@class-4 -n class-4 rollout status deployment/heartsignal-voice --timeout=180s
```

PR 병합 후 main의 코드로 빌드·push·apply합니다. 이번 리뷰 반영본은 아직 이미지 빌드·push·클러스터 적용을 하지 않았습니다.

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

## Voice 화면 로그인 — 같은 origin

- 배포 화면 주소는 `https://heartsignal.class-4.skala-us.com/voice/`입니다. P4가 별도 Ingress에서 `/voice(/|$)(.*)`를 Voice 서비스 `8008`로 연결하고 `/$2`로 rewrite해야 합니다.
- `k8s/deployment.yaml`은 Uvicorn에 `--root-path /voice`를 지정합니다. 서버는 HTML에 `<base href="/voice/">`를 넣어 `/voice`와 `/voice/` 모두 상대 경로를 올바르게 해석합니다. 로컬 실행은 root_path 없이 `<base href="/">`를 사용합니다.
- 화면 링크·`auth-config.js`·STT/TTS/통번역 fetch는 상대 경로입니다. API 응답의 기존 `/uploads/...` 필드는 유지하고 화면에서 base 기준으로 해석하여 `/voice/uploads/...`로 재생합니다.
- 배포 홈은 같은 origin의 `/api/auth/check`를 호출합니다. 별도 Voice origin에 대한 CORS 추가·부모 Cookie Domain·`return_to` 지원은 요청하지 않습니다.
- 미인증 HTML은 같은 호스트의 Vue `/#/login`으로 이동합니다. 로그인 성공 후 기본 홈에서 `/voice/`에 다시 접근합니다. 로컬 Voice(`localhost:8008`)는 기존 auth(`localhost:8080`)와 Vue(`localhost:5174/#/login`)를 사용하며, 직접 다른 포트의 auth 상태 조회를 할 때는 로컬 CORS 설정이 별도로 필요합니다.
- 활성 음성 API와 화면은 `app/auth.py`의 JWT 검증을 공유합니다. `.env`는 라우터 import 전에 로드합니다. role 누락·알 수 없는 값은 공통 계약에 따라 `worker`이며, 서명·발급자·만료 오류는 401입니다.
- 요청안 및 공동 검증 절차는 `docs/p3-auth-request.md`에 있습니다. P4 Ingress와 P3 Secure 쿠키 적용 후 실제 로그인·로그아웃을 함께 검증합니다.
- Python 테스트: `python -m unittest discover -s tests -v` (외부 API·STT 모델 모의 처리).
- JavaScript 테스트: `node tests/test_login_script.cjs` (실제 홈/TTS 스크립트와 전체 화면의 prefix 유지 확인).

### 로컬 실제 TTS 확인

리뷰 반영 코드의 로컬 앱에서 테스트 JWT와 기존 `.env`의 키로 `tts-1`/`nova` 합성 1건을 실행했습니다. 합성 API 200, Voice TTS API 200, `/voice/uploads/...` 조회 200을 확인했습니다. 응답까지 3.87초, MP3 78,336바이트·24kHz·4.9초이며 전체 프레임 디코딩과 무음이 아님을 확인했습니다. 실제 사용자의 로그인·브라우저 재생·주관적인 음질은 별도 공동 검증 대상입니다.

## TTS 모델 변경: gpt-4o-mini-tts

`app/services/tts_service.py`의 합성 모델을 `gpt-4o-mini-tts`로 변경하고 응답 형식은 `mp3`로 명시합니다. 음색은 기존 `nova`를 유지합니다. 같은 함수를 사용하는 단독 `/tts/`와 통번역 `/stt-tts/`의 TTS 단계에 적용됩니다. 별도 환경변수·의존성은 추가하지 않습니다. 메인 화면의 브라우저 내장 음성(`web/src/voice.js`)과는 별개입니다.

OpenAI 공식 Speech API는 이 모델·음색·MP3 형식을 지원합니다. 다만 2026-10-26 확인한 [공식 음성 합성 안내](https://developers.openai.com/api/docs/guides/text-to-speech)는 `tts-1`과 `gpt-4o-mini-tts` 모두 2027-01-06 종료 예정이라고 명시합니다. 이번 변경은 요청된 모델로의 전환이며, 장기 운영을 위한 후속 API 전환은 별도로 계획해야 합니다.

### 검증 상태

- Python 인증 회귀 테스트 12개와 JavaScript 시나리오 8개 통과. 이 테스트는 외부 합성을 모의 처리하므로 실제 합성 성공을 뜻하지 않습니다.
- 초기 시도에서는 기존 로컬 키가 OpenAI HTTP 401 `invalid_api_key`로 거부돼 Voice API가 500을 반환했습니다. 이후 사용자가 로컬 키를 갱신한 뒤 아래와 같이 실제 합성에 성공했습니다.
- 배포 파드의 기존 환경에서도 수정된 함수만 별도 일회성 프로세스로 실행했습니다. 키 값을 꺼내거나 실행 서버 코드를 바꾸지 않았으며, 이 시도 역시 HTTP 401 `invalid_api_key`로 거부됐습니다.
- 2026-10-26 갱신한 로컬 키와 테스트 JWT로 수정된 앱에서 실제 한국어 합성 1건을 검증했습니다. 전송 모델 `gpt-4o-mini-tts`와 MP3 형식도 확인했습니다. OpenAI 합성·로컬 Voice API·파일 조회 모두 200, 응답까지 1.53초, MP3 93,696바이트·24kHz·5.86초입니다. 전체 프레임 디코딩과 무음 아님을 확인했습니다. 청취 품질 및 새 모델의 배포 브라우저 검증은 별도입니다. 이전 `tts-1` 이력은 위에 보존합니다.
- 이 변경본은 배포하지 않았습니다. 로컬 .env 갱신은 Kubernetes Secret에 자동 반영되지 않으므로 P4가 배포 키의 유효성을 확인·갱신해야 합니다. 리뷰·병합 후 새 이미지 태그와 Deployment 설정을 함께 갱신하고 배포 환경에서 검증합니다.
