package workplace;

import java.util.Set;

// ========= Domain =========
// (SimpleAuthServer 내부 static class 에서 분리)

public class User {
    // HeartSignal 역할: 경보 API 권한 판단에 쓰인다 (AGENTS.md 7.1)
    public static final String DEFAULT_ROLE = "worker";
    public static final Set<String> ROLES = Set.of("worker", "foreman", "admin");

    private Long id;
    private String username;
    private String password;
    private String role = DEFAULT_ROLE;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }

    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }

    public String getRole() { return role; }
    // 알 수 없는 값·null 은 worker 로 낮춘다 (권한 상승 방지)
    public void setRole(String role) { this.role = role != null && ROLES.contains(role) ? role : DEFAULT_ROLE; }
}
