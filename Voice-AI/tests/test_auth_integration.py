"""모델 다운로드·유료 API 없이 로그인 경로와 JWT 연동을 검증한다."""

import os
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

os.environ["OPENAI_API_KEY"] = "test-not-a-real-api-key"
os.environ["JWT_SECRET"] = "test-environment-key-not-the-demo-key"
os.environ["JWT_ISSUER"] = "test-issuer"

# 인증 검증에는 음성 모델이 필요하지 않다.
stt = types.ModuleType("app.services.stt_service")
stt.transcribe_audio_file_local = Mock(return_value="테스트")
stt.convert_webm_to_wav = Mock()
sys.modules["app.services.stt_service"] = stt

from fastapi.testclient import TestClient
from jose import jwt
from app.main import app


class AuthIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://heartsignal.class-4.skala-us.com")

    def token(self, **changes):
        payload = {
            "sub": "1", "username": "tester", "role": "worker",
            "iss": "test-issuer", "exp": int(time.time()) + 300,
        }
        payload.update(changes)
        return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")

    def test_html_redirects_to_same_origin_vue_login(self):
        for path in ["/", "/index.html", "/stt.html", "/tts.html", "/stt-tts.html"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], "/#/login")

    def test_local_redirect_uses_vue(self):
        with TestClient(app, base_url="http://localhost:8008") as client:
            response = client.get("/tts.html", follow_redirects=False)
            self.assertEqual(response.headers["location"], "http://localhost:5174/#/login")

    def test_public_config_has_no_secret_or_localhost_in_deployment(self):
        response = self.client.get("/auth-config.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn('"auth_base_url": ""', response.text)
        self.assertIn('"login_url": "/#/login"', response.text)
        self.assertNotIn("return_to", response.text)
        self.assertNotIn("localhost", response.text)
        self.assertNotIn(os.environ["JWT_SECRET"], response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_all_audio_apis_still_reject_missing_auth(self):
        for path in ["/stt/", "/tts/", "/stt-tts/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, data={"text": "테스트"}).status_code, 401)

    def test_environment_signed_cookie_opens_all_pages(self):
        self.client.cookies.set("ACCESS_TOKEN", self.token())
        for path in ["/index.html", "/stt.html", "/tts.html", "/stt-tts.html"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_environment_signed_cookie_reaches_tts_service(self):
        self.client.cookies.set("ACCESS_TOKEN", self.token())
        with patch("app.routers.tts_router.text_to_speech", return_value="test.mp3") as synthesize:
            response = self.client.post("/tts/", data={"text": "테스트"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["user"]["role"], "worker")
            synthesize.assert_called_once()

    def test_invalid_tokens_never_reach_tts(self):
        invalid = [self.token(exp=1), self.token(iss="wrong-issuer")]
        invalid.append(jwt.encode({"sub": "1", "username": "tester", "iss": "test-issuer", "exp": int(time.time()) + 300}, "RANDOM_SECRET_KEY", algorithm="HS256"))
        invalid.append(self.token(exp=None))
        with patch("app.routers.tts_router.text_to_speech") as synthesize:
            for token in invalid:
                with self.subTest(token_type="invalid"):
                    self.client.cookies.set("ACCESS_TOKEN", token)
                    self.assertEqual(self.client.post("/tts/", data={"text": "테스트"}).status_code, 401)
            synthesize.assert_not_called()

    def test_unknown_and_missing_roles_become_worker(self):
        for role in ["device", "owner", "", None, 123, [], {}]:
            with self.subTest(role=role), patch("app.routers.tts_router.text_to_speech"):
                self.client.cookies.set("ACCESS_TOKEN", self.token(role=role))
                response = self.client.post("/tts/", data={"text": "테스트"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["user"]["role"], "worker")
        payload = {"sub": "1", "username": "tester", "iss": "test-issuer", "exp": int(time.time()) + 300}
        self.client.cookies.set("ACCESS_TOKEN", jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256"))
        with patch("app.routers.tts_router.text_to_speech"):
            self.assertEqual(self.client.post("/tts/", data={"text": "테스트"}).json()["user"]["role"], "worker")

    def test_known_roles_are_preserved(self):
        for role in ["worker", "foreman", "admin"]:
            with patch("app.routers.tts_router.text_to_speech"):
                self.client.cookies.set("ACCESS_TOKEN", self.token(role=role))
                self.assertEqual(self.client.post("/tts/", data={"text": "테스트"}).json()["user"]["role"], role)

    def test_voice_prefix_preserves_login_html_api_and_static_block(self):
        with TestClient(app, root_path="/voice", base_url="https://heartsignal.class-4.skala-us.com") as client:
            for path in ["/", "/tts.html", "/voice/", "/voice/tts.html"]:
                response = client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], "/#/login")
            self.assertEqual(client.post("/voice/tts/", data={"text": "테스트"}).status_code, 401)
            client.cookies.set("ACCESS_TOKEN", self.token(), domain="heartsignal.class-4.skala-us.com", path="/")
            for path in ["/voice/", "/voice/index.html", "/voice/stt.html", "/voice/tts.html", "/voice/stt-tts.html", "/voice"]:
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('<base href="/voice/">', response.text)
            with patch("app.routers.tts_router.text_to_speech"):
                response = client.post("/voice/tts/", data={"text": "테스트"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["user"]["role"], "worker")
            self.assertEqual(client.get("/voice/auth-config.js").status_code, 200)
            self.assertEqual(client.get("/voice/static/index.html").status_code, 404)
            client.cookies.clear()
            self.assertEqual(client.post("/voice/tts/", data={"text": "테스트"}).status_code, 401)

    def test_auth_cookie_does_not_authenticate_sibling_voice_host(self):
        with TestClient(app, base_url="https://heartsignal-voice.class-4.skala-us.com") as client:
            client.cookies.set("ACCESS_TOKEN", self.token(), domain="heartsignal.class-4.skala-us.com", path="/")
            self.assertEqual(client.post("/tts/", data={"text": "테스트"}).status_code, 401)

    def test_static_html_bypass_remains_blocked(self):
        self.assertEqual(self.client.get("/static/index.html").status_code, 404)


if __name__ == "__main__":
    unittest.main()
