package workplace;

import com.auth0.jwt.JWT;
import com.auth0.jwt.JWTVerifier;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.exceptions.JWTVerificationException;
import com.auth0.jwt.interfaces.DecodedJWT;

// java.time
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;

// ========= JWT Util =========
// (SimpleAuthServer 내부 static class 에서 분리)

public class JwtUtil {
    private static final String SECRET = System.getenv("JWT_SECRET");
    private static final Algorithm ALG = Algorithm.HMAC256(SECRET);
    private static final String ISSUER = "simple-auth-server";

    public static String createToken(User user) {
        Instant now = Instant.now();
        return JWT.create()
                .withIssuer(ISSUER)
                .withIssuedAt(Date.from(now))
                //  JWT가 무기한 유효하지 않도록 발급 시점 기준 1시간 만료를 지정하세요.
                .withExpiresAt(Date.from(now.plus(1, ChronoUnit.HOURS))).withSubject(String.valueOf(user.getId()))
                .withClaim("username", user.getUsername())
                // Python 서비스들이 권한 판단에 쓰는 클레임 (AGENTS.md 7.1)
                .withClaim("role", user.getRole())
                .sign(ALG);
    }

    public static DecodedJWT verifyToken(String token) throws JWTVerificationException {
        JWTVerifier verifier = JWT.require(ALG)
                .withIssuer(ISSUER)
                .build();
        //  JWT 파싱만 하지 말고 검증기의 검증 결과를 반환하세요.
        return verifier.verify(token);
    }

    // role 클레임이 없거나 모르는 값이면 worker 로 간주한다 (AGENTS.md 7.1)
    public static String roleOf(DecodedJWT decoded) {
        String role = decoded.getClaim("role").asString();
        return User.ROLES.contains(role) ? role : User.DEFAULT_ROLE;
    }
}
