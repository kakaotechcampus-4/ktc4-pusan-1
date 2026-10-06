"""면접 기록(검토 상세) 조회 — `GET /interviews/{interviewId}/review` (#137 1-2 · #163).

기준 세션은 그 면접에서 가장 나중에 끝난 세션이다(목록과 같다).

    끝난 세션 없음 · 요약 PROCESSING  → 202 PROCESSING
    요약 READY                       → 200, 계산된 coverage · moments · findings
    요약 FAILED                      → 200, 분석만 빈다 (#163 결정)

계산 규칙 자체는 `test_review_rules.py` 가 본다. 여기서는 경로가 저장된 값을 제대로
모아 그 규칙에 넘기는지, 갈래가 맞는지를 본다.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import (
    Context,
    FindingState,
    InterviewPrep,
    ReviewMark,
    SummaryStatus,
    User,
)
from app.domain.store import InMemoryStore
from app.services.review import build_review

V1 = "/api/v1"
DEMO: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "app" / "demo_review.json").read_text(encoding="utf-8")
)


def _interview(client: TestClient, name: str | None = "김도현") -> str:
    return client.post(f"{V1}/interviews", json={"candidateName": name}).json()[
        "interviewId"
    ]


def _ended_session(client: TestClient, interview_id: str, *, start: bool = True) -> str:
    session_id = client.post(f"{V1}/interviews/{interview_id}/sessions").json()[
        "sessionId"
    ]
    if start:
        client.post(f"{V1}/sessions/{session_id}/start")
    client.post(f"{V1}/sessions/{session_id}/end")
    return session_id


def _prepared(store: InMemoryStore, interview_id: str) -> None:
    """면접 전 분석을 데모 역량 · 주장으로 READY 로 둔다."""
    opened = store.get_prep(interview_id) or InterviewPrep(interview_id=interview_id)
    store.ensure_prep(opened)
    opened.status = SummaryStatus.READY
    opened.competencies = DEMO["prep"]["competencies"]
    opened.resume_claims = DEMO["prep"]["resumeClaims"]
    store.finish_prep(opened)


def _analysed(store: InMemoryStore, session_id: str) -> None:
    """면접 후 분석을 데모 결과로 READY 로 둔다 (#164 가 붙기 전의 대역)."""
    summary = store.get_summary(session_id)
    assert summary is not None
    review = DEMO["review"]
    summary.complete(
        review["summary"],
        review["keyPoints"],
        moments=review["moments"],
        findings=review["findings"],
    )
    store.save_summary(summary)


def get_review(client: TestClient, interview_id: str):
    return client.get(f"{V1}/interviews/{interview_id}/review")


# ── 준비 전 (202) ───────────────────────────────────────


def test_an_interview_never_ended_is_processing(client: TestClient):
    response = get_review(client, _interview(client))

    # 202 인 건 FE 가 그렇게 읽기 때문이다 — "준비 전에는 202 와 PROCESSING".
    assert response.status_code == 202
    assert response.json() == {"status": "PROCESSING", "etaSec": None}


def test_a_summary_still_being_made_is_processing(client: TestClient):
    interview_id = _interview(client)
    _ended_session(client, interview_id)

    assert get_review(client, interview_id).status_code == 202


def test_a_summary_past_its_limit_is_judged_here_too(
    client: TestClient, store: InMemoryStore
):
    """요약 API 와 같은 판정이다. 아무도 요약 화면을 안 열어도 상세는 열린다."""
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    stored = store._summaries[session_id]  # pyright: ignore[reportPrivateUsage]
    stored.requested_at -= settings.summary_timeout + timedelta(seconds=1)

    response = get_review(client, interview_id)

    assert response.status_code == 200
    assert response.json()["summaryStatus"] == "FAILED"


# ── READY ───────────────────────────────────────────────


def test_a_ready_review_carries_the_computed_parts(
    client: TestClient, store: InMemoryStore, owner: User
):
    context = store.ensure_context(Context(owner_id=owner.id))
    context.role = "백엔드 개발자"
    store.save_context(context)
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    _prepared(store, interview_id)
    _analysed(store, session_id)
    store.save_mark(ReviewMark(session_id, "mom_qa_utt_TR_a_0007", bookmarked=True))

    response = get_review(client, interview_id)

    assert response.status_code == 200
    body = response.json()
    expected = build_review(
        DEMO["prep"]["competencies"],
        DEMO["prep"]["resumeClaims"],
        DEMO["review"]["moments"],
        DEMO["review"]["findings"],
        store.list_marks(session_id),
    )
    assert (body["coverage"], body["moments"], body["findings"]) == (
        expected.coverage,
        expected.moments,
        expected.findings,
    )
    assert body["moments"][1]["bookmarked"] is True
    assert body["summary"] == {
        "overview": DEMO["review"]["summary"],
        "keyPoints": DEMO["review"]["keyPoints"],
    }
    assert {k: body[k] for k in ("status", "summaryStatus", "interviewId")} == {
        "status": "READY",
        "summaryStatus": "READY",
        "interviewId": interview_id,
    }
    # 녹화는 싣지 않는다. FE 가 이 id 로 녹화 API 를 부른다 (#163).
    assert body["sessionId"] == session_id
    assert "recording" not in body
    assert body["candidate"] == {"name": "김도현", "role": "백엔드 개발자"}
    assert body["interviewer"] == {"nickname": owner.nickname}
    assert (body["reviewStatus"], body["reviewedAt"], body["memo"]) == (
        "PENDING",
        None,
        "",
    )
    assert body["interviewedAt"] is not None
    assert isinstance(body["durationSec"], int)


def test_the_latest_ended_session_is_the_one_shown(
    client: TestClient, store: InMemoryStore
):
    interview_id = _interview(client)
    _ended_session(client, interview_id)
    later = _ended_session(client, interview_id)
    store.fail_summary(later)

    assert get_review(client, interview_id).json()["sessionId"] == later


# ── FAILED (#163 결정) ──────────────────────────────────


def test_a_failed_summary_still_opens_with_an_empty_analysis(
    client: TestClient, store: InMemoryStore
):
    """AI 결과가 없어도 메모 · 검토 확정은 해야 한다. 역량은 전부 MISSING 이다."""
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    _prepared(store, interview_id)
    store.fail_summary(session_id)
    store.save_mark(ReviewMark(session_id, "fnd_x", state=FindingState.ADOPTED))

    response = get_review(client, interview_id)

    assert response.status_code == 200
    body = response.json()
    assert body["summaryStatus"] == "FAILED"
    assert body["summary"] is None
    assert (body["moments"], body["findings"]) == ([], [])
    assert [c["state"] for c in body["coverage"]] == ["MISSING"] * 4


def test_a_session_ended_before_summaries_existed_waits_like_the_summary_api(
    client: TestClient, store: InMemoryStore
):
    """요약 자리가 없으면 지금 만든다 — 요약 API 와 같다. 한도가 지나면 FAILED 다."""
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    store._summaries.pop(session_id)  # pyright: ignore[reportPrivateUsage]

    assert get_review(client, interview_id).status_code == 202
    assert store.get_summary(session_id) is not None


# ── 면접 정보 ───────────────────────────────────────────


def test_an_interview_never_started_has_no_time(
    client: TestClient, store: InMemoryStore
):
    """「시작」을 안 누르고 아무도 입장하지 않고 끝낸 면접. 500 이 아니라 null 이다."""
    interview_id = _interview(client, name=None)
    session_id = _ended_session(client, interview_id, start=False)
    store.fail_summary(session_id)

    body = get_review(client, interview_id).json()

    assert (body["interviewedAt"], body["durationSec"]) == (None, None)
    assert body["candidate"]["name"] is None


def test_review_of_unknown_interview(client: TestClient):
    response = get_review(client, "int_nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


def test_the_ready_shape_is_published(client: TestClient):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert {"ReviewResponse", "ReviewProcessingResponse"} <= set(schemas)


# ── 검토 상태 · 메모 (#137 1-3) ─────────────────────────


def patch(client: TestClient, interview_id: str, body: dict[str, Any]):
    return client.patch(f"{V1}/interviews/{interview_id}", json=body)


def test_confirming_stamps_the_time(client: TestClient):
    interview_id = _interview(client)

    response = patch(
        client, interview_id, {"reviewStatus": "CONFIRMED", "memo": "확인"}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"reviewStatus", "reviewedAt", "memo"}
    assert (body["reviewStatus"], body["memo"]) == ("CONFIRMED", "확인")
    assert body["reviewedAt"] is not None


def test_the_review_survives_a_reload(client: TestClient, store: InMemoryStore):
    interview_id = _interview(client)
    patch(client, interview_id, {"reviewStatus": "IN_REVIEW", "memo": "다시 볼 것"})

    stored = store.get_interview(interview_id)

    assert stored is not None
    assert (stored.review_status.value, stored.memo) == ("IN_REVIEW", "다시 볼 것")


def test_confirming_again_keeps_the_first_time(client: TestClient):
    """메모를 저장할 때 상태가 같이 실려 와도 확정 시각이 밀리지 않는다."""
    interview_id = _interview(client)
    first = patch(client, interview_id, {"reviewStatus": "CONFIRMED"}).json()

    again = patch(client, interview_id, {"reviewStatus": "CONFIRMED", "memo": "덧붙임"})

    assert again.json()["reviewedAt"] == first["reviewedAt"]


def test_a_memo_alone_leaves_the_status(client: TestClient):
    interview_id = _interview(client)
    confirmed = patch(client, interview_id, {"reviewStatus": "CONFIRMED"}).json()

    body = patch(client, interview_id, {"memo": "메모만"}).json()

    assert (body["reviewStatus"], body["reviewedAt"]) == (
        "CONFIRMED",
        confirmed["reviewedAt"],
    )


def test_leaving_confirmed_clears_the_time(client: TestClient):
    interview_id = _interview(client)
    patch(client, interview_id, {"reviewStatus": "CONFIRMED"})

    body = patch(client, interview_id, {"reviewStatus": "IN_REVIEW"}).json()

    assert (body["reviewStatus"], body["reviewedAt"]) == ("IN_REVIEW", None)


def test_null_means_unchanged_and_empty_clears(client: TestClient):
    interview_id = _interview(client)
    patch(client, interview_id, {"memo": "남길 것"})

    kept = patch(client, interview_id, {"memo": None}).json()
    cleared = patch(client, interview_id, {"memo": ""}).json()

    assert (kept["memo"], cleared["memo"]) == ("남길 것", "")


def test_an_empty_patch_changes_nothing(client: TestClient):
    interview_id = _interview(client)

    body = patch(client, interview_id, {}).json()

    assert body == {"reviewStatus": "PENDING", "reviewedAt": None, "memo": ""}


def test_review_can_change_before_any_analysis(client: TestClient):
    """AI 결과가 없어도(세션도 없어도) 검토 상태 · 메모는 바뀐다."""
    interview_id = _interview(client)

    assert patch(client, interview_id, {"reviewStatus": "IN_REVIEW"}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"reviewStatus": "DONE"},
        {"memo": "가" * 4001},
        {"memo": "NUL\x00"},
    ],
)
def test_unstorable_review_input_is_refused(client: TestClient, body: dict[str, Any]):
    assert patch(client, _interview(client), body).status_code == 422


# ── 채택 · 북마크 (#137 1-4) ────────────────────────────

FINDING_ID = DEMO["review"]["findings"][1]["findingId"]
MOMENT_ID = DEMO["review"]["moments"][2]["momentId"]


def _ready(client: TestClient, store: InMemoryStore) -> tuple[str, str]:
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    _prepared(store, interview_id)
    _analysed(store, session_id)
    return interview_id, session_id


def put_mark(client: TestClient, interview_id: str, item_id: str, body: Any):
    return client.put(
        f"{V1}/interviews/{interview_id}/review/marks/{item_id}", json=body
    )


def test_adopting_a_finding_shows_in_the_detail(
    client: TestClient, store: InMemoryStore
):
    interview_id, _ = _ready(client, store)

    response = put_mark(client, interview_id, FINDING_ID, {"state": "ADOPTED"})

    assert response.status_code == 200
    assert response.json() == {
        "itemId": FINDING_ID,
        "state": "ADOPTED",
        "bookmarked": False,
    }
    findings = get_review(client, interview_id).json()["findings"]
    assert {f["id"]: f["state"] for f in findings}[FINDING_ID] == "ADOPTED"


def test_only_the_sent_field_changes(client: TestClient, store: InMemoryStore):
    interview_id, _ = _ready(client, store)
    put_mark(client, interview_id, MOMENT_ID, {"bookmarked": True})

    body = put_mark(client, interview_id, MOMENT_ID, {"state": "REJECTED"}).json()

    assert (body["state"], body["bookmarked"]) == ("REJECTED", True)
    moments = get_review(client, interview_id).json()["moments"]
    assert {m["id"]: m["bookmarked"] for m in moments}[MOMENT_ID] is True


def test_an_item_the_detail_does_not_have_is_404(
    client: TestClient, store: InMemoryStore
):
    """아무 id 로 행이 쌓이지 않는다 (#163 결정)."""
    interview_id, session_id = _ready(client, store)

    response = put_mark(client, interview_id, "fnd_nope", {"state": "ADOPTED"})

    assert response.status_code == 404
    assert store.list_marks(session_id) == []


def test_marks_wait_for_an_analysis(client: TestClient, store: InMemoryStore):
    """끝난 세션이 없거나 요약이 FAILED 면 표시할 항목이 없다."""
    never_ended = _interview(client)
    failed = _interview(client)
    store.fail_summary(_ended_session(client, failed))

    for interview_id in (never_ended, failed):
        got = put_mark(client, interview_id, FINDING_ID, {"state": "ADOPTED"})
        assert got.status_code == 404


@pytest.mark.parametrize("body", [{}, {"state": "EDITED"}, {"bookmarked": "maybe"}])
def test_a_mark_without_a_usable_field_is_refused(
    client: TestClient, store: InMemoryStore, body: dict[str, Any]
):
    interview_id, _ = _ready(client, store)

    assert put_mark(client, interview_id, FINDING_ID, body).status_code == 422
