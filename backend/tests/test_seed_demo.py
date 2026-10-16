"""데모 시드 (#137 6장 · #163) — FE 목의 5명을 데모 계정 소유로 넣는다.

넣은 뒤 목록 · 상세 API 가 #137 1장 모양으로 응답하는지 본다. 김도현은 #137 1-2
예시 그대로라, 목록 집계가 1-1 예시와 같아야 한다.
"""

import pytest
from fastapi.testclient import TestClient

from app import seed_demo
from app.core.config import settings
from app.domain.models import Context, SessionSummary, SummaryStatus, User
from app.domain.store import InMemoryStore
from app.seed_demo import seed


def test_the_fe_mock_candidates_come_out_of_the_api(
    client: TestClient, store: InMemoryStore, owner: User
):
    assert seed(store, owner.id) == 5

    items = client.get("/api/v1/interviews").json()["items"]

    assert [i["candidateName"] for i in items] == [
        "김도현",
        "이재훈",
        "박수민",
        "최유진",
        "정민서",
    ]
    kim, _, park, *_ = items
    assert kim["counts"] == {
        "coverageConfirmed": 1,
        "coverageTotal": 4,
        "findings": 5,
        "needsReview": 5,
        "adopted": 0,
    }
    assert (kim["reviewStatus"], park["reviewStatus"]) == ("PENDING", "CONFIRMED")
    assert (kim["role"], kim["durationSec"]) == ("백엔드 개발자", 634)

    detail = client.get(f"/api/v1/interviews/{kim['interviewId']}/review").json()
    assert detail["summaryStatus"] == "READY"
    assert [m["bookmarked"] for m in detail["moments"]] == [False, True, True, False]
    assert (
        detail["memo"] == "팀 성과와 본인 기여 범위를 다음 면접에서 구분해 확인할 것."
    )


def test_seeding_again_adds_nothing(store: InMemoryStore, owner: User):
    seed(store, owner.id)

    assert seed(store, owner.id) == 0
    assert len(store.list_interviews(owner.id)) == 5


def test_each_account_gets_its_own_copy(store: InMemoryStore, owner: User):
    other = store.upsert_user(User(kakao_id=99, nickname="다른 데모"))

    assert (seed(store, owner.id), seed(store, other.id)) == (5, 5)


def test_a_role_already_set_is_kept(store: InMemoryStore, owner: User):
    """데모 계정의 실제 직무 설정을 덮지 않는다. 비어 있을 때만 채운다."""
    context = store.ensure_context(Context(owner_id=owner.id))
    context.role = "플랫폼 엔지니어"
    store.save_context(context)

    seed(store, owner.id)

    assert store.ensure_context(Context(owner_id=owner.id)).role == "플랫폼 엔지니어"


def test_an_unknown_owner_is_refused(store: InMemoryStore):
    """오타가 나면 아무에게도 안 보이는 면접 5건이 생긴다. 넣기 전에 막는다."""
    with pytest.raises(ValueError):
        seed(store, "usr_nope")
    assert store.list_interviews("usr_nope") == []


def test_without_a_database_it_does_not_pretend(monkeypatch: pytest.MonkeyPatch):
    """인메모리에 넣고 성공한 척 끝나면 서버에는 아무것도 없다."""
    monkeypatch.setattr(settings, "database_url", "")

    assert seed_demo.main(["--owner", "usr_x"]) == 1


def test_a_seed_that_died_halfway_is_finished_by_the_next_run(
    store: InMemoryStore, owner: User, monkeypatch: pytest.MonkeyPatch
):
    """쓰기가 여러 번이라 중간에 죽으면 반쪽 면접이 남는다. 다시 돌리면 마저 채운다
    — 「면접이 있으면 건너뜀」이면 그 면접은 영원히 반쪽이다(ACID 감사에서 재현)."""
    save_summary = store.save_summary
    calls = 0

    def dies_once(summary: SessionSummary) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("시드 도중 실패")
        save_summary(summary)

    monkeypatch.setattr(store, "save_summary", dies_once)
    with pytest.raises(RuntimeError):
        seed(store, owner.id)
    monkeypatch.setattr(store, "save_summary", save_summary)

    assert seed(store, owner.id) == 4
    statuses = [
        store.get_summary(session.id)
        for _, session, _ in store.list_interviews(owner.id)
        if session is not None
    ]
    assert [s.status for s in statuses if s is not None] == [SummaryStatus.READY] * 5
