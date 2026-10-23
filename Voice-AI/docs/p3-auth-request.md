# P3 요청: Voice-AI 로그인 연동

Voice 화면에서 로그인을 사용합니다. 대상은 `https://heartsignal-voice.class-4.skala-us.com`입니다.

## Voice 담당 완료 범위

- 인증 주소를 `app/auth.py` 한 곳에서 관리합니다. 로컬은 `http://localhost:8080`, 배포는 `https://heartsignal.class-4.skala-us.com`입니다.
- `/auth-config.js`는 공개 주소 설정만 제공합니다. JWT·비밀값을 응답하지 않습니다.
- 홈의 인증 확인은 `credentials: include`로 auth의 `/api/auth/check`를 호출합니다.
- 미인증 HTML은 auth `/login?return_to=...`로 이동합니다. 음성 API는 리다이렉트하지 않고 401을 유지합니다.
- 모든 활성 음성 라우터가 같은 `JWT_SECRET`·`JWT_ISSUER`로 검증합니다.
- 쿠키는 Voice가 발급하거나 복사하지 않습니다. 브라우저의 공통 `ACCESS_TOKEN` 계약을 사용합니다.

## P3에게 요청할 사항

1. auth의 CORS 허용 목록에 `https://heartsignal-voice.class-4.skala-us.com`을 추가해 주세요. 기존 허용 목록은 유지하고, 해당 Origin의 GET·OPTIONS·401 응답에도 정확한 Origin과 `Access-Control-Allow-Credentials: true`가 반환되는지 확인해 주세요. 로컬 시험에는 `http://localhost:8008`도 필요합니다.
2. 현재 쿠키에는 Domain이 없어 auth 호스트에만 전달됩니다. Voice에 JWT가 전달되도록 쿠키 공유 방식을 검토해 주세요. 공통 부모 Domain(`class-4.skala-us.com`)은 다른 class-4 서비스까지 범위가 넓어지므로 보안 검토가 필요합니다. 부적절하면 P4와 동일 origin 프록시 방식을 협의해 주세요. Voice 쪽은 Domain을 임의로 확대하지 않았습니다.
3. 배포 쿠키의 Secure·HttpOnly·Path·SameSite와 만료 정책을 확인해 주세요. 로그아웃 때에도 발급 때와 같은 Domain·Path로 삭제하고, 기존 host-only 쿠키가 남아 같은 이름의 쿠키가 중복되지 않도록 정리해 주세요.
4. Voice는 로그인 URL에 `return_to`를 붙입니다. 현재 로그인 화면·API는 이를 처리하지 않으므로, 로그인 성공 후 Voice로 복귀하도록 지원해 주세요. 허용 대상은 배포 Voice origin과 개발용 로컬 Voice origin으로 제한하고, 임의 URL로 이동하는 open redirect가 생기지 않도록 검증해 주세요. 기존 로그인 기본 이동 주소는 유지해 주세요.
5. Voice 코드에서 기본 role 누락은 현재 AGENTS.md 7.1의 worker 대체 규칙을 따릅니다. 실제 P3 계약이 누락 시 401로 바뀌었다면 공통 문서와 함께 알려 주세요.

## 공동 완료 확인

- auth 로그인 후 Voice에 접근하면 HTML 200, 음성 API도 환경변수 기반 JWT를 수락해야 합니다.
- Voice에서 auth check 요청의 CORS·쿠키가 정상 동작해야 합니다.
- 로그아웃 후 Voice의 HTML은 로그인으로 이동하고 API는 401이어야 합니다.
- 실제 로그인 후 복귀와 쿠키 공유는 P3 변경 이후 브라우저로 함께 확인합니다.

본 문서는 전달용 요청안입니다. P3 소유 backend·공통 ConfigMap·쿠키 설정을 Voice 담당이 직접 수정하거나 적용하지 않습니다.

## 확인한 배포 상태

Voice Origin을 넣어 auth `/api/auth/check`를 조회했을 때 GET은 401, OPTIONS는 204였고 두 응답 모두 `Access-Control-Allow-Origin`·`Access-Control-Allow-Credentials`가 없었습니다. 무인증 요청만 사용했으며 실제 계정으로 로그인하지 않았습니다.
