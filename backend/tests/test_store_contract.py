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
from datetime import timedelta

import pytest

from app.domain.models import (
    Interview,
    Session,
    SessionStatus,
    SessionSummary,
    SummaryStatus,
)
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


# ── 요약 ────────────────────────────────────────────────


def test_summary_roundtrip(subject: Store):
    session = _seed(subject)

    subject.ensure_summary(SessionSummary(session_id=session.id))
    found = subject.get_summary(session.id)

    assert found is not None
    assert found.session_id == session.id
    assert found.status is SummaryStatus.PROCESSING
    assert found.overview == ""
    assert found.key_points == []
    assert found.completed_at is None


def test_ensure_summary_keeps_the_first_one(subject: Store):
    """두 번째 호출은 새로 쓰지 않고 있는 것을 돌려준다.

    `requested_at` 이 밀리면 한도가 계속 연장돼 FAILED 로 못 간다.
    """
    session = _seed(subject)
    first = subject.ensure_summary(SessionSummary(session_id=session.id))

    later = SessionSummary(session_id=session.id)
    later.requested_at += timedelta(minutes=30)
    again = subject.ensure_summary(later)

    assert again.requested_at == first.requested_at


def test_saving_a_summary_persists_the_content(subject: Store):
    session = _seed(subject)
    summary = subject.ensure_summary(SessionSummary(session_id=session.id))

    summary.complete("전체 요약입니다.", ["핵심 하나", "핵심 둘"])
    subject.save_summary(summary)

    found = subject.get_summary(session.id)
    assert found is not None
    assert found.status is SummaryStatus.READY
    assert found.overview == "전체 요약입니다."
    assert found.key_points == ["핵심 하나", "핵심 둘"]
    assert found.completed_at is not None


def test_saving_a_summary_does_not_move_the_deadline(subject: Store):
    session = _seed(subject)
    summary = subject.ensure_summary(SessionSummary(session_id=session.id))
    requested_at = summary.requested_at

    summary.give_up()
    subject.save_summary(summary)

    found = subject.get_summary(session.id)
    assert found is not None
    assert found.requested_at == requested_at


def test_summary_of_an_unknown_session_is_none(subject: Store):
    assert subject.get_summary("ses_없는것") is None


def test_summaries_do_not_leak_between_sessions(subject: Store):
    a = _seed(subject)
    b = _seed(subject)
    subject.ensure_summary(SessionSummary(session_id=a.id))

    assert subject.get_summary(b.id) is None
