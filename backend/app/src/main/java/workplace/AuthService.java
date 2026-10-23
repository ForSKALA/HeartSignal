package workplace;

import org.mindrot.jbcrypt.BCrypt;

import static workplace.SimpleAuthServer.DEBUG;
import static workplace.TextUtil.trimToNull;

import java.sql.SQLIntegrityConstraintViolationException;

// ========= Service =========
// (SimpleAuthServer 내부 static class 에서 분리)

public class AuthService {
    private final UserRepository userRepository;

    public AuthService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public void signUp(String username, String rawPassword) throws Exception {
        username = trimToNull(username);
        if (rawPassword != null) rawPassword = rawPassword.trim();

        User existing = userRepository.findByUsername(username);
        if (existing != null) {
            throw new SQLIntegrityConstraintViolationException("username already exists");
        }

        // [⑤-A 비밀번호 저장] 평문 대신 cost 12의 BCrypt salt 포함 해시를 저장하세요.
        String hashed = BCrypt.hashpw(rawPassword, BCrypt.gensalt(12));

        User u = new User();
        u.setUsername(username);
        u.setPassword(hashed);
        // role 은 기본값(worker) 그대로 둔다
        userRepository.save(u);
    }

    public User login(String username, String rawPassword) throws Exception {
        username = trimToNull(username);
        if (rawPassword != null) rawPassword = rawPassword.trim();

        User u = userRepository.findByUsername(username);
        if (u == null) {
            if (DEBUG) System.out.println("[AUTH] user not found: " + username);
            return null;
        }
        if (DEBUG) {
            System.out.println("[AUTH] user found: " + username);
            String hash = u.getPassword();
            System.out.println("[AUTH] dbHash prefix: " + (hash == null ? "null" : hash.substring(0, Math.min(7, hash.length()))));
        }

        // [⑤-B 비밀번호 검증] 입력 평문과 저장된 BCrypt 해시를 검증하세요. ⑤-A와 한 묶음입니다.
        boolean ok = checkPassword(rawPassword, u.getPassword());
        if (DEBUG) System.out.println("[AUTH] bcrypt matches=" + ok);

        if (!ok) return null;
        return u;
    }

    // 저장된 값이 BCrypt 형식이 아니면(평문 등) checkpw 가 예외를 던지므로 실패로 처리
    private static boolean checkPassword(String rawPassword, String hashed) {
        if (rawPassword == null || hashed == null) return false;
        try {
            return BCrypt.checkpw(rawPassword, hashed);
        } catch (IllegalArgumentException e) {
            return false;
        }
    }
}
