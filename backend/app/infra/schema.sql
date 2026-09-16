-- IRYA 저장소 스키마.
--
-- 마이그레이션 도구는 아직 붙이지 않는다. 테이블이 둘뿐이고 운영 데이터가
-- 없어서, 지금은 기동 시 이 파일을 한 번 실행하는 것으로 충분하다.
-- 컬럼을 바꿔야 할 때가 오면 그때 Alembic 을 넣는다.
--
-- 시각은 전부 TIMESTAMPTZ 다. 도메인 모델이 UTC aware datetime 을 쓰고,
-- 면접 참가자·서버·AI 가 서로 다른 시간대에 있을 수 있다.

CREATE TABLE IF NOT EXISTS interview (
    id             TEXT        PRIMARY KEY,
    interviewer_id TEXT        NOT NULL,
    -- 비워둘 수 있다. FE 가 기본 라벨로 대체한다.
    candidate_name TEXT,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    id           TEXT        PRIMARY KEY,
    interview_id TEXT        NOT NULL REFERENCES interview (id) ON DELETE CASCADE,
    -- SessionStatus. CHECK 를 걸지 않는다 — 값이 늘 때 DDL 과 코드를 같이
    -- 고쳐야 하는데, 명세 잠금 테스트가 이미 코드 쪽에서 값을 강제한다.
    status       TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    -- 「면접 시작」 버튼을 누른 비즈니스 시각. 안 누르고 끝나면 비어 있다.
    started_at   TIMESTAMPTZ,
    ended_at     TIMESTAMPTZ
);

-- 면접 하나에 세션이 여럿이다. 면접 기준 조회가 생길 때를 위해 걸어 둔다.
CREATE INDEX IF NOT EXISTS session_interview_id_idx ON session (interview_id);
