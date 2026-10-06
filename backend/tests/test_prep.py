"""AI 내부 API ① 면접 전 분석 (#162) — AI 폴러가 한 바퀴 도는 길.

    GET /internal/v1/jobs/pending               → PREP 하나 (없으면 null)
    GET /internal/v1/sessions/{id}/context      → 회사 · JD · 이력서 · 역량 · 전사
    PUT /internal/v1/interviews/{id}/prep       → READY

결과 본문은 `fixtures/prep_result.json` 이다. #137 2-4 의 예시를 #156 `PrepResult` 가
내는 모양 그대로 둔 것이라, 저장하지 않는 필드(`rejections` · `usage` …)도 실려 있다.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import (
    Context,
    ContextDoc,
    DocCategory,
    DocKind,
    SummaryStatus,
    User,
)
from app.domain.store import InMemoryStore

V1 = "/api/v1"
INTERNAL = "/internal/v1"
PDF = b"%PDF-1.7\nresume\n"

PREP_RESULT: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "prep_result.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "internal_api_key", "test-secret")
    return "test-secret"


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def interview_id(client: TestClient) -> str:
    made = client.post(f"{V1}/interviews", json={"candidateName": "김도현"})
    return made.json()["interviewId"]


def open_session(client: TestClient, interview_id: str) -> str:
    return client.post(f"{V1}/interviews/{interview_id}/sessions").json()["sessionId"]


def upload_resume(client: TestClient, interview_id: str) -> str:
    made = client.post(
        f"{V1}/interviews/{interview_id}/resume",
        files={"file": ("이력서.pdf", PDF, "application/pdf")},
    )
    return made.json()["id"]


def pending(client: TestClient, key: str) -> Any:
    got = client.get(f"{INTERNAL}/jobs/pending", headers=auth(key))
    assert got.status_code == 200
    return got.json()


def context_of(client: TestClient, key: str, session_id: str) -> dict[str, Any]:
    got = client.get(f"{INTERNAL}/sessions/{session_id}/context", headers=auth(key))
    assert got.status_code == 200
    return got.json()


def put_prep(client: TestClient, key: str, interview_id: str, body: dict[str, Any]):
    return client.put(
        f"{INTERNAL}/interviews/{interview_id}/prep", json=body, headers=auth(key)
    )


def result_for(job: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """폴러가 받은 작업의 `requestedAt` 을 그대로 돌려 보낸다."""
    return PREP_RESULT | {"requestedAt": job["requestedAt"]} | overrides


# ── 할 일 조회 ──────────────────────────────────────────


def test_creating_a_session_asks_for_prep(
    client: TestClient, key: str, interview_id: str
) -> None:
    session_id = open_session(client, interview_id)

    job = pending(client, key)

    assert set(job) == {"kind", "sessionId", "interviewId", "requestedAt"}
    assert (job["kind"], job["sessionId"], job["interviewId"]) == (
        "PREP",
        session_id,
        interview_id,
    )
    assert datetime.fromisoformat(job["requestedAt"]).tzinfo is not None


def test_another_session_does_not_ask_again(
    client: TestClient, key: str, interview_id: str
) -> None:
    open_session(client, interview_id)
    first = pending(client, key)

    second_session = open_session(client, interview_id)
    again = pending(client, key)

    assert again["requestedAt"] == first["requestedAt"]
    # 컨텍스트는 세션으로 읽는다. 최근 세션이면 전사까지 같은 면접이다.
    assert again["sessionId"] == second_session


def test_a_new_resume_asks_again(
    client: TestClient, key: str, interview_id: str
) -> None:
    open_session(client, interview_id)
    first = pending(client, key)

    upload_resume(client, interview_id)

    assert pending(client, key)["requestedAt"] != first["requestedAt"]


def test_a_request_nobody_answers_gives_up(
    client: TestClient, key: str, interview_id: str, store: InMemoryStore
) -> None:
    """한도는 요약 한도에 문서 추출 한도를 더한 것이다 — 추출을 기다린 시간이 한도를
    먹어 버리지 않게."""
    open_session(client, interview_id)
    stored = store._preps[interview_id]  # pyright: ignore[reportPrivateUsage]

    stored.requested_at -= settings.summary_timeout + timedelta(seconds=1)
    assert pending(client, key) is not None

    stored.requested_at -= settings.doc_parse_timeout
    assert pending(client, key) is None
    found = store.get_prep(interview_id)
    assert found is not None
    assert found.status is SummaryStatus.FAILED


# ── 컨텍스트 ────────────────────────────────────────────


@pytest.fixture
def company(store: InMemoryStore, owner: User) -> Context:
    """면접관의 기업 컨텍스트 — JD 한 장, 사내 문서 한 장, 인재상."""
    context = store.ensure_context(Context(owner_id=owner.id))
    context.company = "누리뱅크"
    context.role = "백엔드 개발자"
    context.talent_profile = "끝까지 파고드는 사람"
    store.save_context(context)
    for name, category, text in [
        ("jd.pdf", DocCategory.JD, "JD 본문"),
        ("사내.pdf", DocCategory.INTERNAL, "사내 문서 본문"),
    ]:
        doc = ContextDoc(
            context_id=context.id,
            name=name,
            kind=DocKind.PDF,
            size_bytes=3,
            category=category,
        )
        store.add_doc(doc, PDF)
        store.finish_doc(context.id, doc.id, text)
    return context


def test_context_is_the_ai_interview_context(
    client: TestClient, key: str, interview_id: str, company: Context
) -> None:
    resume_id = upload_resume(client, interview_id)
    session_id = open_session(client, interview_id)

    assert context_of(client, key, session_id) == {
        "sessionId": session_id,
        "company": {"companyId": company.id, "name": "누리뱅크", "culture": None},
        "jobDescription": {
            "jdId": company.id,
            "companyId": company.id,
            "title": "백엔드 개발자",
            # 사내 문서는 넣지 않는다. JD 는 「이 직무가 요구하는 것」이다.
            "description": "JD 본문\n\n끝까지 파고드는 사람",
        },
        "competencies": [],
        "rubric": None,
        "candidate": {"candidateId": interview_id, "name": "김도현"},
        "resume": {
            "resumeId": resume_id,
            "candidateId": interview_id,
            "storageKey": None,
            "text": "추출한 본문",
        },
        "resumeClaims": [],
        "utterances": [],
    }


def test_context_without_a_resume(
    client: TestClient, key: str, interview_id: str
) -> None:
    """이력서는 선택이다. 없으면 `resume` 이 null 이다."""
    session_id = open_session(client, interview_id)

    assert context_of(client, key, session_id)["resume"] is None


def test_context_carries_the_live_transcript_in_the_ai_shape(
    client: TestClient, key: str, interview_id: str
) -> None:
    session_id = open_session(client, interview_id)
    with client.websocket_connect(
        f"{INTERNAL}/sessions/{session_id}/transcripts", headers=auth(key)
    ) as ws:
        ws.send_json(
            {
                "type": "transcript.upsert",
                "utteranceId": "utt_TR_b_0016",
                "participantId": "CANDIDATE",
                "trackId": "TR_b",
                "seq": 268900000003,
                "speaker": "CANDIDATE",
                "text": "초당 2만 건까지 올렸습니다.",
                "startedAtMs": 268900,
                "endedAtMs": 274100,
            }
        )
        ws.receive_json()

    assert context_of(client, key, session_id)["utterances"] == [
        {
            "utteranceId": "utt_TR_b_0016",
            "sessionId": session_id,
            "trackId": "TR_b",
            "speaker": "CANDIDATE",
            "seq": 268900000003,
            "startMs": 268900,
            "endMs": 274100,
            "content": "초당 2만 건까지 올렸습니다.",
        }
    ]


def test_context_of_an_unknown_session_is_404(client: TestClient, key: str) -> None:
    got = client.get(f"{INTERNAL}/sessions/ses_nope/context", headers=auth(key))
    assert got.status_code == 404


# ── 결과 저장 ───────────────────────────────────────────


def test_the_result_lands_in_the_context(
    client: TestClient, key: str, interview_id: str
) -> None:
    session_id = open_session(client, interview_id)
    job = pending(client, key)

    assert put_prep(client, key, interview_id, result_for(job)).status_code == 204

    context = context_of(client, key, session_id)
    assert context["competencies"] == PREP_RESULT["competencies"]
    assert context["resumeClaims"] == PREP_RESULT["resumeClaims"]
    assert pending(client, key) is None


def test_a_result_for_an_older_request_is_409(
    client: TestClient, key: str, interview_id: str
) -> None:
    """이력서를 다시 올리는 사이 늦게 온 옛 결과다."""
    open_session(client, interview_id)
    old = pending(client, key)
    upload_resume(client, interview_id)

    got = put_prep(client, key, interview_id, result_for(old))

    assert got.status_code == 409
    assert pending(client, key)["requestedAt"] != old["requestedAt"]


def test_a_failure_leaves_the_interview_without_prep(
    client: TestClient, key: str, interview_id: str, store: InMemoryStore
) -> None:
    """면접은 그대로 진행된다. 꼬리질문은 역량 · 주장 없이 만든다 (#137 3장)."""
    session_id = open_session(client, interview_id)
    job = pending(client, key)

    got = put_prep(
        client, key, interview_id, result_for(job, status="failed", competencies=[])
    )

    assert got.status_code == 204
    assert pending(client, key) is None
    found = store.get_prep(interview_id)
    assert found is not None
    assert found.status is SummaryStatus.FAILED
    assert context_of(client, key, session_id)["competencies"] == []


@pytest.mark.parametrize("status", ["partial", "empty"])
def test_partial_and_empty_are_ready(
    client: TestClient, key: str, interview_id: str, store: InMemoryStore, status: str
) -> None:
    """`empty` 는 JD 본문이 없었다는 뜻이다. 실패가 아니라 빈 목록이다."""
    open_session(client, interview_id)
    job = pending(client, key)

    put_prep(client, key, interview_id, result_for(job, status=status))

    found = store.get_prep(interview_id)
    assert found is not None
    assert found.status is SummaryStatus.READY


def test_prep_for_an_unknown_interview_is_404(client: TestClient, key: str) -> None:
    got = put_prep(
        client, key, "int_nope", PREP_RESULT | {"requestedAt": "2026-10-06T00:00:00Z"}
    )
    assert got.status_code == 404


def test_a_requested_at_without_a_timezone_is_refused(
    client: TestClient, key: str, interview_id: str
) -> None:
    """시간대가 없으면 같은 순간인지 가릴 수 없다. 옛 결과로 오인한 409 대신 422 다."""
    open_session(client, interview_id)

    got = put_prep(
        client, key, interview_id, PREP_RESULT | {"requestedAt": "2026-10-06T00:00:00"}
    )

    assert got.status_code == 422


def test_unstorable_text_is_refused(
    client: TestClient, key: str, interview_id: str
) -> None:
    """JSONB 는 NUL 문자를 못 넣는다. 저장에서 500 이 나면 폴러가 같은 결과를
    계속 보낸다."""
    open_session(client, interview_id)
    job = pending(client, key)
    claim = PREP_RESULT["resumeClaims"][0] | {"quote": "초당\x002만 건"}

    got = put_prep(client, key, interview_id, result_for(job, resumeClaims=[claim]))

    assert got.status_code == 422


# ── 인증 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/jobs/pending"),
        ("GET", "/sessions/ses_x/context"),
        ("PUT", "/interviews/int_x/prep"),
    ],
)
def test_the_key_is_required(
    client: TestClient, key: str, method: str, path: str
) -> None:
    got = client.request(method, f"{INTERNAL}{path}", json=PREP_RESULT)
    assert got.status_code == 401
