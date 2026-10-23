package workplace;

// java.sql – Specify only what is needed
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

// ========= Repository (JDBC) =========
// (SimpleAuthServer 내부 static class 에서 분리)

public class JdbcUserRepository implements UserRepository {
    private final String url;
    private final String user;
    private final String password;

    public JdbcUserRepository(String url, String user, String password) {
        this.url = url;
        this.user = user;
        this.password = password;
    }

    private Connection getConnection() throws SQLException {
        return DriverManager.getConnection(url, user, password);
    }

    @Override
    public void save(User u) throws Exception {
        String sql = "INSERT INTO users(username, password, role) VALUES(?, ?, ?)";
        try (Connection conn = getConnection();
             PreparedStatement ps = conn.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS)) {
            //  SQL의 ? 자리와 사용자 필드를 연결하세요(문자열 결합 SQL 금지).
            ps.setString(1, u.getUsername());ps.setString(2, u.getPassword());ps.setString(3, u.getRole());ps.executeUpdate();
            try (ResultSet rs = ps.getGeneratedKeys()) {
                if (rs.next()) {
                    u.setId(rs.getLong(1));
                }
            }
        }
    }

    @Override
    public User findByUsername(String username) throws Exception {
        String sql = "SELECT id, username, password, role FROM users WHERE username = ?";
        try (Connection conn = getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, username);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    User u = new User();
                    u.setId(rs.getLong("id"));
                    u.setUsername(rs.getString("username"));
                    u.setPassword(rs.getString("password"));
                    u.setRole(rs.getString("role"));
                    return u;
                }
            }
        }
        return null;
    }
}
