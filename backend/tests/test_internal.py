"""`/internal/v1` — Agent 가 붙는 경로.

세 가지를 본다. **인증**이 실제로 막는지, **프레임 계약**이 Agent 가 보내는 모양
그대로인지, 그리고 **ACK** 가 돌아오는지.

프레임 예시는 #76 본문의 것을 그대로 쓴다. 우리가 편한 모양으로 바꿔 쓰면 계약이
맞는지를 보는 의미가 없다.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings

UPSERT = {
    "type": "transcript.upsert",
    "utteranceId": "utt_001",
    "participantId": "CANDIDATE",
    "speaker": "CANDIDATE",
    "text": "안녕하세요, 잘 부탁드립니다.",
    "startedAtMs": 15200,
    "endedAtMs": 23800,
}

SUGGESTION = {
    "suggestionId": "sug_001",
    "type": "FOLLOW_UP",
    "content": "그 경험에서 가장 어려웠던 부분은 무엇이었나요?",
    "evidenceUtteranceIds": ["utt_001"],
}


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    """키가 설정된 상태. 기본값은 빈 문자열이라 검사를 건너뛴다."""
    monkeypatch.setattr(settings, "internal_api_key", "test-secret")
    return "test-secret"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 인증 ────────────────────────────────────────────────


def test_suggestion_without_key_is_unauthorized(
    client: TestClient, session_id: str, key: str
) -> None:
    got = client.post(
        f"/internal/v1/sessions/{session_id}/suggestions", json=SUGGESTION
    )
    assert got.status_code == 401


def test_suggestion_with_wrong_key_is_unauthorized(
    client: TestClient, session_id: str, key: str
) -> None:
    got = client.post(
        f"/internal/v1/sessions/{session_id}/suggestions",
        json=SUGGESTION,
        headers=auth("wrong"),
    )
    assert got.status_code == 401


def test_key_unset_skips_the_check(client: TestClient, session_id: str) -> None:
    """양쪽이 비어 있는 로컬에서 자격증명을 지어내지 않고 붙는다."""
    assert settings.internal_api_key == ""
    got = client.post(
        f"/internal/v1/sessions/{session_id}/suggestions", json=SUGGESTION
    )
    assert got.status_code == 204


def test_transcript_socket_rejects_wrong_key(
    client: TestClient, session_id: str, key: str
) -> None:
    """WebSocket 은 101 로 올라가기 전에 끊어야 Agent 가 재시도하지 않는다."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/internal/v1/sessions/{session_id}/transcripts", headers=auth("wrong")
        ):
            pass
    assert exc.value.code == 1008


# ── 전사 ────────────────────────────────────────────────


def test_transcript_upsert_is_acked(
    client: TestClient, session_id: str, key: str
) -> None:
    with client.websocket_connect(
        f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
    ) as ws:
        ws.send_json(UPSERT)
        assert ws.receive_json() == {
            "type": "transcript.ack",
            "utteranceId": "utt_001",
        }


def test_resent_frame_is_acked_again(
    client: TestClient, session_id: str, key: str
) -> None:
    """ACK 을 못 받은 발화는 다시 온다. 두 번째도 똑같이 받아야 한다."""
    with client.websocket_connect(
        f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
    ) as ws:
        ws.send_json(UPSERT)
        first = ws.receive_json()
        ws.send_json(UPSERT)
        assert ws.receive_json() == first


def test_unknown_session_is_refused_before_accept(client: TestClient, key: str) -> None:
    """나중에 생길 값이 아니므로 핸드셰이크에서 끊는다."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/internal/v1/sessions/ses_없는것/transcripts", headers=auth(key)
        ):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize(
    "broken",
    [
        {**UPSERT, "endedAtMs": 1000},  # 끝이 시작보다 앞
        {**UPSERT, "text": ""},  # 빈 발화
        {**UPSERT, "speaker": "OBSERVER"},  # 모르는 화자
        {**UPSERT, "extra": "x"},  # 계약에 없는 필드
        {k: v for k, v in UPSERT.items() if k != "utteranceId"},  # 빠진 필드
    ],
)
def test_broken_frame_closes_the_socket(
    client: TestClient, session_id: str, key: str, broken: dict
) -> None:
    """계약이 어긋나면 다시 보내도 같은 결과다. 조용히 삼키지 않는다."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
        ) as ws:
            ws.send_json(broken)
            ws.receive_json()
    assert exc.value.code == 1008


# ── 꼬리질문 ────────────────────────────────────────────


def test_suggestion_is_accepted(client: TestClient, session_id: str, key: str) -> None:
    got = client.post(
        f"/internal/v1/sessions/{session_id}/suggestions",
        json=SUGGESTION,
        headers=auth(key),
    )
    assert got.status_code == 204


def test_suggestion_without_evidence_is_rejected(
    client: TestClient, session_id: str, key: str
) -> None:
    """근거를 못 대는 제안은 만들지 않는 것이 AI 쪽 원칙이다. 경계에서도 막는다."""
    got = client.post(
        f"/internal/v1/sessions/{session_id}/suggestions",
        json={**SUGGESTION, "evidenceUtteranceIds": []},
        headers=auth(key),
    )
    assert got.status_code == 422


def test_suggestion_for_unknown_session_is_404(client: TestClient, key: str) -> None:
    got = client.post(
        "/internal/v1/sessions/ses_없는것/suggestions",
        json=SUGGESTION,
        headers=auth(key),
    )
    assert got.status_code == 404


# ── 공개 명세 ───────────────────────────────────────────


def test_internal_routes_are_not_in_the_public_schema(client: TestClient) -> None:
    """FE 가 부를 것처럼 읽히면 안 된다."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/internal")]
