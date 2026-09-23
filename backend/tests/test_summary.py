"""면접 요약 — 상태 저장과 조회.

`GET /sessions/{id}/summary` 가 **저장된 상태**를 돌려준다. 지어낸 값이 아니다.

    면접 종료 ──> PROCESSING ──Agent 가 결과를 씀──> READY
                            └─한도를 넘김────────> FAILED

요약 본문을 만드는 쪽(#70)이 아직 없어도 이 기계는 그대로 돈다. 그게 이 테스트들이
지키려는 것이다 — **종료 상태가 반드시 온다.** 안 오면 FE 가 PROCESSING 동안만
다시 조회하므로 화면이 영원히 돈다.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import SummaryStatus
from app.domain.store import InMemoryStore

V1 = "/api/v1"


def summary(client: TestClient, session_id: str):
    return client.get(f"{V1}/sessions/{session_id}/summary")


def ended(client: TestClient, session_id: str) -> str:
    client.post(f"{V1}/sessions/{session_id}/start")
    client.post(f"{V1}/sessions/{session_id}/end")
    return session_id


def age(store: InMemoryStore, session_id: str, delta: timedelta) -> None:
    """실제로 기다리지 않고 기다린 것처럼 만든다."""
    stored = store.get_summary(session_id)
    assert stored is not None
    stored.requested_at -= delta
    store.save_summary(stored)


# ── 자리가 생기는 시점 ────────────────────────────────────────


def test_ending_the_interview_opens_a_summary_slot(
    client: TestClient, store: InMemoryStore, session_id: str
) -> None:
    """종료 시점에 만든다. 조회 시점이 아니다.

    한도의 기준점이 여기서 찍힌다. 화면을 늦게 열었다고 마감이 그때부터 다시
    시작되면, 안 보고 있는 동안은 시간이 안 흐르는 셈이 된다.
    """
    assert store.get_summary(session_id) is None

    ended(client, session_id)

    stored = store.get_summary(session_id)
    assert stored is not None
    assert stored.status is SummaryStatus.PROCESSING


def test_a_later_write_does_not_restart_the_clock(
    client: TestClient, store: InMemoryStore, session_id: str, key: str
) -> None:
    """자리를 만드는 호출이 뒤에 또 와도 기준점은 처음 것이어야 한다.

    `PUT .../review` 도 자리를 확보하고 들어온다. 그때 `requested_at` 이 밀리면
    한도가 계속 연장돼 FAILED 로 갈 수가 없다. (덮어쓰기 자체는 저장소 계약
    테스트가 두 구현 모두에서 잡는다.)
    """
    ended(client, session_id)
    first = store.get_summary(session_id)
    assert first is not None
    started_waiting_at = first.requested_at

    put_review(client, session_id, key)

    again = store.get_summary(session_id)
    assert again is not None
    assert again.requested_at == started_waiting_at


def test_summary_before_the_interview_ends_is_409(
    client: TestClient, session_id: str
) -> None:
    """아직 안 끝났으면 요약할 대상이 없다. PROCESSING 으로 둘러대지 않는다."""
    assert summary(client, session_id).status_code == 409


def test_summary_of_an_unknown_session_is_404(client: TestClient) -> None:
    assert summary(client, "ses_없는것").status_code == 404


# ── 조회 모양 ────────────────────────────────────────────────


def test_a_fresh_summary_is_processing_with_the_fe_shape(
    client: TestClient, session_id: str
) -> None:
    got = summary(client, ended(client, session_id))
    assert got.status_code == 200
    body = got.json()
    # FE 의 InterviewSummary 그대로.
    assert set(body) == {"sessionId", "status", "content", "durationSec"}
    assert body["sessionId"] == session_id
    assert body["status"] == "PROCESSING"
    assert body["content"] is None


def test_duration_is_counted_between_start_and_end(
    client: TestClient, store: InMemoryStore, session_id: str
) -> None:
    client.post(f"{V1}/sessions/{session_id}/start")

    session = store.get_session(session_id)
    assert session is not None and session.started_at is not None
    session.started_at -= timedelta(seconds=125)
    store.save_session(session)

    client.post(f"{V1}/sessions/{session_id}/end")
    assert summary(client, session_id).json()["durationSec"] == 125


def test_duration_is_zero_when_the_interview_never_started(
    client: TestClient, session_id: str
) -> None:
    """시작을 안 누르고 끝냈다. 잴 수가 없으니 지어내지 않는다."""
    client.post(f"{V1}/sessions/{session_id}/end")
    assert summary(client, session_id).json()["durationSec"] == 0


# ── 한도 ────────────────────────────────────────────────────


def test_waiting_too_long_becomes_failed(
    client: TestClient, store: InMemoryStore, session_id: str
) -> None:
    """**이 PR 의 핵심.** 아무도 결과를 안 써 주면 서버가 끝을 낸다.

    이게 없으면 FE 가 PROCESSING 동안 2초마다 영원히 다시 묻는다.
    """
    ended(client, session_id)
    assert summary(client, session_id).json()["status"] == "PROCESSING"

    age(store, session_id, settings.summary_timeout + timedelta(seconds=1))

    body = summary(client, session_id).json()
    assert body["status"] == "FAILED"
    assert body["content"] is None


def test_just_under_the_limit_is_still_processing(
    client: TestClient, store: InMemoryStore, session_id: str
) -> None:
    ended(client, session_id)
    age(store, session_id, settings.summary_timeout - timedelta(seconds=1))

    assert summary(client, session_id).json()["status"] == "PROCESSING"


def test_giving_up_is_written_down_not_just_returned(
    client: TestClient,
    store: InMemoryStore,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """판정 결과를 저장한다.

    ⚠️ 인메모리 저장소는 객체를 **참조로** 돌려주므로, 라우터가
    `save_summary` 를 빠뜨려도 여기서는 티가 안 난다. DB 는 안 그렇다 — 다시
    조회하면 PROCESSING 이 그대로 나와서, 볼 때마다 FAILED 를 만들었다가 잊는
    상태가 된다. 그래서 상태가 아니라 **저장을 불렀는지**를 본다.
    """
    saved: list[SummaryStatus] = []
    write = store.save_summary

    def spy(summary_to_save) -> None:
        saved.append(summary_to_save.status)
        write(summary_to_save)

    ended(client, session_id)
    age(store, session_id, settings.summary_timeout + timedelta(seconds=1))
    monkeypatch.setattr(store, "save_summary", spy)

    assert summary(client, session_id).json()["status"] == "FAILED"
    assert SummaryStatus.FAILED in saved


def test_a_ready_summary_does_not_expire(
    client: TestClient, store: InMemoryStore, session_id: str, key: str
) -> None:
    """한도는 기다리는 동안만이다. 이미 나온 요약은 오래됐다고 사라지지 않는다."""
    ended(client, session_id)
    put_review(client, session_id, key)
    age(store, session_id, settings.summary_timeout * 10)

    assert summary(client, session_id).json()["status"] == "READY"


# ── Agent 가 결과를 써 넣는 경로 ────────────────────────────────


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    from app.core.config import settings

    monkeypatch.setattr(settings, "internal_api_key", "test-secret")
    return "test-secret"


def put_review(
    client: TestClient,
    session_id: str,
    key: str,
    *,
    status: str = "completed",
    summary_text: str = "지원자는 캐시 도입 경험을 근거와 함께 설명했다.",
    key_points: list[str] | None = None,
):
    return client.put(
        f"/internal/v1/sessions/{session_id}/review",
        json={
            "status": status,
            "summary": summary_text,
            "keyPoints": ["Redis 캐시 도입", "부하 테스트 3,000 RPS"]
            if key_points is None
            else key_points,
        },
        headers={"Authorization": f"Bearer {key}"},
    )


def test_agent_result_makes_the_summary_ready(
    client: TestClient, session_id: str, key: str
) -> None:
    ended(client, session_id)

    assert put_review(client, session_id, key).status_code == 204

    body = summary(client, session_id).json()
    assert body["status"] == "READY"
    assert body["content"] == {
        "overview": "지원자는 캐시 도입 경험을 근거와 함께 설명했다.",
        "keyPoints": ["Redis 캐시 도입", "부하 테스트 3,000 RPS"],
    }


def test_partial_still_has_something_to_show(
    client: TestClient, session_id: str, key: str
) -> None:
    """`partial` 은 근거 검증에서 일부가 떨어진 것이다. 보여 줄 내용은 있다."""
    ended(client, session_id)
    put_review(client, session_id, key, status="partial")

    assert summary(client, session_id).json()["status"] == "READY"


@pytest.mark.parametrize("agent_status", ["empty", "failed"])
def test_agent_failure_becomes_failed(
    client: TestClient, session_id: str, key: str, agent_status: str
) -> None:
    ended(client, session_id)
    put_review(client, session_id, key, status=agent_status, summary_text="")

    body = summary(client, session_id).json()
    assert body["status"] == "FAILED"
    assert body["content"] is None


def test_a_done_status_without_a_body_is_refused(
    client: TestClient, session_id: str, key: str
) -> None:
    """본문 없이 READY 로 넘어가면 FE 가 빈 요약 카드를 그린다."""
    ended(client, session_id)

    got = put_review(client, session_id, key, status="completed", summary_text="   ")

    assert got.status_code == 422
    assert summary(client, session_id).json()["status"] == "PROCESSING"


def test_review_is_idempotent(client: TestClient, session_id: str, key: str) -> None:
    """Agent 의 재시도는 응답을 못 받은 것과 처리가 안 된 것을 구분 못 한다."""
    ended(client, session_id)
    put_review(client, session_id, key)
    put_review(client, session_id, key)

    body = summary(client, session_id).json()
    assert body["status"] == "READY"
    assert body["content"] is not None


def test_a_late_result_still_lands(
    client: TestClient, store: InMemoryStore, session_id: str, key: str
) -> None:
    """한도를 넘겨 FAILED 가 된 뒤에 결과가 와도 받는다.

    요약이 실제로 있는데 실패로 두는 편이 더 나쁘다.
    """
    ended(client, session_id)
    age(store, session_id, settings.summary_timeout + timedelta(seconds=1))
    assert summary(client, session_id).json()["status"] == "FAILED"

    put_review(client, session_id, key)

    assert summary(client, session_id).json()["status"] == "READY"


def test_review_without_the_key_is_unauthorized(
    client: TestClient, session_id: str, key: str
) -> None:
    ended(client, session_id)
    got = client.put(
        f"/internal/v1/sessions/{session_id}/review",
        json={"status": "completed", "summary": "요약", "keyPoints": []},
    )
    assert got.status_code == 401
    assert summary(client, session_id).json()["status"] == "PROCESSING"


def test_review_for_an_unknown_session_is_404(client: TestClient, key: str) -> None:
    assert put_review(client, "ses_없는것", key).status_code == 404
