# P3 리뷰 반영 및 P4 요청: 같은 origin의 Voice 로그인

P3 제안에 동의합니다. 배포 화면은 `https://heartsignal.class-4.skala-us.com/voice/`를 사용하며 `ACCESS_TOKEN`은 현재 host-only 범위를 유지합니다. 부모 Domain 공유·별도 Voice CORS 추가·return_to 지원 요청은 철회합니다.

## 음성 담당 수정 범위

- 배포 로그인 대상은 Java `/login`이 아닌 Vue `/#/login`입니다.
- 배포 홈의 상태 확인은 같은 origin의 `/api/auth/check`입니다.
- 모든 화면 링크·API 호출·MP3 재생이 `/voice/` 아래에 유지됩니다. API 응답 필드와 `/uploads/...` 값은 기존대로 유지하고 화면에서 상대 경로로 해석합니다.
- Voice Deployment에 `uvicorn --root-path /voice`를 지정합니다. HTML의 base도 root_path를 따르므로 `/voice`와 `/voice/` 진입 모두 지원합니다.
- JWT의 role은 누락·알 수 없는 값 모두 worker로 통일했습니다. 서명·발급자·만료 검증과 API 401은 유지합니다.
- root_path가 있어도 `/voice/static/*.html` 직접 접근은 404입니다.
- 사용된 1.0.2 태그는 덮어쓰지 않고 다음 이미지 태그를 1.0.3으로 지정했습니다. 이번 수정본은 병합 전에 빌드·push·apply하지 않았습니다.

## P4 요청안

같은 origin 방식에 동의하며 Voice 코드 수정과 테스트를 완료했습니다. 별도 Voice Ingress를 아래 조건으로 준비 부탁드립니다.

- host: `heartsignal.class-4.skala-us.com`, namespace: `class-4`, ingressClassName: `nginx`
- path: `/voice(/|$)(.*)`, pathType: `ImplementationSpecific`
- annotations: `nginx.ingress.kubernetes.io/use-regex: "true"`, `nginx.ingress.kubernetes.io/rewrite-target: /$2`
- backend: `heartsignal-voice`, service port `8008`
- TLS: 기존 HeartSignal 호스트의 인증서 사용
- 필요 시 기존 음성 업로드 크기·응답 대기 시간 설정도 새 Ingress에 반영

rewrite annotation은 **새 Voice 전용 Ingress에만** 적용해 주세요. 기존 Ingress에 rewrite를 추가하지 않습니다. 같은 호스트의 기존 `/api`, `/`, `/rag-query` 라우팅도 회귀 확인해 주세요. 기존 `heartsignal-voice.*` 주소는 로그인 진입점에서 제외하고 제거하거나 동일 origin Voice 주소로 이동하도록 정리 부탁드립니다.

Vue 로그인 성공 후에는 기본 홈으로 이동하므로, 화면에서 Voice를 쓸 계획이면 홈에 `/voice/` 진입 링크도 추가 부탁드립니다. 로그인 후 Voice로 자동 복귀시키는 return_to 기능은 요청하지 않습니다.

## P3 요청안

부모 Domain 방식은 사용하지 않고 host-only 쿠키를 그대로 사용하겠습니다. 별도 Voice CORS 추가·return_to 구현은 필요하지 않습니다. 제안하신 Secure 쿠키는 별도 PR로 진행 부탁드립니다. role도 누락·알 수 없는 값 모두 worker로 맞췄습니다.

## 병합 후 배포 및 공동 검증

1. Voice PR 및 P4 Ingress 변경을 리뷰·병합한 뒤 main을 기준으로 1.0.3 이미지를 빌드·push합니다. P4와 일정을 맞춰 apply합니다. 현재 배포된 1.0.2는 이번 수정본과 다릅니다.
2. 같은 호스트에서 로그아웃 상태로 `/voice/`에 접근하면 `/#/login`으로 이동해야 합니다.
3. Vue 로그인 후 `/voice/`에 다시 접근하면 화면 200, `/voice/auth-config.js` 200, `/api/auth/check` 200이어야 합니다.
4. `/voice/stt/`, `/voice/tts/`, `/voice/stt-tts/` 요청과 `/voice/uploads/...` 재생 경로를 브라우저 네트워크 탭에서 확인합니다.
5. ACCESS_TOKEN이 host-only·HttpOnly·Path=/·SameSite=Lax를 유지하고 P3 PR 이후 Secure인지 확인합니다. 다른 class-4 서비스에 이 쿠키가 전달되지 않는지도 확인합니다.
6. 로그아웃 후 Voice HTML은 로그인으로 이동하고 음성 API는 401이어야 합니다.
7. 실제 브라우저 로그인과 배포 환경 음성 생성은 위 공동 배포 후 검증합니다. 회귀 테스트는 테스트 JWT·모의 TTS를 사용했습니다. 별도로 로컬 앱에서 실제 OpenAI TTS 1건을 검증해 합성 API·MP3 조회 모두 200, 78,336바이트·24kHz·4.9초 MP3 디코딩 및 무음 아님을 확인했습니다. 이 검증은 배포 쿠키 공유 검증을 대체하지 않습니다.

이 문서는 전달용 요청안입니다. backend·P4 Ingress·공통 ConfigMap은 직접 수정하지 않았으며 별도 메시지를 발송하지 않았습니다.
