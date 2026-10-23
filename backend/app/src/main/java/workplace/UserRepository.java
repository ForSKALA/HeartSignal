package workplace;

// ========= Repository =========
// (SimpleAuthServer 내부 interface 에서 분리)

public interface UserRepository {
    void save(User user) throws Exception;
    User findByUsername(String username) throws Exception;
}
