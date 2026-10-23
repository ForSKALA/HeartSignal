package workplace;

import com.sun.net.httpserver.HttpExchange;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

// ========= CORS / Resource / Response / Cookie Helper =========
// (SimpleAuthServer 의 private static 메서드에서 분리)

public final class HttpUtil {

    // ==== CORS ==== //
    // 허용 origin 목록 (쉼표 구분, RAG 와 같은 CORS_ORIGINS). 같은 origin 호출(Ingress·Vite 프록시)에는 필요 없다
    private static final Set<String> CORS_ORIGINS = Arrays.stream(
                    System.getenv().getOrDefault("CORS_ORIGINS", "http://localhost:5174").split(","))
            .map(String::trim)
            .filter(s -> !s.isEmpty())
            .collect(Collectors.toUnmodifiableSet());

    // ==== Cookie ==== //
    // https 배포(Ingress TLS)에서는 true: 쿠키가 http 로는 전송되지 않는다. 로컬 http 개발은 false(기본)
    private static final boolean COOKIE_SECURE =
            Boolean.parseBoolean(System.getenv().getOrDefault("COOKIE_SECURE", "false"));

    private HttpUtil() {}

    // ========= CORS =========

    static void addCorsHeaders(HttpExchange exchange) {
        exchange.getResponseHeaders().set("Vary", "Origin");
        String origin = exchange.getRequestHeaders().getFirst("Origin");
        if (origin == null || !CORS_ORIGINS.contains(origin)) return;
        exchange.getResponseHeaders().set("Access-Control-Allow-Origin", origin);
        exchange.getResponseHeaders().set("Access-Control-Allow-Credentials", "true");
        exchange.getResponseHeaders().set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
        exchange.getResponseHeaders().set("Access-Control-Allow-Headers", "Content-Type");
    }

    // ========= Resource/Reponse Helper =========

    static void serveResource(HttpExchange exchange, String resourcePath, String contentType) throws IOException {
        InputStream is = HttpUtil.class.getClassLoader().getResourceAsStream(resourcePath);
        if (is == null) {
            notFound(exchange);
            return;
        }
        byte[] bytes = is.readAllBytes();
        exchange.getResponseHeaders().add("Content-Type", contentType);
        exchange.sendResponseHeaders(200, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static void writeText(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "text/plain; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static void writeJson(HttpExchange exchange, int status, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    static void redirect(HttpExchange exchange, String location) throws IOException {
        exchange.getResponseHeaders().add("Location", location);
        exchange.sendResponseHeaders(302, -1);
        exchange.close();
    }

    static void methodNotAllowed(HttpExchange exchange) throws IOException {
        writeText(exchange, 405, "Method Not Allowed");
    }

    static void notFound(HttpExchange exchange) throws IOException {
        writeText(exchange, 404, "Not Found");
    }

    static Map<String, String> parseFormBody(HttpExchange exchange) throws IOException {
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        Map<String, String> params = new HashMap<>();
        for (String pair : body.split("&")) {
            if (pair.isEmpty()) continue;
            String[] kv = pair.split("=", 2);
            String key = urlDecode(kv[0]);
            String value = kv.length > 1 ? urlDecode(kv[1]) : "";
            params.put(key, value);
        }
        return params;
    }

    private static String urlDecode(String s) {
        return URLDecoder.decode(s, StandardCharsets.UTF_8);
    }

// Read common cookie
    static String getCookieValue(HttpExchange exchange, String name) {
        List<String> cookies = exchange.getRequestHeaders().get("Cookie");
        if (cookies == null) return null;
        for (String header : cookies) {
            String[] parts = header.split(";\\s*");
            for (String part : parts) {
                String[] kv = part.split("=", 2);
                if (kv.length == 2 && name.equals(kv[0])) {
                    return kv[1];
                }
            }
        }
        return null;
    }

  // Cookie creation helper (unified attributes)
    // maxAgeSeconds:
    //  -1 : Max-Age not set (behaves like a session cookie)
    //   0 : Delete immediately

    static String cookie(String name, String value, boolean httpOnly, int maxAgeSeconds) {
        StringBuilder sb = new StringBuilder();
        sb.append(name).append("=").append(value == null ? "" : value);
        sb.append("; Path=/");
        if (maxAgeSeconds >= 0) sb.append("; Max-Age=").append(maxAgeSeconds);
        if (httpOnly) sb.append("; HttpOnly");
        if (COOKIE_SECURE) sb.append("; Secure");
        sb.append("; SameSite=Lax");
        return sb.toString();
    }
}
