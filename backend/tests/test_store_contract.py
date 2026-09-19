"""저장소 계약 — 인메모리와 PostgreSQL 이 같게 동작해야 한다.

같은 테스트를 두 구현에 돌린다. 인메모리는 객체를 참조로 돌려주고 DB 는
매번 새로 만들어 주기 때문에, 규약을 글로만 적어 두면 갈라진다.

PostgreSQL 쪽은 `TEST_DATABASE_URL` 이 있을 때만 돈다. CI 와 로컬은 DB 없이
돌아야 해서 기본은 건너뛴다.

    docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test \\
      -e POSTGRES_USER=irya -e POSTGRES_DB=irya postgres:17-alpine
    TEST_DATABASE_URL=postgresql://irya:test@localhost:55432/irya uv run pytest
"""

import os
from collections.abc import Iterator

import pytest

from app.domain.models import Interview, Session, SessionStatus
from app.domain.store import InMemoryStore, Store

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture(params=["memory", "postgres"])
def subject(request: pytest.FixtureRequest) -> Iterator[Store]:
    if request.param == "memory":
        yield InMemoryStore()
        return

    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL 이 없다")

    from app.infra.postgres import PostgresStore

    postgres = PostgresStore(TEST_DATABASE_URL)
    postgres.open()
    postgres.create_schema()
    # 테스트끼리 섞이지 않게 비운다. interview 를 지우면 session 은 CASCADE 다.
    with postgres._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
        conn.execute("TRUNCATE interview CASCADE")
    try:
        yield postgres
    finally:
        postgres.close()


def _seed(subject: Store) -> Session:
    interview = Interview(interviewer_id="user_123", candidate_name="김지원")
    subject.add_interview(interview)
    session = Session(interview_id=interview.id)
    subject.add_session(session)
    return session


def test_interview_roundtrip(subject: Store):
    interview = Interview(interviewer_id="user_123", candidate_name="김지원")
    subject.add_interview(interview)

    found = subject.get_interview(interview.id)

    assert found is not None
    assert found.interviewer_id == "user_123"
    assert found.candidate_name == "김지원"
    assert found.created_at == interview.created_at


def test_candidate_name_may_be_empty(subject: Store):
    interview = Interview(interviewer_id="user_123")
    subject.add_interview(interview)

    found = subject.get_interview(interview.id)

    assert found is not None
    assert found.candidate_name is None


def test_unknown_ids_return_none(subject: Store):
    assert subject.get_interview("int_nope") is None
    assert subject.get_session("ses_nope") is None


def test_session_roundtrip(subject: Store):
    session = _seed(subject)

    found = subject.get_session(session.id)

    assert found is not None
    assert found.interview_id == session.interview_id
    assert found.status is SessionStatus.WAITING
    assert found.started_at is None
    assert found.ended_at is None
    assert found.transcript_origin_at is None


def test_state_transition_needs_save(subject: Store):
    """`save_session` 을 부르지 않으면 DB 에 남지 않는다.

    인메모리는 참조라 저장 없이도 반영되므로, 이 테스트는 DB 쪽에서만
    실제 의미를 갖는다. 두 구현 모두 저장 **뒤에는** 같아야 한다는 게 요점이다.
    """
    session = _seed(subject)

    assert session.start() is True
    subject.save_session(session)

    found = subject.get_session(session.id)
    assert found is not None
    assert found.status is SessionStatus.INTERVIEWING
    assert found.started_at == session.started_at


def test_end_is_persisted(subject: Store):
    session = _seed(subject)
    session.start()
    subject.save_session(session)

    assert session.end() is True
    subject.save_session(session)

    found = subject.get_session(session.id)
    assert found is not None
    assert found.status is SessionStatus.ENDED
    assert found.ended_at == session.ended_at


def test_transcript_origin_is_persisted(subject: Store):
    """Webhook 이 채우는 값이다. 재시작해도 원점이 유지돼야 한다."""
    session = _seed(subject)
    origin = session.created_at

    assert session.mark_origin(origin) is True
    subject.save_session(session)

    found = subject.get_session(session.id)
    assert found is not None
    assert found.transcript_origin_at == origin
    # 두 번째 참가자·재전송이 원점을 밀면 안 된다.
    assert found.mark_origin(session.created_at) is False


def test_conditional_save_rejects_stale_expectation(subject: Store):
    """기대한 상태가 아니면 쓰지 않고 False 를 준다.

    두 구현이 같아야 하는 지점이다. DB 는 `WHERE` 의 상태 조건으로, 인메모리는
    마지막으로 저장된 상태를 따로 들고 비교해서 같은 답을 낸다.
    """
    session = _seed(subject)

    assert session.start() is True
    assert subject.save_session(session, expected_status=SessionStatus.WAITING) is True

    # 저장소는 이제 INTERVIEWING 이다. 다시 WAITING 을 기대하면 거절해야 한다.
    assert subject.save_session(session, expected_status=SessionStatus.WAITING) is False


def test_save_does_not_create(subject: Store):
    """`save_session` 은 갱신이다. 없는 세션은 쓰지 않고 False 를 준다.

    추가는 `add_session` 의 일이다. DB 구현의 `UPDATE` 가 0행을 바꾸는 것과
    인메모리가 같은 답을 내야 한다.
    """
    ghost = Session(interview_id="iv_nope")

    assert subject.save_session(ghost) is False
    assert subject.save_session(ghost, expected_status=SessionStatus.WAITING) is False
    assert subject.get_session(ghost.id) is None


def test_conditional_save_without_expectation_always_writes(subject: Store):
    """`expected_status` 가 없으면 조건 없이 쓴다 (Webhook 의 원점 기록)."""
    session = _seed(subject)
    session.start()

    assert subject.save_session(session) is True
    assert subject.save_session(session) is True


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL 이 없다")
def test_two_readers_race_on_start():
    """멘토가 재현한 그 상황. 스레드 없이 조회를 두 번 해서 만든다.

    인메모리에는 이 테스트가 없다. `get_session` 이 같은 객체를 돌려줘서 두
    번째 `start()` 가 애초에 False 가 난다 — 저장소가 우연히 잠금 역할을 하므로
    이 경쟁이 구조적으로 생기지 않는다.
    """
    from app.infra.postgres import PostgresStore

    postgres = PostgresStore(TEST_DATABASE_URL)
    postgres.open()
    postgres.create_schema()
    with postgres._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
        conn.execute("TRUNCATE interview CASCADE")
    try:
        seeded = _seed(postgres)

        first = postgres.get_session(seeded.id)
        second = postgres.get_session(seeded.id)
        assert first is not None and second is not None
        assert first is not second  # DB 는 조회마다 새로 만든다

        assert first.start() is True
        assert second.start() is True  # 둘 다 WAITING 을 들고 있다

        assert (
            postgres.save_session(first, expected_status=SessionStatus.WAITING) is True
        )
        assert (
            postgres.save_session(second, expected_status=SessionStatus.WAITING)
            is False
        )

        stored = postgres.get_session(seeded.id)
        assert stored is not None
        assert stored.started_at == first.started_at  # 뒤 요청이 덮어쓰지 않았다
    finally:
        postgres.close()
