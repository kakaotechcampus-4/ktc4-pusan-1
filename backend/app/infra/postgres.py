"""PostgreSQL 저장소 구현.

`Store` Protocol 의 구현체다. 라우터는 이 모듈을 직접 import 하지 않는다 —
`app/api/deps.py` 가 설정을 보고 골라 준다.

동기 드라이버(psycopg)를 쓴다. FastAPI 는 `def` 라우터를 스레드풀에서 돌리므로
비동기 라우터로 바꾸지 않아도 이벤트 루프를 막지 않는다. 지금 규모에서
asyncpg 를 쓰면 Protocol 과 라우터 절반의 시그니처를 함께 바꿔야 하는데,
그만한 이득이 없다.
"""

from pathlib import Path
from typing import Any, LiteralString

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.domain.models import (
    Interview,
    Session,
    SessionStatus,
    SessionSummary,
    SummaryStatus,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class PostgresStore:
    """`interview` · `session` · `session_summary` 를 읽고 쓴다.

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

    def save_session(self, session: Session) -> None:
        """상태 전이 뒤 저장. `id` 와 `interview_id` 는 바뀌지 않으므로 뺀다."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                UPDATE session
                   SET status = %s,
                       started_at = %s,
                       ended_at = %s,
                       transcript_origin_at = %s
                 WHERE id = %s
                """,
                (
                    session.status.value,
                    session.started_at,
                    session.ended_at,
                    session.transcript_origin_at,
                    session.id,
                ),
            )

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
        if row is None:
            return None
        return SessionSummary(
            session_id=row["session_id"],
            status=SummaryStatus(row["status"]),
            overview=row["overview"],
            key_points=list(row["key_points"]),
            requested_at=row["requested_at"],
            completed_at=row["completed_at"],
        )

    def save_summary(self, summary: SessionSummary) -> None:
        """`requested_at` 은 바꾸지 않는다 — 한도의 기준점이다."""
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

    def _one(
        self, query: LiteralString, params: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        conn: Connection[dict[str, Any]]
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return cur.fetchone()
