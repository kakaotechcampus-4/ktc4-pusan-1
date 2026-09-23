"""`/internal/v1` — Agent 가 붙는 경로.

세 가지를 본다. **인증**이 실제로 막는지, **프레임 계약**이 Agent 가 보내는 모양
그대로인지, 그리고 **ACK** 가 돌아오는지.

프레임 예시는 #76 본문의 것을 그대로 쓴다. 우리가 편한 모양으로 바꿔 쓰면 계약이
맞는지를 보는 의미가 없다.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.internal import transcripts
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
    ],
)
def test_broken_frame_is_nacked(
    client: TestClient, session_id: str, key: str, broken: dict
) -> None:
    """계약이 어긋나면 다시 보내지 말라고 답한다. 연결은 살려 둔다."""
    with client.websocket_connect(
        f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
    ) as ws:
        ws.send_json(broken)
        assert ws.receive_json() == {
            "type": "transcript.nack",
            "utteranceId": "utt_001",
            "reason": "SCHEMA",
        }
        # 발화 하나가 잘못됐다고 면접 전체의 전사를 끊을 이유가 없다.
        ws.send_json(UPSERT)
        assert ws.receive_json()["type"] == "transcript.ack"


def test_frame_without_id_closes_the_socket(
    client: TestClient, session_id: str, key: str
) -> None:
    """어느 발화를 버리라고 할 수가 없으면 NACK 이 의미가 없다."""
    nameless = {k: v for k, v in UPSERT.items() if k != "utteranceId"}
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
        ) as ws:
            ws.send_json(nameless)
            ws.receive_json()
    assert exc.value.code == 1008


def test_non_json_closes_the_socket(
    client: TestClient, session_id: str, key: str
) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/internal/v1/sessions/{session_id}/transcripts", headers=auth(key)
        ) as ws:
            ws.send_text("전사 아님")
            ws.receive_json()
    assert exc.value.code == 1003


def test_new_connection_replaces_the_old_one(
    client: TestClient, session_id: str, key: str
) -> None:
    """Agent 가 끊긴 걸 눈치 못 채고 새로 붙는 경우가 대부분이라 새 쪽이 최신이다.

    옛 소켓에서 블로킹으로 읽어 확인하면, 교체가 깨졌을 때 실패가 아니라 행이 된다.
    그래서 서버가 들고 있는 연결 표를 직접 본다.
    """
    path = f"/internal/v1/sessions/{session_id}/transcripts"
    with client.websocket_connect(path, headers=auth(key)):
        served_first = transcripts._live[session_id]
        with client.websocket_connect(path, headers=auth(key)) as second:
            # 왕복을 한 번 돌려 서버 핸들러가 교체 지점을 지났음을 보장한다.
            # 핸드셰이크만으로는 accept() 직후에서 멈춰 있을 수 있다.
            second.send_json(UPSERT)
            assert second.receive_json()["type"] == "transcript.ack"

            assert transcripts._live[session_id] is not served_first
            assert served_first.application_state is WebSocketState.DISCONNECTED


def test_connection_table_is_emptied_on_disconnect(
    client: TestClient, session_id: str, key: str
) -> None:
    """끊긴 세션이 표에 남으면 다음 연결이 이미 죽은 소켓을 끊으려 든다."""
    path = f"/internal/v1/sessions/{session_id}/transcripts"
    with client.websocket_connect(path, headers=auth(key)) as ws:
        ws.send_json(UPSERT)
        ws.receive_json()
        assert session_id in transcripts._live
    assert session_id not in transcripts._live


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
