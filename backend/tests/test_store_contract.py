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

from app.domain.models import (
    Context,
    ContextDoc,
    DocKind,
    Interview,
    Session,
    SessionStatus,
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
        conn.execute("TRUNCATE context CASCADE")
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


# ── 기업 컨텍스트 ────────────────────────────────────────


def _context(subject: Store, owner_id: str = "조직A") -> Context:
    return subject.ensure_context(Context(owner_id=owner_id))


def test_context_roundtrip(subject: Store):
    context = subject.ensure_context(
        Context(
            owner_id="조직A",
            company="카카오",
            team="플랫폼",
            role="백엔드",
            talent_profile="협업",
        )
    )

    found = subject.get_context(context.id)
    assert found is not None
    assert found.owner_id == "조직A"
    assert found.company == "카카오"
    assert found.team == "플랫폼"
    assert found.role == "백엔드"
    assert found.talent_profile == "협업"


def test_ensure_is_idempotent_per_owner(subject: Store):
    """주인당 하나. 두 번 불러 둘이 생기면 어느 쪽에 문서를 올렸는지가 갈린다."""
    first = _context(subject)
    second = _context(subject)
    assert first.id == second.id


def test_ensure_keeps_the_stored_one_not_the_new_one(subject: Store):
    """이미 있으면 새로 만든 쪽을 버린다 — 저장된 내용이 지워지면 안 된다."""
    stored = _context(subject)
    stored.company = "카카오"
    subject.save_context(stored)

    again = subject.ensure_context(Context(owner_id="조직A"))
    assert again.id == stored.id
    assert again.company == "카카오"


def test_different_owners_get_different_contexts(subject: Store):
    assert _context(subject, "조직A").id != _context(subject, "조직B").id


def test_saving_a_context_persists_the_change(subject: Store):
    context = _context(subject)
    context.company = "카카오"
    context.talent_profile = "끈기"
    subject.save_context(context)

    found = subject.get_context(context.id)
    assert found is not None
    assert found.company == "카카오"
    assert found.talent_profile == "끈기"


def test_unknown_context_is_none(subject: Store):
    assert subject.get_context("ctx_없는것") is None


# ── 문서 ────────────────────────────────────────────────


def _doc(context_id: str, name: str = "jd.pdf") -> ContextDoc:
    return ContextDoc(context_id=context_id, name=name, kind=DocKind.PDF, size_bytes=12)


def test_doc_roundtrip(subject: Store):
    context = _context(subject)
    doc = _doc(context.id)
    subject.add_doc(doc, b"%PDF-1.7\nx\n")

    found = subject.get_doc(context.id, doc.id)
    assert found is not None
    assert found.name == "jd.pdf"
    assert found.kind is DocKind.PDF
    assert found.size_bytes == 12


def test_docs_are_listed_in_upload_order(subject: Store):
    context = _context(subject)
    for name in ("first.pdf", "second.pdf", "third.pdf"):
        subject.add_doc(_doc(context.id, name), b"x")

    listed = [doc.name for doc in subject.list_docs(context.id)]
    assert listed == ["first.pdf", "second.pdf", "third.pdf"]


def test_docs_are_scoped_to_their_context(subject: Store):
    """id 만 알면 남의 문서를 읽거나 지울 수 있으면 안 된다."""
    mine = _context(subject, "조직A")
    yours = _context(subject, "조직B")
    doc = _doc(yours.id)
    subject.add_doc(doc, b"x")

    assert subject.get_doc(mine.id, doc.id) is None
    assert subject.delete_doc(mine.id, doc.id) is False
    assert subject.list_docs(mine.id) == []
    assert len(subject.list_docs(yours.id)) == 1


def test_deleting_a_doc_reports_whether_it_existed(subject: Store):
    context = _context(subject)
    doc = _doc(context.id)
    subject.add_doc(doc, b"x")

    assert subject.delete_doc(context.id, doc.id) is True
    assert subject.delete_doc(context.id, doc.id) is False
    assert subject.get_doc(context.id, doc.id) is None
