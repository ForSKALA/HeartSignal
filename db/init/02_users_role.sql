-- 이미 초기화된 DB(role 컬럼 없음)에 role 을 추가한다. 새 DB 에서는 01 에 이미 있으므로 아무 일도 하지 않는다.
-- 기존 DB 적용: docker exec -i <db 컨테이너> mariadb -uroot -p"$DB_PASSWORD" < db/init/02_users_role.sql
USE sql_db;

ALTER TABLE `users`
  ADD COLUMN IF NOT EXISTS `role` varchar(20) NOT NULL DEFAULT 'worker' AFTER `password`;

ALTER TABLE `users`
  ADD CONSTRAINT IF NOT EXISTS `ck_users_role` CHECK (`role` IN ('worker','foreman','admin','device'));

-- 역할 부여 예시 (가입 화면에서는 role 을 받지 않음, 관리자가 직접 실행)
-- UPDATE users SET role = 'admin'   WHERE username = 'manager1';
-- UPDATE users SET role = 'foreman' WHERE username = 'foreman1';
-- UPDATE users SET role = 'device'  WHERE username = 'sensor-gw1';
