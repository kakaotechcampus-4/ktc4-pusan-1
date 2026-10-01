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
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain.models import (
    Context,
    ContextDoc,
    DocKind,
    Interview,
    Resume,
    Role,
    Session,
    SessionStatus,
    SessionSummary,
    Suggestion,
    SummaryStatus,
    TranscriptStage,
    User,
    Utterance,
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
        conn.execute("TRUNCATE app_user")
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


# ── 지원자 이력서 ────────────────────────────────────────


def _resume(interview_id: str, name: str = "이력서.pdf") -> Resume:
    return Resume(interview_id=interview_id, name=name, kind=DocKind.PDF, size_bytes=9)


def test_resume_roundtrip(subject: Store):
    session = _seed(subject)
    subject.save_resume(_resume(session.interview_id), b"%PDF-1.7\n")

    found = subject.get_resume(session.interview_id)
    assert found is not None
    assert found.name == "이력서.pdf"
    assert found.kind is DocKind.PDF
    assert found.size_bytes == 9


def test_resume_is_replaced_not_appended(subject: Store):
    """면접 한 건에 한 장. 다시 올리면 덮어쓴다."""
    session = _seed(subject)
    subject.save_resume(_resume(session.interview_id, "old.pdf"), b"old")
    subject.save_resume(_resume(session.interview_id, "new.pdf"), b"new")

    found = subject.get_resume(session.interview_id)
    assert found is not None
    assert found.name == "new.pdf"


def test_resume_of_an_interview_without_one_is_none(subject: Store):
    session = _seed(subject)
    assert subject.get_resume(session.interview_id) is None


def _waits_for_lock(dsn: str, table: str, *, timeout: float = 5.0) -> bool:
    """`table` 에 걸린 행 잠금을 기다리는 백엔드가 생길 때까지 본다.

    `pg_stat_activity` 를 별도 연결로 폴링한다. 잠금을 쥔 트랜잭션 안에서 보면
    자기 자신이 섞여 헷갈리므로 연결을 따로 연다.
    """
    import time

    import psycopg

    deadline = time.monotonic() + timeout
    with psycopg.connect(dsn, autocommit=True) as watcher:
        while time.monotonic() < deadline:
            waiting = watcher.execute(
                """
                SELECT count(*) FROM pg_stat_activity
                 WHERE wait_event_type = 'Lock'
                   AND state = 'active'
                   AND pid <> pg_backend_pid()
                   AND query ILIKE %s
                """,
                (f"%{table}%",),
            ).fetchone()
            if waiting is not None and waiting[0] > 0:
                return True
            time.sleep(0.02)
    return False


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


def test_expiring_a_summary_past_the_limit_marks_it_failed(subject: Store):
    session = _seed(subject)
    subject.ensure_summary(SessionSummary(session_id=session.id))

    # 한도를 음수로 주면 만들자마자 넘긴 것이다. `requested_at` 을 건드리지 않고
    # 판정을 시험할 수 있어 두 구현에서 똑같이 돈다.
    #
    # 0 이 아니라 −1초인 이유는 시계 해상도다. 0 이면 `requested_at` 과 비교
    # 시각이 같은 값일 수 있고(인메모리는 그사이가 마이크로초다), 그러면 `<` 가
    # 거짓이 되어 테스트가 간헐적으로 깨진다.
    returned = subject.expire_summary(session.id, timedelta(seconds=-1))

    assert returned is not None
    assert returned.status is SummaryStatus.FAILED
    stored = subject.get_summary(session.id)
    assert stored is not None
    assert stored.status is SummaryStatus.FAILED


def test_expiring_a_summary_within_the_limit_changes_nothing(subject: Store):
    session = _seed(subject)
    subject.ensure_summary(SessionSummary(session_id=session.id))

    returned = subject.expire_summary(session.id, timedelta(minutes=10))

    assert returned is not None
    assert returned.status is SummaryStatus.PROCESSING


def test_expiring_does_not_touch_a_summary_the_agent_already_finished(subject: Store):
    """한도가 지난 뒤 Agent 의 결과가 먼저 들어온 경우.

    조회가 읽고 판정하고 쓰면 방금 들어온 READY 와 본문이 FAILED · 빈 값으로
    덮인다 (#115). 판정과 갱신이 한 문장 안에 있으면 그 틈이 없다.
    """
    session = _seed(subject)
    summary = subject.ensure_summary(SessionSummary(session_id=session.id))
    summary.complete("살아남아야 하는 요약", ["근거 하나"])
    subject.save_summary(summary)

    returned = subject.expire_summary(session.id, timedelta(seconds=-1))

    assert returned is not None
    assert returned.status is SummaryStatus.READY
    assert returned.overview == "살아남아야 하는 요약"
    assert returned.key_points == ["근거 하나"]


def test_expiring_a_summary_that_does_not_exist(subject: Store):
    session = _seed(subject)

    assert subject.expire_summary(session.id, timedelta(minutes=1)) is None


def test_reading_gives_a_copy_not_the_stored_object(subject: Store):
    """`get_*` 이 참조를 돌려주면 라우터가 저장을 빼먹어도 인메모리에서는 통과한다.

    DB 에서만 나는 버그를 인메모리 테스트가 못 잡는 원인이라 계약으로 못박는다.
    """
    session = _seed(subject)
    subject.ensure_summary(SessionSummary(session_id=session.id))

    loose = subject.get_summary(session.id)
    assert loose is not None
    loose.complete("저장하지 않고 고친 값", [])

    again = subject.get_summary(session.id)
    assert again is not None
    assert again.status is SummaryStatus.PROCESSING


def test_saving_a_summary_ignores_a_changed_deadline(subject: Store):
    """호출자가 `requested_at` 을 바꿔 보내도 저장소는 원래 것을 지킨다.

    한도의 기준점이라 밀리면 FAILED 로 영영 못 간다. DB 구현의 UPDATE 가 이
    컬럼을 빼고 쓰므로, 인메모리도 같아야 계약이 하나가 된다.
    """
    session = _seed(subject)
    summary = subject.ensure_summary(SessionSummary(session_id=session.id))
    original = summary.requested_at

    summary.requested_at -= timedelta(hours=1)
    subject.save_summary(summary)

    found = subject.get_summary(session.id)
    assert found is not None
    assert found.requested_at == original


def test_saving_a_summary_does_not_move_the_deadline(subject: Store):
    session = _seed(subject)
    summary = subject.ensure_summary(SessionSummary(session_id=session.id))
    requested_at = summary.requested_at

    summary.give_up()
    subject.save_summary(summary)

    found = subject.get_summary(session.id)
    assert found is not None
    assert found.requested_at == requested_at


def test_expiring_loses_to_an_agent_result_that_lands_mid_flight():
    """#115 를 실제로 재현한다. **PostgreSQL 전용이다.**

    앞의 테스트들은 순서대로 부르기만 해서, 판정과 갱신 사이가 열려 있어도
    통과한다. 여기서는 그 틈을 강제로 만든다.

    커밋하지 않은 UPDATE 로 행 잠금을 쥔 채 `expire_summary` 를 부른다.

    - 한 문장이면: UPDATE 가 잠금을 기다렸다가 풀린 뒤 `WHERE` 를 **다시**
      평가한다. 그때는 READY 라 0행이 바뀌고 요약이 산다.
    - 읽고-고쳐-쓰기면: SELECT 는 잠금을 안 기다리고 옛 PROCESSING 을 읽는다.
      그 판단으로 만든 FAILED 가 잠금이 풀린 뒤 READY 를 덮는다.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL 이 없다")

    import threading

    import psycopg
    from psycopg.types.json import Jsonb

    from app.infra.postgres import PostgresStore

    subject = PostgresStore(TEST_DATABASE_URL)
    subject.open()
    subject.create_schema()
    try:
        with subject._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
            conn.execute("DELETE FROM interview")

        session = _seed(subject)
        summary = subject.ensure_summary(SessionSummary(session_id=session.id))
        # 한도를 이미 넘긴 상태로 만든다.
        with subject._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
            conn.execute(
                "UPDATE session_summary SET requested_at = requested_at - %s"
                " WHERE session_id = %s",
                (timedelta(hours=1), summary.session_id),
            )

        blocker = psycopg.connect(TEST_DATABASE_URL, autocommit=False)
        try:
            # Agent 의 결과. 커밋하지 않아 행 잠금만 쥔다.
            blocker.execute(
                "UPDATE session_summary"
                "   SET status = 'READY', overview = %s, key_points = %s"
                " WHERE session_id = %s",
                ("살아남아야 하는 요약", Jsonb(["근거"]), session.id),
            )

            done = threading.Event()

            def expire() -> None:
                try:
                    subject.expire_summary(session.id, timedelta(minutes=1))
                finally:
                    done.set()

            worker = threading.Thread(target=expire, daemon=True)
            worker.start()

            # **잠금을 실제로 기다리는 것을 보고 나서 커밋한다.**
            #
            # 그냥 잠깐 자고 커밋하면, 스레드가 그사이 UPDATE 에 못 들어갔을 때
            # 경합 없이 지나가고 테스트는 통과한다. 실패 쪽으로 흔들리진 않지만
            # 조용히 아무것도 검증하지 않게 된다. 그래서 기다림을 확인한다.
            assert _waits_for_lock(TEST_DATABASE_URL, "session_summary"), (
                "expire_summary 가 행 잠금을 기다리지 않았다 — "
                "이 테스트가 경합을 재현하지 못했다는 뜻이다"
            )

            blocker.commit()
            worker.join(timeout=10)
            assert not worker.is_alive()
            assert done.is_set()
        finally:
            blocker.close()

        found = subject.get_summary(session.id)
        assert found is not None
        assert found.status is SummaryStatus.READY
        assert found.overview == "살아남아야 하는 요약"
    finally:
        subject.close()


def test_summary_of_an_unknown_session_is_none(subject: Store):
    assert subject.get_summary("ses_없는것") is None


def test_summaries_do_not_leak_between_sessions(subject: Store):
    a = _seed(subject)
    b = _seed(subject)
    subject.ensure_summary(SessionSummary(session_id=a.id))

    assert subject.get_summary(b.id) is None


# ── 사용자 ──────────────────────────────────────────────


def test_upsert_user_keeps_first_id_and_updates_profile(subject: Store):
    first = subject.upsert_user(User(99, "처음", "a"))
    again = subject.upsert_user(User(kakao_id=99, nickname="바뀜"))

    assert again.id == first.id
    assert again.created_at == first.created_at
    found = subject.get_user(first.id)
    assert found is not None
    assert (found.nickname, found.profile_image_url) == ("바뀜", None)


def test_unknown_user_is_none(subject: Store):
    assert subject.get_user("usr_none") is None


# ── 전사 (#85) ──────────────────────────────────────────


def _utterance(session: Session, utterance_id: str = "utt_001", **overrides: Any):
    fields: dict[str, Any] = {
        "session_id": session.id,
        "utterance_id": utterance_id,
        "speaker": Role.CANDIDATE,
        "text": "캐시는 Redis 로 붙였습니다.",
        "started_at_ms": 15200,
        "ended_at_ms": 23800,
    }
    return Utterance(**(fields | overrides))


def test_utterance_roundtrip(subject: Store):
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session))

    assert subject.list_utterances(session.id) == [_utterance(session)]


def test_upserting_the_same_utterance_twice_replaces_it(subject: Store):
    """교정본이 같은 id 로 다시 온다 (#76). 행이 늘지 않고 내용만 바뀐다."""
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session, text="캐시는"))
    subject.upsert_utterance(
        _utterance(session, text="캐시는 Redis", ended_at_ms=24100)
    )

    [found] = subject.list_utterances(session.id)

    assert (found.text, found.ended_at_ms) == ("캐시는 Redis", 24100)


def test_utterances_come_back_in_speaking_order(subject: Store):
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session, "utt_b", started_at_ms=3000))
    subject.upsert_utterance(_utterance(session, "utt_a", started_at_ms=1000))
    subject.upsert_utterance(_utterance(session, "utt_c", started_at_ms=2000))

    ids = [u.utterance_id for u in subject.list_utterances(session.id)]

    assert ids == ["utt_a", "utt_c", "utt_b"]


def test_at_the_same_ms_the_interviewer_comes_first(subject: Store):
    """두 사람이 같은 ms 에 말을 시작하면 면접관이 먼저다.

    질문이 같은 순간의 답보다 앞에 와야 Q&A 로 읽힌다. id 로 자르면 트랙 ID
    순이 되는데 트랙 ID 는 무작위라 의미가 없다. `seq` 가 페이로드에 없어서
    (#76 ①) 저장소가 정한다.
    """
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session, "utt_a", started_at_ms=1000))
    subject.upsert_utterance(
        _utterance(session, "utt_z", speaker=Role.INTERVIEWER, started_at_ms=1000)
    )

    ids = [u.utterance_id for u in subject.list_utterances(session.id)]

    assert ids == ["utt_z", "utt_a"]


def test_same_speaker_at_the_same_ms_falls_back_to_id(subject: Store):
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session, "utt_b", started_at_ms=1000))
    subject.upsert_utterance(_utterance(session, "utt_a", started_at_ms=1000))

    ids = [u.utterance_id for u in subject.list_utterances(session.id)]

    assert ids == ["utt_a", "utt_b"]


def test_a_realigned_utterance_does_not_overwrite_the_live_one(subject: Store):
    """재전사가 같은 id 를 다시 써도 초벌이 남는다 — 기본키에 stage 가 있다.

    재전사 id 를 새로 낼지 재사용할지는 아직 답이 없다 (#76 A). 어느 쪽이든
    이 테스트가 통과하도록 키를 잡았다.
    """
    session = _seed(subject)
    subject.upsert_utterance(_utterance(session, text="초벌"))
    subject.upsert_utterance(
        _utterance(session, text="재전사", stage=TranscriptStage.REALIGNED)
    )

    [live] = subject.list_utterances(session.id)
    [realigned] = subject.list_utterances(session.id, stage=TranscriptStage.REALIGNED)

    assert (live.text, realigned.text) == ("초벌", "재전사")


def test_utterances_do_not_leak_between_sessions(subject: Store):
    one = _seed(subject)
    two = _seed(subject)
    subject.upsert_utterance(_utterance(one))

    assert subject.list_utterances(two.id) == []


# ── 꼬리질문 (#85) ──────────────────────────────────────


def _suggestion(session: Session, suggestion_id: str = "sug_001", **overrides: Any):
    fields: dict[str, Any] = {
        "session_id": session.id,
        "suggestion_id": suggestion_id,
        "content": "캐시 적중률은 얼마였나요?",
        "evidence_utterance_ids": ["utt_001", "utt_002"],
    }
    return Suggestion(**(fields | overrides))


def test_suggestion_roundtrip(subject: Store):
    session = _seed(subject)
    suggestion = _suggestion(session)
    subject.add_suggestion(suggestion)

    assert subject.list_suggestions(session.id) == [suggestion]


def test_adding_the_same_suggestion_twice_keeps_the_first(subject: Store):
    """Agent 가 전송을 재시도해도 한 건이다.

    처음 것을 남긴다 — `status` 와 `created_at` 은 BE 가 매기는 값이라 재시도가
    덮으면 도착 순서가 흔들린다.
    """
    session = _seed(subject)
    first = _suggestion(session, created_at=datetime(2026, 9, 29, 1, tzinfo=UTC))
    subject.add_suggestion(first)
    subject.add_suggestion(
        _suggestion(session, created_at=datetime(2026, 9, 29, 2, tzinfo=UTC))
    )

    assert subject.list_suggestions(session.id) == [first]


def test_suggestions_come_back_in_the_order_they_arrived(subject: Store):
    session = _seed(subject)
    for suggestion_id, hour in [("sug_b", 3), ("sug_a", 1), ("sug_c", 2)]:
        subject.add_suggestion(
            _suggestion(
                session,
                suggestion_id,
                created_at=datetime(2026, 9, 29, hour, tzinfo=UTC),
            )
        )

    ids = [s.suggestion_id for s in subject.list_suggestions(session.id)]

    assert ids == ["sug_a", "sug_c", "sug_b"]


def test_suggestion_evidence_is_a_copy(subject: Store):
    """돌려받은 근거 목록을 고쳐도 저장된 값은 그대로다."""
    session = _seed(subject)
    subject.add_suggestion(_suggestion(session))

    subject.list_suggestions(session.id)[0].evidence_utterance_ids.append("utt_999")

    [found] = subject.list_suggestions(session.id)
    assert found.evidence_utterance_ids == ["utt_001", "utt_002"]


def test_suggestion_evidence_keeps_the_order_it_was_sent(subject: Store):
    """근거는 위치로 저장된다. 어느 발화를 먼저 들었는지가 Agent 의 판단이다."""
    session = _seed(subject)
    order = ["utt_009", "utt_001", "utt_005"]
    subject.add_suggestion(_suggestion(session, evidence_utterance_ids=order))

    [found] = subject.list_suggestions(session.id)
    assert found.evidence_utterance_ids == order


def test_retried_suggestion_does_not_add_its_evidence_again(subject: Store):
    """재시도는 꼬리질문만이 아니라 근거도 다시 쌓지 않는다."""
    session = _seed(subject)
    subject.add_suggestion(_suggestion(session))
    subject.add_suggestion(_suggestion(session))

    [found] = subject.list_suggestions(session.id)
    assert found.evidence_utterance_ids == ["utt_001", "utt_002"]


def test_a_suggestion_can_arrive_before_its_evidence(subject: Store):
    """근거 발화가 아직 없어도 받는다. 전사와 통로가 달라 먼저 올 수 있다.

    잇는 것은 타임라인을 읽을 때다 — 그때는 면접이 끝나 전사가 다 와 있다.
    """
    session = _seed(subject)
    subject.add_suggestion(_suggestion(session))

    assert subject.list_utterances(session.id) == []
    [found] = subject.list_suggestions(session.id)
    assert found.evidence_utterance_ids == ["utt_001", "utt_002"]


def test_suggestions_do_not_leak_between_sessions(subject: Store):
    one = _seed(subject)
    two = _seed(subject)
    subject.add_suggestion(_suggestion(one))

    assert subject.list_suggestions(two.id) == []


def test_deleting_the_interview_takes_its_transcript_and_suggestions():
    """세션이 지워지면 전사·꼬리질문·근거가 같이 지워진다. **PostgreSQL 전용이다.**

    인메모리에는 삭제 경로가 없고, 이 보장은 외래키의 `ON DELETE CASCADE` 가
    한다. 면접 전사는 지원자의 말이라, 지울 수 있는 길이 있어야 한다.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL 이 없다")

    from app.infra.postgres import PostgresStore

    subject = PostgresStore(TEST_DATABASE_URL)
    subject.open()
    subject.create_schema()
    try:
        session = _seed(subject)
        subject.upsert_utterance(_utterance(session))
        subject.add_suggestion(_suggestion(session))

        with subject._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
            conn.execute("DELETE FROM interview WHERE id = %s", (session.interview_id,))

        assert subject.list_utterances(session.id) == []
        assert subject.list_suggestions(session.id) == []
        with subject._pool.connection() as conn:  # pyright: ignore[reportPrivateUsage]
            left = conn.execute(
                "SELECT count(*) FROM suggestion_evidence WHERE session_id = %s",
                (session.id,),
            ).fetchone()
        assert left == (0,)
    finally:
        subject.close()
