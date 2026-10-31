"""면접 리포트 한 바퀴 (#238) — 면접관이 버튼을 누르고 AI 가 채우고 다시 읽는 길.

    POST /api/v1/interviews/{id}/report                 → 202 (자리를 연다)
    GET  /internal/v1/jobs/pending                      → kind="REPORT"
    GET  /internal/v1/interviews/{id}/report/context    → 채택한 근거만
    PUT  /internal/v1/interviews/{id}/report            → 204
    GET  /api/v1/interviews/{id}/report                  → READY 본문

401 · 남의 면접 404 는 `tests/test_authorization.py` 의 표가 전부 돈다. 내부 API 의
키 요구는 `tests/test_prep.py` 의 표에 있다. 여기서는 리포트만의 판정을 본다.
"""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.models import Context, User, utcnow
from app.domain.store import InMemoryStore
from tests.conftest import DEMO, age_report, analysed, prepared

V1 = "/api/v1"
INTERNAL = "/internal/v1"

#: 데모 시드의 근거 id. 어느 역량에 걸리는지가 카드 상태를 가른다.
DESIGN = "fnd_COMPETENCY_EVIDENCE_cpt_design_utt_TR_b_0002"
PERF = "fnd_CLAIM_UNVERIFIED_clm_002_utt_TR_b_0016"
COLLAB = "fnd_COMPETENCY_EVIDENCE_cpt_collab_utt_TR_b_0009"


# ── 거기까지 가는 길 ────────────────────────────────────


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "internal_api_key", "test-secret")
    return "test-secret"


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _interview(client: TestClient, name: str = "김도현") -> str:
    return client.post(f"{V1}/interviews", json={"candidateName": name}).json()[
        "interviewId"
    ]


def _ended_session(client: TestClient, interview_id: str) -> str:
    session_id = client.post(f"{V1}/interviews/{interview_id}/sessions").json()[
        "sessionId"
    ]
    client.post(f"{V1}/sessions/{session_id}/start")
    client.post(f"{V1}/sessions/{session_id}/end")
    return session_id


def _mark(client: TestClient, interview_id: str, item_id: str, state: str) -> None:
    got = client.put(
        f"{V1}/interviews/{interview_id}/review/marks/{item_id}",
        json={"state": state},
    )
    assert got.status_code == 200, got.text


def _confirm(client: TestClient, interview_id: str, memo: str = "메모"):
    return client.patch(
        f"{V1}/interviews/{interview_id}",
        json={"reviewStatus": "CONFIRMED", "memo": memo},
    )


def reviewed(
    client: TestClient,
    store: InMemoryStore,
    *,
    adopt: tuple[str, ...] = (DESIGN, PERF),
    reject: tuple[str, ...] = (),
    confirm: bool = True,
) -> tuple[str, str]:
    """리포트를 만들 수 있는 상태까지 — 분석이 끝나고 채택하고 확정한 면접."""
    interview_id = _interview(client)
    session_id = _ended_session(client, interview_id)
    prepared(store, interview_id)
    analysed(store, session_id)
    for item_id in adopt:
        _mark(client, interview_id, item_id, "ADOPTED")
    for item_id in reject:
        _mark(client, interview_id, item_id, "REJECTED")
    if confirm:
        assert _confirm(client, interview_id).status_code == 200
    return interview_id, session_id


def ask(client: TestClient, interview_id: str):
    return client.post(f"{V1}/interviews/{interview_id}/report")


def read(client: TestClient, interview_id: str):
    return client.get(f"{V1}/interviews/{interview_id}/report")


def pending(client: TestClient, key: str) -> Any:
    got = client.get(f"{INTERNAL}/jobs/pending", headers=auth(key))
    assert got.status_code == 200
    return got.json()


def context_of(client: TestClient, key: str, interview_id: str):
    return client.get(
        f"{INTERNAL}/interviews/{interview_id}/report/context", headers=auth(key)
    )


def put_report(client: TestClient, key: str, interview_id: str, body: dict[str, Any]):
    return client.put(
        f"{INTERNAL}/interviews/{interview_id}/report", json=body, headers=auth(key)
    )


def written(requested_at: str, **overrides: Any) -> dict[str, Any]:
    """AI 가 보내는 본문. 문장은 `{text, findingId}` 뿐이다 (#163).

    일부러 세 가지를 섞어 뒀다 — 채택하지 않은 근거를 단 문장(`cpt_design` 의
    `unconfirmed`), 다루지 않은 역량에 달린 꼬리질문(`cpt_collab`), 아예 보내지
    않은 역량(`cpt_incident`).
    """
    return {
        "status": "completed",
        "requestedAt": requested_at,
        "model": "test-model",
        "overview": (
            "실시간 파이프라인 경험을 설명했고, 처리량 수치의 근거는\n"
            "면접에서 확인되지 않았다."
        ),
        "competencies": [
            {
                "competencyId": "cpt_design",
                "confirmed": [
                    {
                        "text": "실시간 스트리밍 파이프라인을 맡아 왔다고 설명함",
                        "findingId": DESIGN,
                    }
                ],
                "unconfirmed": [
                    {"text": "채택하지 않은 근거를 단 문장", "findingId": COLLAB}
                ],
                "nextQuestions": ["파이프라인의 처리량 한계를 어디서 봤는지"],
            },
            {
                "competencyId": "cpt_perf",
                "confirmed": [],
                "unconfirmed": [
                    {
                        "text": "초당 2만 건은 병목을 재 보지 못했다고 답함",
                        "findingId": PERF,
                    }
                ],
                "nextQuestions": ["병목을 무엇으로 측정할 생각인지"],
            },
            {
                "competencyId": "cpt_collab",
                "confirmed": [],
                "unconfirmed": [],
                "nextQuestions": ["협업에서 맡은 역할"],
            },
        ],
    } | overrides


def finished(client: TestClient, key: str, store: InMemoryStore, **overrides: Any):
    """버튼 → 작업 → 저장까지. 돌려주는 것은 `(interviewId, sessionId, job)`."""
    interview_id, session_id = reviewed(client, store)
    assert ask(client, interview_id).status_code == 202
    job = pending(client, key)
    assert (
        put_report(
            client, key, interview_id, written(job["requestedAt"], **overrides)
        ).status_code
        == 204
    )
    return interview_id, session_id, job


# ── 생성 요청 ───────────────────────────────────────────


def test_asking_opens_one_slot_on_the_ended_session(
    client: TestClient, store: InMemoryStore
) -> None:
    interview_id, session_id = reviewed(client, store)

    got = ask(client, interview_id)

    assert got.status_code == 202
    assert got.json() == {"status": "PROCESSING", "etaSec": None}
    report = store.get_report(interview_id)
    assert report is not None
    # 기준 세션을 박아 둔다 — 근거 시각의 원점이 흔들리면 안 된다.
    assert report.session_id == session_id


def test_an_unconfirmed_review_cannot_be_handed_over(
    client: TestClient, store: InMemoryStore
) -> None:
    """리포트는 확정된 판단을 넘기는 문서다."""
    interview_id, _ = reviewed(client, store, confirm=False)

    got = ask(client, interview_id)

    assert got.status_code == 409
    assert got.json()["error"]["code"] == "REVIEW_NOT_CONFIRMED"


def test_without_an_adopted_finding_there_is_nothing_to_write(
    client: TestClient, store: InMemoryStore
) -> None:
    """반려한 근거는 세지 않는다 — 센 곳이 AI 가 받는 곳과 같은 함수다."""
    interview_id, _ = reviewed(client, store, adopt=(), reject=(DESIGN,))

    got = ask(client, interview_id)

    assert got.status_code == 409
    assert got.json()["error"]["code"] == "NO_ADOPTED_FINDING"


def test_pressing_twice_while_it_is_being_made_is_refused(
    client: TestClient, store: InMemoryStore
) -> None:
    interview_id, _ = reviewed(client, store)
    assert ask(client, interview_id).status_code == 202

    got = ask(client, interview_id)

    assert got.status_code == 409
    assert got.json()["error"]["code"] == "REPORT_IN_PROGRESS"


def test_past_the_limit_it_can_be_asked_again(
    client: TestClient, store: InMemoryStore
) -> None:
    """아무도 채우지 않은 자리는 계속 막고 있지 않는다."""
    interview_id, _ = reviewed(client, store)
    assert ask(client, interview_id).status_code == 202
    stale = store.get_report(interview_id)
    assert stale is not None
    age_report(store, interview_id, settings.report_timeout + timedelta(seconds=1))

    assert ask(client, interview_id).status_code == 202

    fresh = store.get_report(interview_id)
    assert fresh is not None
    assert fresh.requested_at > stale.requested_at


def test_asking_again_overwrites_the_report_that_was_there(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """면접 하나에 리포트 하나다 — 버전을 남기지 않는다."""
    interview_id, _, _ = finished(client, key, store)
    assert read(client, interview_id).json()["status"] == "READY"

    assert ask(client, interview_id).status_code == 202

    assert read(client, interview_id).status_code == 202
    report = store.get_report(interview_id)
    assert report is not None
    assert (report.overview, report.competencies) == ("", [])


# ── 조회 ────────────────────────────────────────────────


def test_a_report_nobody_asked_for_is_missing(
    client: TestClient, store: InMemoryStore
) -> None:
    """없는 면접(`INTERVIEW_NOT_FOUND`)과 코드가 다르다 — FE 가 보일 화면이 갈린다."""
    interview_id, _ = reviewed(client, store)

    got = read(client, interview_id)

    assert got.status_code == 404
    assert got.json()["error"]["code"] == "REPORT_NOT_FOUND"


def test_a_report_being_made_is_processing(
    client: TestClient, store: InMemoryStore
) -> None:
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)

    got = read(client, interview_id)

    assert got.status_code == 202
    assert got.json() == {"status": "PROCESSING", "etaSec": None}


def test_a_report_past_its_limit_is_folded_here(
    client: TestClient, store: InMemoryStore
) -> None:
    """아무도 기다려 주지 않아도 화면은 끝나야 한다 (요약·면접 전 분석과 같은 판정)."""
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)
    age_report(store, interview_id, settings.report_timeout + timedelta(seconds=1))

    got = read(client, interview_id)

    assert got.status_code == 200
    body = got.json()
    assert (body["status"], body["failureReason"]) == ("FAILED", None)
    # 머리는 그대로 나간다 — 실패 화면에서도 누구의 어떤 면접인지는 읽힌다.
    assert (body["memo"], body["candidate"]["name"]) == ("메모", "김도현")
    assert (body["overview"], body["competencies"]) == ("", [])


def test_a_ready_report_reads_as_a_handover(
    client: TestClient, key: str, store: InMemoryStore, owner: User
) -> None:
    context = store.ensure_context(Context(owner_id=owner.id))
    context.role = "백엔드 개발자"
    store.save_context(context)
    interview_id, session_id, _ = finished(client, key, store)

    got = read(client, interview_id)

    assert got.status_code == 200
    body = got.json()
    assert (body["status"], body["interviewId"], body["sessionId"]) == (
        "READY",
        interview_id,
        session_id,
    )
    assert body["reviewStatus"] == "CONFIRMED"
    assert body["candidate"] == {"name": "김도현", "role": "백엔드 개발자"}
    assert body["interviewer"] == {"nickname": owner.nickname}
    assert body["memo"] == "메모"
    assert body["overview"].startswith("실시간 파이프라인")
    assert body["generatedAt"] is not None
    assert body["interviewedAt"] is not None
    assert body["failureReason"] is None
    # 점수 · 합격 여부 · 집계는 없다.
    assert not {"score", "passed", "rank", "adoptedCount"} & set(body)


def test_the_cards_are_every_jd_competency_in_order(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """AI 가 빠뜨린 역량도 카드로 남아야 「다루지 않음」이 보인다."""
    interview_id, _, _ = finished(client, key, store)

    cards = read(client, interview_id).json()["competencies"]

    names = ["서비스 설계", "성능 개선", "협업", "장애 대응"]
    assert [c["name"] for c in cards] == names
    assert [c["state"] for c in cards] == ["CONFIRMED", "PARTIAL", "MISSING", "MISSING"]
    # 필수 여부는 BE 가 JD 에서 붙인다 (#163) — AI 는 보내지 않는다.
    assert [c["required"] for c in cards] == [True, True, False, True]


def test_each_statement_carries_the_evidence_be_joined(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """같은 근거가 검토 화면과 리포트에서 다르게 보이면 안 된다."""
    interview_id, _, _ = finished(client, key, store)

    cards = read(client, interview_id).json()["competencies"]

    design = cards[0]["confirmed"][0]
    assert (design["findingId"], design["findingType"]) == (
        DESIGN,
        "COMPETENCY_EVIDENCE",
    )
    # 면접 발화만 있는 근거다 — 지원서 문장은 없다.
    assert (design["source"], design["quote"]) == ("면접 답변", None)
    assert design["transcript"] == "실시간 스트리밍 파이프라인을 주로 맡아 왔습니다."
    assert design["atSec"] == 19.2

    perf = cards[1]["unconfirmed"][0]
    assert perf["source"] == "지원서 · 성과 2"
    assert perf["quote"] == "초당 2만 건의 이벤트를 안정적으로 처리했습니다."
    assert perf["transcript"] == (
        "초당 2만 건까지 올렸는데 병목은 구체적으로 재보지 못했습니다."
    )
    assert perf["atSec"] == 268.9


def test_a_statement_pointing_at_an_unadopted_finding_is_dropped(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """모든 문장에 근거가 붙는다 — 채택하지 않은 id 를 단 문장은 버린다."""
    interview_id, _, _ = finished(client, key, store)

    cards = read(client, interview_id).json()["competencies"]

    assert cards[0]["unconfirmed"] == []


def test_a_competency_the_interview_never_covered_keeps_only_its_questions(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """MISSING 이면 확인된·확인되지 않은 점은 비우고 꼬리질문만 남긴다.

    리포트를 받는 2차 면접관에게는 안 다룬 역량이 바로 물어볼 거리다. 근거가 없는
    「확인된」 문장은 거짓이지만, 「다음에 물어볼 것」은 근거를 필요로 하지 않는다.
    """
    interview_id, _, _ = finished(client, key, store)

    cards = read(client, interview_id).json()["competencies"]

    for card in cards[2:]:
        assert (card["confirmed"], card["unconfirmed"]) == ([], [])
    # AI 가 보낸 역량은 꼬리질문이 남고, 아예 보내지 않은 역량은 빈 배열이다.
    assert cards[2]["nextQuestions"] == ["협업에서 맡은 역할"]
    assert cards[3]["nextQuestions"] == []
    # 다룬 역량의 결론도 그대로다.
    assert cards[0]["nextQuestions"] == ["파이프라인의 처리량 한계를 어디서 봤는지"]


@pytest.mark.parametrize(
    ("agent_status", "reason"), [("empty", "NO_EVIDENCE"), ("failed", None)]
)
def test_the_two_failures_are_told_apart(
    client: TestClient,
    key: str,
    store: InMemoryStore,
    agent_status: str,
    reason: str | None,
) -> None:
    """「채택한 근거로 만들 수 없었다」와 「다시 만들어 보세요」는 다른 말이다."""
    interview_id, _, _ = finished(client, key, store, status=agent_status)

    body = read(client, interview_id).json()

    assert (body["status"], body["failureReason"]) == ("FAILED", reason)
    assert (body["overview"], body["competencies"]) == ("", [])
    assert (body["memo"], body["candidate"]["name"]) == ("메모", "김도현")


# ── 내부 API: 작업 ──────────────────────────────────────


def test_the_button_is_what_puts_a_report_in_the_queue(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    interview_id, session_id = reviewed(client, store)
    assert pending(client, key) is None

    ask(client, interview_id)

    job = pending(client, key)
    assert job["kind"] == "REPORT"
    assert (job["interviewId"], job["sessionId"]) == (interview_id, session_id)
    assert set(job) == {"kind", "sessionId", "interviewId", "requestedAt"}


def test_a_report_waits_behind_prep_and_review(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """앞의 둘은 다음 면접과 검토 화면 전체가 막혀 있다. 리포트는 한 사람이 기다린다."""
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)
    later = _interview(client, "이서준")
    later_session = _ended_session(client, later)
    store.mark_transcript(later_session, utcnow())

    assert pending(client, key)["kind"] == "PREP"

    prepared(store, later)
    assert pending(client, key)["kind"] == "REVIEW"

    analysed(store, later_session)
    assert pending(client, key)["kind"] == "REPORT"


# ── 내부 API: 입력 ──────────────────────────────────────


def test_the_context_is_only_what_the_report_is_written_from(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    interview_id, session_id = reviewed(client, store)
    ask(client, interview_id)

    got = context_of(client, key, interview_id)

    assert got.status_code == 200
    body = got.json()
    assert set(body) == {
        "interviewId",
        "sessionId",
        "requestedAt",
        "summary",
        "competencies",
        "findings",
    }
    assert (body["interviewId"], body["sessionId"]) == (interview_id, session_id)
    assert body["summary"] == {
        "overview": DEMO["review"]["summary"],
        "keyPoints": DEMO["review"]["keyPoints"],
    }
    # 채택한 것만, 저장된 순서로. 반려 · 미채택은 애초에 없다.
    assert [f["findingId"] for f in body["findings"]] == [PERF, DESIGN]
    # 역량 한 줄에 상태가 붙어 나간다 — 받는 쪽이 id 로 다시 맞추지 않게 (#239).
    assert [c["competencyId"] for c in body["competencies"]] == [
        c["competencyId"] for c in DEMO["prep"]["competencies"]
    ]
    assert [c["state"] for c in body["competencies"]] == [
        "CONFIRMED",
        "PARTIAL",
        "MISSING",
        "MISSING",
    ]
    assert all("name" in c and "required" in c for c in body["competencies"])


def test_the_memo_never_goes_to_the_ai(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """메모는 사람의 판단이고 리포트 맨 위 칸에 그대로 나간다."""
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)

    body = context_of(client, key, interview_id).json()

    assert "memo" not in body
    assert read(client, interview_id).status_code == 202


def test_there_is_no_context_before_the_button(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    interview_id, _ = reviewed(client, store)

    got = context_of(client, key, interview_id)

    assert got.status_code == 404
    assert got.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


def test_the_context_keeps_the_session_the_button_pinned(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """그 사이 세션이 하나 더 끝나도 이미 요청된 리포트의 근거는 흔들리지 않는다."""
    interview_id, session_id = reviewed(client, store)
    ask(client, interview_id)
    later = _ended_session(client, interview_id)
    assert later != session_id

    assert context_of(client, key, interview_id).json()["sessionId"] == session_id


# ── 내부 API: 저장 ──────────────────────────────────────


def test_a_result_for_an_older_request_is_refused(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    """면접관이 그 사이 다시 눌렀다. 폴러는 다음 조회에서 새 작업을 받는다."""
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)
    job = pending(client, key)
    age_report(store, interview_id, settings.report_timeout + timedelta(seconds=1))
    assert ask(client, interview_id).status_code == 202

    got = put_report(client, key, interview_id, written(job["requestedAt"]))

    assert got.status_code == 409
    assert got.json()["error"]["code"] == "REPORT_OUTDATED"
    assert read(client, interview_id).status_code == 202


def test_a_late_failure_does_not_erase_a_report_that_is_there(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    interview_id, _, job = finished(client, key, store)

    got = put_report(
        client,
        key,
        interview_id,
        written(job["requestedAt"], status="failed", overview=""),
    )

    assert got.status_code == 204
    assert read(client, interview_id).json()["status"] == "READY"


def test_there_is_nowhere_to_write_without_the_button(
    client: TestClient, key: str, store: InMemoryStore
) -> None:
    interview_id, _ = reviewed(client, store)

    got = put_report(client, key, interview_id, written(utcnow().isoformat()))

    assert got.status_code == 404
    assert got.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


@pytest.mark.parametrize("overview", ["", "   "])
def test_a_finished_report_cannot_be_blank(
    client: TestClient, key: str, store: InMemoryStore, overview: str
) -> None:
    """개요 없이 READY 로 넘어가면 FE 는 빈 리포트를 그린다. 그건 `empty` 로 말한다."""
    interview_id, _ = reviewed(client, store)
    ask(client, interview_id)
    job = pending(client, key)

    got = put_report(
        client, key, interview_id, written(job["requestedAt"], overview=overview)
    )

    assert got.status_code == 422
