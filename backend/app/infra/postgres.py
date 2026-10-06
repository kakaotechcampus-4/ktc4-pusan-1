"""PostgreSQL 저장소 구현.

`Store` Protocol 의 구현체다. 라우터는 이 모듈을 직접 import 하지 않는다 —
`app/api/deps.py` 가 설정을 보고 골라 준다.

동기 드라이버(psycopg)를 쓴다. FastAPI 는 `def` 라우터를 스레드풀에서 돌리므로
비동기 라우터로 바꾸지 않아도 이벤트 루프를 막지 않는다. 지금 규모에서
asyncpg 를 쓰면 Protocol 과 라우터 절반의 시그니처를 함께 바꿔야 하는데,
그만한 이득이 없다.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, LiteralString

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.domain.models import (
    Context,
    ContextDoc,
    DocCategory,
    DocKind,
    DocStatus,
    Interview,
    Recording,
    Resume,
    Role,
    Session,
    SessionStatus,
    SessionSummary,
    Suggestion,
    SuggestionStatus,
    SummaryStatus,
    TranscriptStage,
    User,
    Utterance,
    utcnow,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _finished(text: str | None) -> DocStatus:
    return DocStatus.READY if text else DocStatus.FAILED


class PostgresStore:
    """`schema.sql` 의 테이블을 읽고 쓴다 — 면접·세션·요약·기업 컨텍스트·이력서·
    사용자·전사·꼬리질문.

    커넥션 풀을 하나 들고 있다가 호출마다 빌려 쓴다. 매번 새로 연결하면
    면접 입장처럼 짧은 요청이 몰릴 때 연결 비용이 응답 시간을 지배한다.
    """

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        # open=False 로 만들고 명시적으로 연다. import 시점에 DB 가 떠 있지
        # 않아도 모듈을 읽을 수 있어야 테스트·마이그레이션이 편하다.
        self._pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, open=False
        )

    def open(self, *, timeout: float = 10.0) -> None:
        self._pool.open(wait=True, timeout=timeout)

    def close(self) -> None:
        self._pool.close()

    def create_schema(self) -> None:
        """스키마를 적용한다. 전부 `IF NOT EXISTS` 라 여러 번 불러도 된다."""
        # 파일에서 읽은 문자열이라 psycopg 가 리터럴로 보지 않는다. 값 바인딩이
        # 없는 순수 DDL 이고 파일도 우리가 배포하는 것이라 SQL() 로 감싼다.
        ddl = sql.SQL(SCHEMA_PATH.read_text(encoding="utf-8"))  # pyright: ignore[reportArgumentType]
        with self._pool.connection() as conn:
            conn.execute(ddl)

    # ── 면접 ────────────────────────────────────────────────

    def add_interview(self, interview: Interview) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO interview (id, interviewer_id, candidate_name, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    interview.id,
                    interview.interviewer_id,
                    interview.candidate_name,
                    interview.created_at,
                ),
            )

    def get_interview(self, interview_id: str) -> Interview | None:
        row = self._one(
            "SELECT id, interviewer_id, candidate_name, created_at"
            " FROM interview WHERE id = %s",
            (interview_id,),
        )
        if row is None:
            return None
        return Interview(
            id=row["id"],
            interviewer_id=row["interviewer_id"],
            candidate_name=row["candidate_name"],
            created_at=row["created_at"],
        )

    def list_interviews(
        self, interviewer_id: str
    ) -> list[tuple[Interview, Session | None, SummaryStatus | None]]:
        """마지막으로 끝난 세션은 `LATERAL` 로 면접마다 하나씩 붙인다. 한 문장이다."""
        rows = self._all(
            """
            SELECT i.id, i.interviewer_id, i.candidate_name, i.created_at,
                   s.id AS s_id, s.status AS s_status, s.created_at AS s_created_at,
                   s.started_at AS s_started_at, s.ended_at AS s_ended_at,
                   s.transcript_origin_at AS s_transcript_origin_at,
                   ss.status AS summary_status
            FROM interview i
            LEFT JOIN LATERAL (
                SELECT * FROM session
                WHERE session.interview_id = i.id AND session.ended_at IS NOT NULL
                ORDER BY session.ended_at DESC
                LIMIT 1
            ) s ON TRUE
            LEFT JOIN session_summary ss ON ss.session_id = s.id
            WHERE i.interviewer_id = %s
            ORDER BY i.created_at DESC
            """,
            (interviewer_id,),
        )
        return [
            (
                Interview(
                    id=row["id"],
                    interviewer_id=row["interviewer_id"],
                    candidate_name=row["candidate_name"],
                    created_at=row["created_at"],
                ),
                None
                if row["s_id"] is None
                else Session(
                    id=row["s_id"],
                    interview_id=row["id"],
                    status=SessionStatus(row["s_status"]),
                    created_at=row["s_created_at"],
                    started_at=row["s_started_at"],
                    ended_at=row["s_ended_at"],
                    transcript_origin_at=row["s_transcript_origin_at"],
                ),
                None
                if row["summary_status"] is None
                else SummaryStatus(row["summary_status"]),
            )
            for row in rows
        ]

    # ── 세션 ────────────────────────────────────────────────

    def add_session(self, session: Session) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO session (
                    id, interview_id, status, created_at,
                    started_at, ended_at, transcript_origin_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                self._session_values(session),
            )

    def get_session(self, session_id: str) -> Session | None:
        row = self._one(
            """
            SELECT id, interview_id, status, created_at,
                   started_at, ended_at, transcript_origin_at
            FROM session WHERE id = %s
            """,
            (session_id,),
        )
        if row is None:
            return None
        return Session(
            id=row["id"],
            interview_id=row["interview_id"],
            status=SessionStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            transcript_origin_at=row["transcript_origin_at"],
        )

    def save_session(
        self, session: Session, *, expected_status: SessionStatus | None = None
    ) -> bool:
        """상태 전이 뒤 저장. `id` 와 `interview_id` 는 바뀌지 않으므로 뺀다.

        `expected_status` 가 있으면 `WHERE` 에 상태 조건을 얹는다. 조건 평가와
        갱신이 한 문장 안에서 끝나므로 그 사이가 열리지 않는다. 읽고 나서 다른
        요청이 먼저 상태를 바꿨으면 0행이 바뀌고 False 가 나간다.

        조건절을 문자열로 붙이지만 값이 아니라 구조만 고른다 — 두 가지 중
        하나이고 바깥 입력이 닿지 않는다. 상태 값 자체는 파라미터로 나간다.
        """
        clause = "" if expected_status is None else " AND status = %s"
        params: tuple[Any, ...] = (
            session.status.value,
            session.started_at,
            session.ended_at,
            session.id,
        )
        if expected_status is not None:
            params += (expected_status.value,)

        with self._pool.connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE session
                   SET status = %s,
                       started_at = %s,
                       ended_at = %s
                 WHERE id = %s{clause}
                """,
                params,
            )
            return cursor.rowcount == 1

    def mark_origin(self, session_id: str, at: datetime) -> bool:
        """조건과 갱신이 한 문장이다. 동시에 들어와도 늦은 값이 이기지 않는다."""
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE session
                   SET transcript_origin_at = %s
                 WHERE id = %s
                   AND (transcript_origin_at IS NULL OR transcript_origin_at > %s)
                """,
                (at, session_id, at),
            )
            return cursor.rowcount == 1

    # ── 요약 ────────────────────────────────────────────────

    def ensure_summary(self, summary: SessionSummary) -> SessionSummary:
        """없으면 넣고, 있든 없든 **저장소에 있는 것**을 돌려준다.

        `ON CONFLICT DO NOTHING` 뒤에 다시 읽는다. `RETURNING` 은 충돌했을 때
        아무 행도 안 주므로 그것만으로는 기존 값을 못 가져온다. 종료 요청이
        겹쳐 들어와도 먼저 들어간 `requested_at` 이 남아야 한다.
        """
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO session_summary (
                    session_id, status, overview, key_points,
                    requested_at, completed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                self._summary_values(summary),
            )
        stored = self.get_summary(summary.session_id)
        assert stored is not None  # 방금 넣었거나 이미 있었다
        return stored

    def get_summary(self, session_id: str) -> SessionSummary | None:
        row = self._one(
            """
            SELECT session_id, status, overview, key_points,
                   requested_at, completed_at
            FROM session_summary WHERE session_id = %s
            """,
            (session_id,),
        )
        return None if row is None else self._to_summary(row)

    def save_summary(self, summary: SessionSummary) -> None:
        """Agent 가 만든 결과를 받아 둔다. `requested_at` 은 바꾸지 않는다 —
        한도의 기준점이다."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE session_summary
                   SET status = %s,
                       overview = %s,
                       key_points = %s,
                       completed_at = %s
                 WHERE session_id = %s
                """,
                (
                    summary.status.value,
                    summary.overview,
                    Jsonb(summary.key_points),
                    summary.completed_at,
                    summary.session_id,
                ),
            )

    def fail_summary(self, session_id: str) -> bool:
        """READY 가 아닐 때만 FAILED 로. 조건이 `WHERE` 안에 있어 판정과 갱신
        사이가 열리지 않는다 (#132). 시각은 `expire_summary` 처럼 앱이 찍는다."""
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE session_summary
                   SET status = %s,
                       overview = '',
                       key_points = '[]'::jsonb,
                       completed_at = %s
                 WHERE session_id = %s
                   AND status <> %s
                """,
                (
                    SummaryStatus.FAILED.value,
                    utcnow(),
                    session_id,
                    SummaryStatus.READY.value,
                ),
            )
            return cursor.rowcount == 1

    def expire_summary(
        self, session_id: str, limit: timedelta
    ) -> SessionSummary | None:
        """판정·전이·저장을 한 문장으로 끝낸다.

        `WHERE` 가 「아직 PROCESSING 이고 한도를 넘겼는가」를 보고 같은 문장이
        FAILED 로 넘긴다. 그 사이가 열리지 않으므로, 한도가 막 지나는 순간에
        Agent 의 결과가 들어와도 덮어 지우지 않는다 (#115).

        **시각은 앱이 만들어 넘긴다.** 한도 기준점(`requested_at`)을 앱이 찍으므로
        비교도 같은 시계로 해야 한다. DB 의 `now()` 를 쓰면 두 시계 차이만큼
        한도가 늘거나 줄고, 파이썬 시계만 쓰는 인메모리 구현과 판정이 갈린다.
        원자성은 조건이 `WHERE` 안에 있는 것으로 지켜지지, 시계가 DB 것이어야
        지켜지는 게 아니다.

        0행이 바뀌면 한도를 안 넘겼거나 누가 먼저 끝낸 것이다. 그때는 지금 값을
        읽어 돌려준다.
        """
        moment = utcnow()
        row = self._one(
            """
            UPDATE session_summary
               SET status = %s,
                   overview = '',
                   key_points = '[]'::jsonb,
                   completed_at = %s
             WHERE session_id = %s
               AND status = %s
               AND requested_at < %s
         RETURNING session_id, status, overview, key_points,
                   requested_at, completed_at
            """,
            (
                SummaryStatus.FAILED.value,
                moment,
                session_id,
                SummaryStatus.PROCESSING.value,
                moment - limit,
            ),
        )
        if row is not None:
            return self._to_summary(row)
        # 한도를 안 넘겼거나 누가 먼저 끝냈다. 지금 값을 그대로 준다.
        return self.get_summary(session_id)

    # ── 내부 ────────────────────────────────────────────────

    @staticmethod
    def _summary_values(summary: SessionSummary) -> tuple[Any, ...]:
        return (
            summary.session_id,
            summary.status.value,
            summary.overview,
            Jsonb(summary.key_points),
            summary.requested_at,
            summary.completed_at,
        )

    @staticmethod
    def _session_values(session: Session) -> tuple[Any, ...]:
        return (
            session.id,
            session.interview_id,
            session.status.value,
            session.created_at,
            session.started_at,
            session.ended_at,
            session.transcript_origin_at,
        )

    # ── 녹화 ────────────────────────────────────────────

    def ensure_recording(self, session_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO recording (session_id, status) VALUES (%s, %s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (session_id, SummaryStatus.PROCESSING.value),
            )

    def get_recording(self, session_id: str) -> Recording | None:
        row = self._one(
            """
            SELECT session_id, status, s3_key, egress_started_at,
                   duration_ms, completed_at
            FROM recording WHERE session_id = %s
            """,
            (session_id,),
        )
        if row is None:
            return None
        return Recording(
            session_id=row["session_id"],
            status=SummaryStatus(row["status"]),
            s3_key=row["s3_key"],
            egress_started_at=row["egress_started_at"],
            duration_ms=row["duration_ms"],
            completed_at=row["completed_at"],
        )

    def save_recording(self, recording: Recording) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE recording
                   SET status = %s, s3_key = %s, egress_started_at = %s,
                       duration_ms = %s, completed_at = %s
                 WHERE session_id = %s
                """,
                (
                    recording.status.value,
                    recording.s3_key,
                    recording.egress_started_at,
                    recording.duration_ms,
                    recording.completed_at,
                    recording.session_id,
                ),
            )

    def pending_recordings(self) -> list[str]:
        rows = self._all(
            """
            SELECT r.session_id FROM recording r
            JOIN session s ON s.id = r.session_id
            WHERE r.status = %s AND s.status = %s
            """,
            (SummaryStatus.PROCESSING.value, SessionStatus.ENDED.value),
        )
        return [row["session_id"] for row in rows]

    def _all(
        self, query: LiteralString, params: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        conn: Connection[dict[str, Any]]
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return cur.fetchall()

    @staticmethod
    def _to_summary(row: dict[str, Any]) -> SessionSummary:
        return SessionSummary(
            session_id=row["session_id"],
            status=SummaryStatus(row["status"]),
            overview=row["overview"],
            key_points=list(row["key_points"]),
            requested_at=row["requested_at"],
            completed_at=row["completed_at"],
        )

    def _one(
        self, query: LiteralString, params: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        conn: Connection[dict[str, Any]]
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return cur.fetchone()

    # ── 기업 컨텍스트 ───────────────────────────────────

    def ensure_context(self, context: Context) -> Context:
        """한 문장으로 넣거나 넘긴다.

        확인한 뒤 넣으면 그 사이에 다른 요청이 넣을 수 있고, `owner_id` 가 UNIQUE 라
        그때 두 번째 요청이 500 으로 터진다. `DO NOTHING` 으로 넘기고 다시 읽는다 —
        어느 쪽이 이겼든 결과는 같다.
        """
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO context
                    (id, owner_id, company, team, role, talent_profile, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (owner_id) DO NOTHING
                """,
                self._context_values(context),
            )
        found = self._context_by_owner(context.owner_id)
        # UNIQUE 가 있으니 방금 넣었거나 남이 넣었거나 둘 중 하나다.
        assert found is not None
        return found

    def get_context(self, context_id: str) -> Context | None:
        row = self._one(
            "SELECT id, owner_id, company, team, role, talent_profile,"
            " created_at FROM context WHERE id = %s",
            (context_id,),
        )
        return None if row is None else self._to_context(row)

    def _context_by_owner(self, owner_id: str) -> Context | None:
        row = self._one(
            "SELECT id, owner_id, company, team, role, talent_profile,"
            " created_at FROM context WHERE owner_id = %s",
            (owner_id,),
        )
        return None if row is None else self._to_context(row)

    def save_context(self, context: Context) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE context
                   SET company = %s, team = %s, role = %s, talent_profile = %s
                 WHERE id = %s
                """,
                (
                    context.company,
                    context.team,
                    context.role,
                    context.talent_profile,
                    context.id,
                ),
            )

    def add_doc(self, doc: ContextDoc, content: bytes) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO context_doc
                    (id, context_id, name, kind, category, size_bytes, status,
                     content, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    doc.id,
                    doc.context_id,
                    doc.name,
                    doc.kind.value,
                    doc.category.value,
                    doc.size_bytes,
                    doc.status.value,
                    content,
                    doc.created_at,
                ),
            )

    def list_docs(self, context_id: str) -> list[ContextDoc]:
        # content 는 고르지 않는다. 목록 한 번에 파일 전체가 딸려 오면 안 된다.
        rows = self._all(
            "SELECT id, context_id, name, kind, category, size_bytes, status,"
            " created_at FROM context_doc WHERE context_id = %s ORDER BY created_at",
            (context_id,),
        )
        return [self._to_doc(row) for row in rows]

    def get_doc(self, context_id: str, doc_id: str) -> ContextDoc | None:
        row = self._one(
            "SELECT id, context_id, name, kind, category, size_bytes, status,"
            " created_at FROM context_doc WHERE context_id = %s AND id = %s",
            (context_id, doc_id),
        )
        return None if row is None else self._to_doc(row)

    def delete_doc(self, context_id: str, doc_id: str) -> bool:
        with self._pool.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM context_doc WHERE context_id = %s AND id = %s",
                (context_id, doc_id),
            )
            return cursor.rowcount == 1

    def finish_doc(self, context_id: str, doc_id: str, text: str | None) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE context_doc SET status = %s, text = %s"
                " WHERE context_id = %s AND id = %s",
                (_finished(text).value, text, context_id, doc_id),
            )

    def get_doc_text(self, context_id: str, doc_id: str) -> str | None:
        row = self._one(
            "SELECT text FROM context_doc WHERE context_id = %s AND id = %s",
            (context_id, doc_id),
        )
        return None if row is None else row["text"]

    @staticmethod
    def _context_values(context: Context) -> tuple[Any, ...]:
        return (
            context.id,
            context.owner_id,
            context.company,
            context.team,
            context.role,
            context.talent_profile,
            context.created_at,
        )

    @staticmethod
    def _to_context(row: dict[str, Any]) -> Context:
        return Context(
            id=row["id"],
            owner_id=row["owner_id"],
            company=row["company"],
            team=row["team"],
            role=row["role"],
            talent_profile=row["talent_profile"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_doc(row: dict[str, Any]) -> ContextDoc:
        return ContextDoc(
            id=row["id"],
            context_id=row["context_id"],
            name=row["name"],
            kind=DocKind(row["kind"]),
            category=DocCategory(row["category"]),
            size_bytes=row["size_bytes"],
            status=DocStatus(row["status"]),
            created_at=row["created_at"],
        )

    # ── 지원자 이력서 ───────────────────────────────────

    def save_resume(self, resume: Resume, content: bytes) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO interview_resume
                    (interview_id, id, name, kind, size_bytes, status, content,
                     created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (interview_id) DO UPDATE SET
                    id = EXCLUDED.id,
                    name = EXCLUDED.name,
                    kind = EXCLUDED.kind,
                    size_bytes = EXCLUDED.size_bytes,
                    status = EXCLUDED.status,
                    content = EXCLUDED.content,
                    text = NULL,
                    created_at = EXCLUDED.created_at
                """,
                (
                    resume.interview_id,
                    resume.id,
                    resume.name,
                    resume.kind.value,
                    resume.size_bytes,
                    resume.status.value,
                    content,
                    resume.created_at,
                ),
            )

    def get_resume(self, interview_id: str) -> Resume | None:
        # content 는 고르지 않는다. 메타데이터만 필요한 자리가 대부분이다.
        row = self._one(
            "SELECT interview_id, id, name, kind, size_bytes, status, created_at"
            " FROM interview_resume WHERE interview_id = %s",
            (interview_id,),
        )
        if row is None:
            return None
        return Resume(
            interview_id=row["interview_id"],
            id=row["id"],
            name=row["name"],
            kind=DocKind(row["kind"]),
            size_bytes=row["size_bytes"],
            status=DocStatus(row["status"]),
            created_at=row["created_at"],
        )

    def finish_resume(
        self, interview_id: str, resume_id: str, text: str | None
    ) -> None:
        # id 까지 맞춰 본다. 추출 도중 새 이력서로 덮였으면 옛 결과를 버린다.
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE interview_resume SET status = %s, text = %s"
                " WHERE interview_id = %s AND id = %s",
                (_finished(text).value, text, interview_id, resume_id),
            )

    def get_resume_text(self, interview_id: str) -> str | None:
        row = self._one(
            "SELECT text FROM interview_resume WHERE interview_id = %s",
            (interview_id,),
        )
        return None if row is None else row["text"]

    # ── 사용자 ──────────────────────────────────────────────

    def upsert_user(self, user: User) -> User:
        """`ON CONFLICT DO UPDATE ... RETURNING` 한 문장이다.

        충돌하면 기존 행이 갱신되어 나오므로 id·created_at 은 처음 것이 돌아온다.
        """
        row = self._one(
            """
            INSERT INTO app_user
                (id, kakao_id, nickname, profile_image_url, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (kakao_id) DO UPDATE SET
                nickname = EXCLUDED.nickname,
                profile_image_url = EXCLUDED.profile_image_url
            RETURNING id, kakao_id, nickname, profile_image_url, created_at,
                      token_version
            """,
            (
                user.id,
                user.kakao_id,
                user.nickname,
                user.profile_image_url,
                user.created_at,
            ),
        )
        assert row is not None
        return User(**row)

    def get_user(self, user_id: str) -> User | None:
        row = self._one(
            "SELECT id, kakao_id, nickname, profile_image_url, created_at,"
            " token_version FROM app_user WHERE id = %s",
            (user_id,),
        )
        return None if row is None else User(**row)

    # ── 전사·꼬리질문 (#85) ─────────────────────────────────

    def upsert_utterance(self, utterance: Utterance) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO utterance (
                    session_id, stage, utterance_id,
                    speaker, text, started_at_ms, ended_at_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, stage, utterance_id) DO UPDATE SET
                    speaker = EXCLUDED.speaker,
                    text = EXCLUDED.text,
                    started_at_ms = EXCLUDED.started_at_ms,
                    ended_at_ms = EXCLUDED.ended_at_ms
                """,
                (
                    utterance.session_id,
                    utterance.stage.value,
                    utterance.utterance_id,
                    utterance.speaker.value,
                    utterance.text,
                    utterance.started_at_ms,
                    utterance.ended_at_ms,
                ),
            )

    def list_utterances(
        self, session_id: str, stage: TranscriptStage = TranscriptStage.LIVE
    ) -> list[Utterance]:
        rows = self._all(
            """
            SELECT session_id, stage, utterance_id,
                   speaker, text, started_at_ms, ended_at_ms
            FROM utterance
            WHERE session_id = %s AND stage = %s
            ORDER BY started_at_ms,
                     CASE speaker WHEN 'INTERVIEWER' THEN 0 ELSE 1 END,
                     utterance_id
            """,
            (session_id, stage.value),
        )
        return [
            Utterance(
                session_id=row["session_id"],
                utterance_id=row["utterance_id"],
                speaker=Role(row["speaker"]),
                text=row["text"],
                started_at_ms=row["started_at_ms"],
                ended_at_ms=row["ended_at_ms"],
                stage=TranscriptStage(row["stage"]),
            )
            for row in rows
        ]

    def add_suggestion(self, suggestion: Suggestion) -> None:
        # 꼬리질문과 근거를 한 트랜잭션으로 넣는다 — 풀에서 빌린 연결은 블록을
        # 나갈 때 커밋한다. 재시도라 꼬리질문이 이미 있으면 근거도 다시 넣지 않는다.
        with self._pool.connection() as conn:
            inserted = conn.execute(
                """
                INSERT INTO suggestion (
                    session_id, suggestion_id, content, status, created_at
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id, suggestion_id) DO NOTHING
                RETURNING 1
                """,
                (
                    suggestion.session_id,
                    suggestion.suggestion_id,
                    suggestion.content,
                    suggestion.status.value,
                    suggestion.created_at,
                ),
            ).fetchone()
            if inserted is None:
                return
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO suggestion_evidence (
                        session_id, suggestion_id, position, utterance_id
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (suggestion.session_id, suggestion.suggestion_id, i, uid)
                        for i, uid in enumerate(suggestion.evidence_utterance_ids)
                    ],
                )

    def list_suggestions(self, session_id: str) -> list[Suggestion]:
        rows = self._all(
            """
            SELECT s.session_id, s.suggestion_id, s.content,
                   s.status, s.created_at,
                   COALESCE(
                       (SELECT array_agg(e.utterance_id ORDER BY e.position)
                        FROM suggestion_evidence e
                        WHERE e.session_id = s.session_id
                          AND e.suggestion_id = s.suggestion_id),
                       '{}'
                   ) AS evidence_utterance_ids
            FROM suggestion s
            WHERE s.session_id = %s
            ORDER BY s.created_at, s.suggestion_id
            """,
            (session_id,),
        )
        return [
            Suggestion(
                session_id=row["session_id"],
                suggestion_id=row["suggestion_id"],
                content=row["content"],
                evidence_utterance_ids=list(row["evidence_utterance_ids"]),
                status=SuggestionStatus(row["status"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
