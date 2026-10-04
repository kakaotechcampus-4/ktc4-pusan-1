-- IRYA 저장소 스키마.
--
-- 마이그레이션 도구는 아직 붙이지 않는다. 테이블은 늘었지만 전부 새로 만드는
-- 것이라 `CREATE TABLE IF NOT EXISTS` 로 따라붙고, 기존 테이블에 컬럼을 더할
-- 때는 `ALTER ... ADD COLUMN IF NOT EXISTS` 로 버틴다 (session 의 원점이 그렇다).
-- 컬럼의 **타입이나 키를 바꿔야** 할 때가 오면 그때 Alembic 을 넣는다.
-- 처음 닿을 자리는 전사에 seq 를 필수 컬럼으로 넣을 때다 (#76 ①). 보내는 쪽이
-- 붙기 전까지 utterance · suggestion 계열은 비어 있어서 지우고 다시 만들어도 된다.
-- ⚠️ `CREATE INDEX IF NOT EXISTS` 는 이름이 같으면 정의를 바꿔도 기존 DB 에
-- 반영되지 않는다. 인덱스를 고칠 때는 이름도 바꾼다.
--
-- 시각은 TIMESTAMPTZ 다. 도메인 모델이 UTC aware datetime 을 쓰고, 면접
-- 참가자·서버·AI 가 서로 다른 시간대에 있을 수 있다. 예외는 전사의 발화
-- 시각 하나다 — 벽시계가 아니라 세션 원점 기준 ms 라 BIGINT 로 둔다 (아래).

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

-- 전사 타임라인 원점(t=0). 첫 참가자 입장 시각을 LiveKit Webhook 이 채운다.
-- started_at 과 다른 값이다 (자세한 이유는 domain/models.py 주석 참고).
--
-- CREATE TABLE 안이 아니라 ALTER 로 둔다. 이미 테이블이 만들어진 환경에서도
-- 기동 한 번으로 따라붙어야 하고, IF NOT EXISTS 라 여러 번 돌려도 안전하다.
ALTER TABLE session ADD COLUMN IF NOT EXISTS transcript_origin_at TIMESTAMPTZ;

-- ── 기업 컨텍스트 ──────────────────────────────────────────
--
-- 면접이 아니라 조직에 딸린다. 회사 정보와 JD 는 면접마다 바뀌지 않으므로 설정에
-- 한 번 넣고 계속 쓴다 (#79). 주인당 하나라 owner_id 가 유일하다.
--
-- 조직도 로그인도 아직 없어서 주인은 지금 하나뿐이다. 로그인이 들어오면 토큰에서
-- 정하게 되고, 컬럼 이름은 그때도 그대로 쓴다.

CREATE TABLE IF NOT EXISTS context (
    id              TEXT        PRIMARY KEY,
    owner_id        TEXT        NOT NULL UNIQUE,
    company         TEXT        NOT NULL DEFAULT '',
    team            TEXT        NOT NULL DEFAULT '',
    role            TEXT        NOT NULL DEFAULT '',
    -- AI 면접관이 참고할 추가 인재상·평가 포인트.
    talent_profile  TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL
);

-- 원본 바이트를 여기 둔다. S3 가 아직 없고, 컨테이너 볼륨을 새로 붙이면 배포 협의가
-- 필요한데 문서 몇 개를 위해 그럴 단계가 아니다. 저장소 교체가 필요해지면 content 를
-- 빼고 키만 남기면 된다 — 나머지 컬럼은 그대로 쓴다.
CREATE TABLE IF NOT EXISTS context_doc (
    id          TEXT        PRIMARY KEY,
    context_id  TEXT        NOT NULL REFERENCES context (id) ON DELETE CASCADE,
    -- 파일명은 NFC 로 정규화해 넣는다. macOS 앱이 만든 이름은 NFD 라, 그대로 두면
    -- 눈에는 같아 보이는데 검색·중복 제거가 어긋난다.
    name        TEXT        NOT NULL,
    kind        TEXT        NOT NULL,
    size_bytes  BIGINT      NOT NULL,
    status      TEXT        NOT NULL,
    content     BYTEA       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS context_doc_context_id_idx ON context_doc (context_id);

-- 지원자 이력서. 면접 한 건에 한 장이라 interview_id 가 기본키다 — 다시 올리면
-- 덮어쓴다. 원본을 여기 두는 이유는 context_doc 과 같다.
CREATE TABLE IF NOT EXISTS interview_resume (
    interview_id TEXT        PRIMARY KEY REFERENCES interview (id) ON DELETE CASCADE,
    id           TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    kind         TEXT        NOT NULL,
    size_bytes   BIGINT      NOT NULL,
    status       TEXT        NOT NULL,
    content      BYTEA       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL
);

-- 세션 하나의 요약. 면접이 끝나는 순간 PROCESSING 으로 만들어지고, Agent 가
-- `PUT /internal/v1/sessions/{id}/review` 로 결과를 써 넣으면 READY 가 된다.
-- 아무도 안 써 주면 한도(SUMMARY_TIMEOUT) 를 넘긴 뒤 조회 시점에 FAILED 로 간다.
--
-- 세션당 하나라 session_id 가 그대로 PK 다. 면접이 지워지면 요약도 같이 간다.
CREATE TABLE IF NOT EXISTS session_summary (
    session_id   TEXT        PRIMARY KEY REFERENCES session (id) ON DELETE CASCADE,
    -- SummaryStatus. session.status 와 같은 이유로 CHECK 를 걸지 않는다.
    status       TEXT        NOT NULL,
    -- READY 일 때만 찬다. FAILED 로 갈 때 다시 비운다.
    overview     TEXT        NOT NULL DEFAULT '',
    key_points   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- 기다리기 시작한 시각. 한도 판정의 기준점이라 면접 종료 시각과 따로 둔다.
    requested_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

-- ── 사용자 ──────────────────────────────────────────────
--
-- 카카오 로그인으로 들어온 면접관 (#118). `user` 는 예약어라 app_user 다.
-- kakao_id 가 유일하다 — 재로그인할 때 같은 사람을 이걸로 찾는다. 카카오 회원번호는
-- 64비트 정수라 BIGINT 다.
--
-- 카카오 access 토큰은 저장하지 않는다. 사용자 정보를 한 번 읽는 데만 쓴다.
CREATE TABLE IF NOT EXISTS app_user (
    id                 TEXT        PRIMARY KEY,
    kakao_id           BIGINT      NOT NULL UNIQUE,
    nickname           TEXT        NOT NULL,
    profile_image_url  TEXT,
    created_at         TIMESTAMPTZ NOT NULL
);

-- ── 전사·꼬리질문 (#85) ────────────────────────────────────
--
-- Agent 가 면접 중에 보내는 두 가지다. 전사는 WebSocket 으로, 꼬리질문은
-- POST 로 온다 (#76). 세션이 지워지면 같이 지워진다 — 면접 전사는 지원자의
-- 말이라 지울 길이 있어야 한다.
--
-- 발화 시각은 **세션 원점 기준 ms** 다. TIMESTAMPTZ 로 바꾸려면 원점을
-- 더해야 하는데 그 원점이 아직 믿을 만하지 않다 (#86). 받은 값을 그대로
-- 두면 원점을 고친 뒤에도 다시 계산할 수 있다.
--
-- 기본키에 stage 가 있다. 재전사(REALIGNED)가 초벌과 같은 utterance_id 를
-- 쓸지 새로 낼지 아직 답이 없는데 (#76 A), 키에 넣어 두면 어느 쪽이든 초벌을
-- 덮지 않는다. 새로 낸다고 해도 키가 한 칸 넓을 뿐이다.
CREATE TABLE IF NOT EXISTS utterance (
    session_id     TEXT    NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    -- TranscriptStage. session.status 와 같은 이유로 CHECK 를 걸지 않는다.
    stage          TEXT    NOT NULL,
    -- C 정렬 — 같은 ms 의 id 순을 코드포인트 순(인메모리와 같음)으로 고정한다. id 에
    -- 트랙 SID 가 들어가 대소문자 · '_' 가 섞이는데, DB 로캘을 따르면 이미지마다
    -- (alpine · glibc · RDS) 순서가 갈린다.
    utterance_id   TEXT    COLLATE "C" NOT NULL,
    speaker        TEXT    NOT NULL,
    text           TEXT    NOT NULL,
    started_at_ms  BIGINT  NOT NULL,
    ended_at_ms    BIGINT  NOT NULL,
    PRIMARY KEY (session_id, stage, utterance_id)
);

-- 말한 순서대로 읽는다. 같은 ms 면 면접관이 먼저, 그다음 id 순이다 — 질문이
-- 같은 순간의 답보다 앞에 와야 Q&A 로 읽힌다. seq 가 전송 페이로드에 아직 없어서
-- (#76 ①) 여기서 정한다. 같은 ms 는 드물어 그 자리는 인덱스를 안 탄다.
CREATE INDEX IF NOT EXISTS utterance_order_idx
    ON utterance (session_id, stage, started_at_ms, utterance_id);

-- 근거 발화는 suggestion_evidence 에 한 줄씩 둔다. 타임라인에서 「이 말로 나온
-- 꼬리질문」을 찾을 때 평범한 JOIN 으로 읽기 위해서다.
--
-- 근거 발화를 utterance 에 외래키로 걸지 않는다. 꼬리질문(POST)과 전사
-- (WebSocket)는 통로가 달라서 꼬리질문이 제 근거보다 먼저 도착할 수 있고, 전사
-- 배선 전에는 근거가 아예 없다. 그때 외래키가 있으면 멀쩡한 질문이 거절되고
-- Agent 는 짧게 재시도한 뒤 버린다. 그래서 받은 그대로 두고, 타임라인을 읽을 때
-- 잇는다 — 그때는 면접이 끝나 전사가 다 와 있다. 못 찾은 근거는 링크 없이 보인다.
-- 이 방식이 믿을 만하려면 발화 ID 가 세션 안에서 유일해야 한다 (AI 쪽 계약).
--
-- 비어 있지 않은지는 경계(SuggestionCreate)에서 본다 — 여기서도 막으면 인메모리
-- 구현과 결과가 갈린다.
CREATE TABLE IF NOT EXISTS suggestion (
    session_id     TEXT        NOT NULL REFERENCES session (id) ON DELETE CASCADE,
    suggestion_id  TEXT        NOT NULL,
    content        TEXT        NOT NULL,
    -- SuggestionStatus. 같은 이유로 CHECK 를 걸지 않는다.
    status         TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id, suggestion_id)
);

CREATE INDEX IF NOT EXISTS suggestion_order_idx
    ON suggestion (session_id, created_at, suggestion_id);

-- position 은 Agent 가 보낸 순서다. 중복 ID 는 경계에서 하나로 합쳐 온다.
CREATE TABLE IF NOT EXISTS suggestion_evidence (
    session_id     TEXT  NOT NULL,
    suggestion_id  TEXT  NOT NULL,
    position       INT   NOT NULL,
    -- utterance.utterance_id 와 같은 C 정렬. 다르면 JOIN 이 아래 인덱스를 못 탄다.
    utterance_id   TEXT  COLLATE "C" NOT NULL,
    PRIMARY KEY (session_id, suggestion_id, position),
    FOREIGN KEY (session_id, suggestion_id)
        REFERENCES suggestion (session_id, suggestion_id) ON DELETE CASCADE
);

-- 발화에서 꼬리질문을 거꾸로 찾는다 (타임라인의 「이 말로 나온 질문」).
CREATE INDEX IF NOT EXISTS suggestion_evidence_utterance_idx
    ON suggestion_evidence (session_id, utterance_id);
