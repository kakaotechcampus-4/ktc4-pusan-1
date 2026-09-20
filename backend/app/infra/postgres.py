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
from psycopg_pool import ConnectionPool

from app.domain.models import Interview, Session, SessionStatus

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class PostgresStore:
    """테이블 두 개(`interview`, `session`)를 읽고 쓴다.

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

    # ── 내부 ────────────────────────────────────────────────

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
