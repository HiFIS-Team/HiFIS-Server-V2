-- HiFIS 테스트 계정 4종 (권한별). 비밀번호는 bcrypt 해시(평문은 주석 참고).
-- branch_id 는 '본사'(HQ) 지점으로 연결. id 자동생성. 이미 있으면 건너뜀(email 유니크).
--
-- 실행:  docker exec -i hifis-db-1 psql -U hifis -d hifis < accounts.sql
-- 전제:  '본사' 지점이 먼저 있어야 함(app.seed 가 생성). 없으면 branch_id NULL 로 실패.
--
-- 참고:  app/seed_dev.py 로도 동일 계정을 만들 수 있음(그쪽은 비번 매 실행 재설정).

INSERT INTO employees (id, name, email, password_hash, branch_id, rank, role, status, work_status, avatar_color)
VALUES
  -- master@hifis.local / master1234    (MASTER · 대표)
  (gen_random_uuid()::text, '테스트 마스터', 'master@hifis.local',
   '$2b$12$Nq48iPTAvoFVMteXnj41muxkeflFrG4xC19aiPgbpASTXnJlO3dkG',
   (SELECT id FROM branches WHERE name = '본사' LIMIT 1), 'CEO', 'MASTER', 'ACTIVE', 'AUTO', '#6366f1'),
  -- admin2@hifis.local / admin1234     (ADMIN · 관리자/참관)
  (gen_random_uuid()::text, '테스트 관리자', 'admin2@hifis.local',
   '$2b$12$mBO8aCMH1CGdjmzukItOF.4CsJh56YOqncBdCRP0yWuQOAtdMJwfq',
   (SELECT id FROM branches WHERE name = '본사' LIMIT 1), 'STORE_MANAGER', 'ADMIN', 'ACTIVE', 'AUTO', '#6366f1'),
  -- manager@hifis.local / manager1234  (MANAGER · 점장)
  (gen_random_uuid()::text, '테스트 점장', 'manager@hifis.local',
   '$2b$12$lrow7dSfqLJQVjoHFbXhUeKP3gjxI0u6qJ.Ik91wJI5gvwjCoWNyO',
   (SELECT id FROM branches WHERE name = '본사' LIMIT 1), 'STORE_MANAGER', 'MANAGER', 'ACTIVE', 'AUTO', '#f59e0b'),
  -- trainer@hifis.local / trainer1234  (MEMBER · 트레이너)
  (gen_random_uuid()::text, '테스트 트레이너', 'trainer@hifis.local',
   '$2b$12$g1ERMeSzpKesubdBqV6gP.J8NaY0w95nb7hzxr6OuRTnJ9bAALEzK',
   (SELECT id FROM branches WHERE name = '본사' LIMIT 1), 'TRAINER', 'MEMBER', 'ACTIVE', 'AUTO', '#6366f1')
ON CONFLICT (email) DO NOTHING;
