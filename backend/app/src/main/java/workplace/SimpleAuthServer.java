/*
##### The following practice code is intended for educational purposes only. For contact : architect@ajou.ac.kr, audit@korea.ac.kr 林圣烨 Ph.D.
#### This practice code is not a completed commercial version but has been developed for educational purposes; supplementation is required depending on the deployment objective for use as a commercial service.

```java

Guide for copying or moving the entire gradle directory (when receiving source code)
At this time, copy/move the entire folder containing gradlew, settings.gradle (or .kts), build.gradle (or .kts)

1. If ports such as 8080 (Java) or 8008 (FastAPI) are in use, disconnect them first
    lsof -iTCP:8080 -sTCP:LISTEN
    lsof -iTCP:8008 -sTCP:LISTEN
2. If a PID exists, terminate it
    kill -9 <PID>
3. In the new directory root, stop the Gradle Daemon
    ./gradlew --stop
    or pkill -f GradleDaemon || true
4. Completely delete local cache/build artifacts of the project
    rm -rf .gradle
    rm -rf build
    find . -name build -type d -prune -exec rm -rf {} +
*/
// or rm -rf **/build
/*
5. On first run, execute with cache disabled
    ./gradlew :app:clean --no-configuration-cache --no-build-cache
    ./gradlew :app:run   --no-configuration-cache --no-build-cache
6. Add the following to gradle.properties in the project root:
    org.gradle.configuration-cache=false
    org.gradle.caching=false

7. The users schema to be used by the authentication server must be created in advance (Ground Rule: table names must be written in lowercase)
    CREATE TABLE `users` (
    `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
    `username` varchar(100) NOT NULL,
    `password` varchar(255) NOT NULL,
    `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
    `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_users_username` (`username`)
    ) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    SELECT * FROM sql_db.users;
8. Run (e.g. from root directory workplace)
    workplace % ./gradlew build
    ./gradlew :app:run --no-configuration-cache
*/

package workplace;

import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import static workplace.HttpUtil.addCorsHeaders;
import static workplace.HttpUtil.cookie;
import static workplace.HttpUtil.getCookieValue;
import static workplace.HttpUtil.methodNotAllowed;
import static workplace.HttpUtil.notFound;
import static workplace.HttpUtil.parseFormBody;
import static workplace.HttpUtil.redirect;
import static workplace.HttpUtil.serveResource;
import static workplace.HttpUtil.writeJson;
import static workplace.HttpUtil.writeText;
import static workplace.TextUtil.escapeHtml;
import static workplace.TextUtil.escapeJson;
import static workplace.TextUtil.isBlank;
import static workplace.TextUtil.trimToNull;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.sql.SQLIntegrityConstraintViolationException;

// java.util – Specify only what is needed
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;

/*
Pure Java + HttpServer + MariaDB + Session + JWT Example

Modification history:
  1) Applied username/password trim on login/signup (prevents invalid_credentials caused by whitespace)
  2) Unified cookie creation/deletion attributes (cookie() helper)
     - Prevents missing cookie deletion or attribute mismatch on logout
  3) Added CORS + credentials support for /api/auth/check
  4) Maintained redirect to http://localhost:8008/index.html on successful login
  5) Added DEBUG logs to identify login failure causes
     - Outputs raw params / username/password / bcrypt matches result to console
  6) [HeartSignal P3] 내부 static class를 영역별 파일로 분리
     - User / UserRepository / JdbcUserRepository / AuthService / JwtUtil / HttpUtil / TextUtil
     - 이 파일에는 설정값·세션 저장소·라우팅(main)만 남김
  7) [HeartSignal P3] users.role 컬럼 + JWT role 클레임 추가, /api/auth/check 응답에 role 포함
 */

public class SimpleAuthServer {

    // ==== DB CONFIG (modify according to your environment) ==== //
    // k8s 등에서는 DB_URL 환경변수로 주입 (없으면 로컬 docker compose DB)
    private static final String DB_URL = System.getenv().getOrDefault("DB_URL", "jdbc:mariadb://localhost:53301/sql_db");
    private static final String DB_USER = "root";
    private static final String DB_PASSWORD = System.getenv("DB_PASSWORD");

    // ==== SESSION STORE ==== //
    private static final Map<String, User> SESSION_STORE = new ConcurrentHashMap<>();
    private static final String SESSION_COOKIE_NAME = "SESSION_ID";

    // ==== JWT COOKIE NAME ==== //
    private static final String JWT_COOKIE_NAME = "ACCESS_TOKEN";

    // ==== (Optional) Cookie name for login status check in Vue ==== //
    private static final String APP_AUTH_COOKIE_NAME = "APP_AUTH";

    // ==== DEBUG ==== //
    static final boolean DEBUG = true;

    public static void main(String[] args) throws Exception {
        // 비밀값이 없으면 기동하지 않는다 (JwtUtil 클래스 초기화 실패보다 원인을 먼저 알린다)
        if (isBlank(System.getenv("JWT_SECRET"))) {
            System.err.println("[BOOT] JWT_SECRET 환경변수가 없습니다. .env 를 확인하세요.");
            System.exit(1);
        }

        // Load JDBC Driver
        Class.forName("org.mariadb.jdbc.Driver");

        System.out.println("=== SimpleAuthServer v2026-02-03-REPLACED ===");
        System.out.println("Server started at http://localhost:8080");

        //  어떤 계층이 DB 접근을 담당해야 하는가? Repository 구현체를 생성하여 서비스와 연결하세요.
        UserRepository userRepository = new JdbcUserRepository(DB_URL, DB_USER, DB_PASSWORD);
        //  HTTP 처리부가 SQL을 직접 실행하지 않도록 인증 서비스에 저장소를 주입하세요.
        AuthService authService = new AuthService(userRepository);

        HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
        server.setExecutor(Executors.newFixedThreadPool(10));

        // GET / -> /login redirect
        server.createContext("/", exchange -> {
            if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                redirect(exchange, "/login");
            } else {
                methodNotAllowed(exchange);
            }
        });

        // GET /login -> login.html
        server.createContext("/login", exchange -> {
            if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                serveResource(exchange, "web/login.html", "text/html; charset=utf-8");
            } else {
                methodNotAllowed(exchange);
            }
        });

        // GET /signup -> signup.html
        server.createContext("/signup", exchange -> {
            if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                serveResource(exchange, "web/signup.html", "text/html; charset=utf-8");
            } else {
                methodNotAllowed(exchange);
            }
        });

        // GET /static/* -> CSS/JS
        server.createContext("/static", exchange -> {
            if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }
            String path = exchange.getRequestURI().getPath(); // /static/style.css
            String filename = path.replaceFirst("/static/?", "");
            if (filename.isEmpty()) {
                notFound(exchange);
                return;
            }

            String resourcePath = "web/" + filename;
            String contentType;
            if (filename.endsWith(".css")) {
                contentType = "text/css; charset=utf-8";
            } else if (filename.endsWith(".js")) {
                contentType = "application/javascript; charset=utf-8";
            } else {
                contentType = "application/octet-stream";
            }
            serveResource(exchange, resourcePath, contentType);
        });

        // POST /api/signup -> Sign up
        server.createContext("/api/signup", exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }
            Map<String, String> params = parseFormBody(exchange);

            String username = trimToNull(params.get("username"));
            String password = params.get("password");
            if (password != null) password = password.trim();

            if (DEBUG) {
                System.out.println("=== SIGNUP HIT ===");
                System.out.println("[SIGNUP] request received (credentials omitted)");
                System.out.println("[SIGNUP] username=" + username + ", pwLen=" + (password == null ? "null" : password.length()));
            }

            if (isBlank(username) || isBlank(password)) {
                writeText(exchange, 400, "username and password are required");
                return;
            }

            try {
                //  회원가입 요청을 어떤 계층으로 위임해야 하는가?
                // (role 은 받지 않는다: 가입자는 항상 worker, 다른 role 은 관리자가 DB 에서 부여)
                authService.signUp(username, password);redirect(exchange, "/login");
            } catch (SQLIntegrityConstraintViolationException dup) {
                writeText(exchange, 400, "username already exists");
            } catch (Exception e) {
                e.printStackTrace();
                writeText(exchange, 500, "signup error");
            }
        });

        // POST /api/login
        // Login + Session + JWT issuance + (Important) No 302 redirect → Return 200 JSON
        server.createContext("/api/login", exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }

            try {
                Map<String, String> params = parseFormBody(exchange);
                String username = params.get("username");
                String password = params.get("password");

                System.out.println("[LOGIN] content-type=" + exchange.getRequestHeaders().getFirst("Content-Type"));
                System.out.println("[LOGIN] username(trim)=" + (username == null ? "null" : username.trim())
                        + ", pwLen=" + (password == null ? -1 : password.length()));

                if (isBlank(username) || isBlank(password)) {
                    writeJson(exchange, 400, "{\"ok\":false,\"error\":\"username and password are required\"}");
                    return;
                }

                // [① 로그인 연결] 서비스의 로그인 결과를 받아 실패 시 401, 성공 시 쿠키 발급으로 이어지게 하세요.
                User user = authService.login(username, password);
                if (user == null) {
                    writeJson(exchange, 401, "{\"ok\":false,\"error\":\"invalid credentials\"}");
                    return;
                }

                // 1) Session Cookie
                String sessionId = UUID.randomUUID().toString();
                //  서버 측 세션 상태를 어떤 키로 보관해야 이후 쿠키를 통해 찾을 수 있는가?
                SESSION_STORE.put(sessionId, user);exchange.getResponseHeaders().add(
                        "Set-Cookie",
                        SESSION_COOKIE_NAME + "=" + sessionId + "; Path=/; HttpOnly; SameSite=Lax"
                );

                // 2) JWT Cookie
                //  서버 측 세션과 별개로 검증 가능한 토큰을 발급하세요.
                String jwt = JwtUtil.createToken(user);
                exchange.getResponseHeaders().add(
                        "Set-Cookie",
                        JWT_COOKIE_NAME + "=" + jwt + "; Path=/; HttpOnly; SameSite=Lax"
                );

                // 3) Cookie for frontend login status check (readable by JS)
                exchange.getResponseHeaders().add(
                        "Set-Cookie",
                        APP_AUTH_COOKIE_NAME + "=1; Path=/; SameSite=Lax"
                );

                // 4) (Most important) Do not redirect here — end with 200 JSON response
                //    → In fetch/XHR environments, 302 redirects easily cause HTTP 0/cancellation
                //  fetch 호출에서는 서버 302 대신 성공 JSON으로 이동 경로를 알립니다.
                writeJson(exchange, 200, "{\"ok\":true,\"redirect\":\"http://localhost:8008/index.html\"}");System.out.println("[LOGIN] SUCCESS -> 200 JSON (no redirect)");
                return;

            } catch (Exception e) {
                e.printStackTrace();
                // Respond with JSON so fetch receives 500 instead of HTTP 0
                writeJson(exchange, 500, "{\"ok\":false,\"error\":\"login error\"}");
                return;
            }
        });

        // GET /api/auth/check -> // Check login status (Session or JWT)
        server.createContext("/api/auth/check", exchange -> {
            // CORS Preflight
            if ("OPTIONS".equalsIgnoreCase(exchange.getRequestMethod())) {
                //  브라우저의 사전 요청은 인증 전에 CORS 헤더를 붙이고 본문 없이 종료해야 합니다.
                addCorsHeaders(exchange);exchange.sendResponseHeaders(204, -1);
                exchange.close();
                return;
            }

            if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }

            addCorsHeaders(exchange);

            // (A) Session validation
            String sessionId = getCookieValue(exchange, SESSION_COOKIE_NAME);
            User sessionUser = null;
            if (!isBlank(sessionId)) {
                // [② 세션 검증] 쿠키의 세션 ID는 사용자 자체가 아닙니다. 서버 저장소에서 해당 사용자를 조회하세요.
                sessionUser = SESSION_STORE.get(sessionId);
            }

            // (B) JWT validation
            String token = getCookieValue(exchange, JWT_COOKIE_NAME);
            boolean jwtOk = false;
            String jwtUsername = null;
            String jwtSubject = null;
            String jwtRole = null;

            if (!isBlank(token)) {
                try {
                    // [③ JWT 검증] 토큰 내용을 단순 디코딩하지 말고 서명·만료·발급자 검증 함수를 사용하세요.
                    DecodedJWT decoded = JwtUtil.verifyToken(token);
                    jwtOk = true;
                    jwtUsername = decoded.getClaim("username").asString();
                    jwtSubject = decoded.getSubject();
                    jwtRole = JwtUtil.roleOf(decoded);
                } catch (JWTVerificationException ex) {
                    jwtOk = false;
                } catch (Exception ex) {
                    jwtOk = false;
                }
            }

            // Policy: pass if either session OR JWT is valid
            // [④ 인증 정책] Session OR JWT: 두 방식 모두 실패한 경우에만 거부하도록 조건을 작성하세요.
            if (sessionUser == null && !jwtOk) {
                writeJson(exchange, 401, "{\"ok\":false,\"reason\":\"UNAUTHORIZED\"}");
                return;
            }

            if (sessionUser != null) {
                String body = "{\"ok\":true,\"via\":\"session\",\"username\":\""
                        + escapeJson(sessionUser.getUsername()) + "\",\"role\":\""
                        + escapeJson(sessionUser.getRole()) + "\"}";
                writeJson(exchange, 200, body);
            } else {
                String body = "{\"ok\":true,\"via\":\"jwt\",\"username\":\""
                        + escapeJson(jwtUsername) + "\",\"sub\":\""
                        + escapeJson(jwtSubject) + "\",\"role\":\""
                        + escapeJson(jwtRole) + "\"}";
                writeJson(exchange, 200, body);
            }
        });

        // (Optional) GET /home -> for session testing within 8080
        server.createContext("/home", exchange -> {
            if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }
            User user = resolveUser(exchange);
            if (user == null) {
                redirect(exchange, "/login");
                return;
            }
            String body = """
                    <html>
                    <head>
                      <meta charset='utf-8'/>
                      <link rel='stylesheet' href='/static/style.css'/>
                      <title>Home</title>
                    </head>
                    <body>
                      <div class='container'>
                        <h1>Welcome, %s</h1>
                        <p>This is the /home page of the 8080 server.</p>
                        <form method='POST' action='/api/logout'>
                          <button type='submit'>Logout</button>
                        </form>
                      </div>
                    </body>
                    </html>
                    """.formatted(escapeHtml(user.getUsername()));
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/html; charset=utf-8");
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(bytes);
            }
        });

        // POST /api/logout -> Log out
        server.createContext("/api/logout", exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                methodNotAllowed(exchange);
                return;
            }

            String sessionId = resolveSessionId(exchange);
            if (sessionId != null) {
                //  로그아웃 때 서버 측 세션을 무효화하세요.
                SESSION_STORE.remove(sessionId);}

            // Remove cookie (delete with identical attributes)
            exchange.getResponseHeaders().add("Set-Cookie", cookie(SESSION_COOKIE_NAME, "", true, 0));
            exchange.getResponseHeaders().add("Set-Cookie", cookie(JWT_COOKIE_NAME, "", true, 0));
            exchange.getResponseHeaders().add("Set-Cookie", cookie(APP_AUTH_COOKIE_NAME, "", false, 0));

            redirect(exchange, "/login");
        });

        server.start();
    }

    // ========= Session Helper =========

    private static String resolveSessionId(HttpExchange exchange) {
        return getCookieValue(exchange, SESSION_COOKIE_NAME);
    }

    private static User resolveUser(HttpExchange exchange) {
        String sessionId = resolveSessionId(exchange);
        if (sessionId == null) return null;
        return SESSION_STORE.get(sessionId);
    }
}
