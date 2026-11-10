"""발표 데모용 발화 주입 — `POST /sessions/{sessionId}/demo/utterance`.

제품 기능이 아니라 무대용 경로다. 그래서 보는 것이 둘이다. 하나는 켜졌을 때
Agent 가 듣는 토픽으로 제대로 나가는지, 다른 하나는 **꺼졌을 때·남의 세션일 때
아무것도 나가지 않는지**다. 후자가 더 중요하다 — 켜 둔 채로 내보내면 남의 면접
전사에 아무도 말하지 않은 문장을 넣을 수 있는 경로가 된다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.sessions import DEMO_TOPIC
from app.core.config import settings
from app.domain.store import InMemoryStore
from tests.conftest import ANON, FakeMedia

ANSWER = "읽기 쪽 커넥션 풀이 먼저 말라서 초당 2만 건에서 응답이 밀렸습니다."


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch, session_id: str) -> None:
    """이 세션에만 데모 주입을 켠다. 기본값은 꺼짐이고, 켜는 테스트만 이걸 쓴다."""
    monkeypatch.setattr(settings, "demo_injection_enabled", True)
    monkeypatch.setattr(settings, "demo_injection_sessions", session_id)


def inject(client: TestClient, session_id: str, content: str = ANSWER, **kwargs):
    return client.post(
        f"/api/v1/sessions/{session_id}/demo/utterance",
        json={"content": content},
        **kwargs,
    )


def started(client: TestClient, session_id: str) -> str:
    """면접을 진행 중 상태로 만든다. 주입은 그때만 된다."""
    assert client.post(f"/api/v1/sessions/{session_id}/start").status_code == 200
    return session_id


# ── 켜져 있을 때 ────────────────────────────────────────


def test_the_answer_goes_out_on_the_agent_topic(
    client: TestClient,
    session_id: str,
    media: FakeMedia,
    store: InMemoryStore,
    demo_on: None,
) -> None:
    started(client, session_id)

    assert inject(client, session_id).status_code == 204

    [(room, data, topic, to)] = media.sent
    session = store.get_session(session_id)
    assert session is not None
    assert room == session.room_name
    assert topic == DEMO_TOPIC
    # Agent 는 숨어 있어서 identity 를 미리 알 수 없다. 사람 쪽은 이 토픽을 듣지 않는다.
    assert to == []
    packet = json.loads(data)
    assert packet == {"type": "demo.utterance", "content": ANSWER}


def test_korean_is_not_escaped_in_the_packet(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    """Agent 가 UTF-8 로 읽는다. `\\uXXXX` 로 보내면 길이 상한 판정이 달라진다."""
    started(client, session_id)

    inject(client, session_id)

    [(_, data, _, _)] = media.sent
    assert ANSWER.encode() in data


def test_each_press_sends_one_packet(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    started(client, session_id)

    inject(client, session_id, "첫 번째 답변입니다. 길이를 맞추기 위해 더 적습니다.")
    inject(client, session_id, "두 번째 답변입니다. 길이를 맞추기 위해 더 적습니다.")

    assert len(media.sent) == 2


# ── 막혀야 하는 것 ───────────────────────────────────────


def test_disabled_gives_404_and_sends_nothing(
    client: TestClient, session_id: str, media: FakeMedia
) -> None:
    """기본값은 꺼짐이다. 404 를 주고 아무것도 보내지 않는다.

    「없는 경로와 완전히 구분되지 않는다」고까지는 말하지 않는다 — 로그인하지 않은
    요청은 404 가 아니라 401 을 먼저 받고, 본문 문구도 FastAPI 기본값과 다르다.
    경로의 존재를 숨기는 것이 목적이 아니라 제품 API 에서 빼 두는 것이 목적이다.
    """
    started(client, session_id)

    response = inject(client, session_id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert media.sent == []


def test_a_session_that_has_not_started_is_refused(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    assert inject(client, session_id).status_code == 409
    assert media.sent == []


def test_an_ended_session_is_refused(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    started(client, session_id)
    client.post(f"/api/v1/sessions/{session_id}/end")
    media.sent.clear()

    assert inject(client, session_id).status_code == 409
    assert media.sent == []


def test_someone_elses_session_is_not_found(
    client: TestClient,
    session_id: str,
    media: FakeMedia,
    other: dict[str, str],
    demo_on: None,
) -> None:
    """남의 면접에 발화를 넣을 수 있으면 안 된다. 없는 것과 같은 404 다."""
    started(client, session_id)
    media.sent.clear()

    response = inject(client, session_id, headers=other)

    assert response.status_code == 404
    assert media.sent == []


def test_an_anonymous_request_is_refused(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    started(client, session_id)
    media.sent.clear()

    assert inject(client, session_id, headers=ANON).status_code == 401
    assert media.sent == []


def test_an_unknown_session_is_not_found(
    client: TestClient, media: FakeMedia, demo_on: None
) -> None:
    assert inject(client, "ses_nope").status_code == 404
    assert media.sent == []


@pytest.mark.parametrize(
    "content",
    ["", "   ", "가" * 2_001],
    ids=["empty", "blank", "too-long"],
)
def test_content_outside_the_limits_is_refused(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None, content: str
) -> None:
    started(client, session_id)

    assert inject(client, session_id, content).status_code == 422
    assert media.sent == []


def test_the_route_is_not_in_the_public_spec(client: TestClient) -> None:
    """제품 API 가 아니다. 명세에 실으면 FE 가 부를 것처럼 읽힌다."""
    paths = client.get("/openapi.json").json()["paths"]

    assert not any("demo" in path for path in paths)


# ── 다른 세션은 열리지 않는다 ─────────────────────────────


def test_a_session_not_on_the_list_is_not_found(
    client: TestClient,
    session_id: str,
    media: FakeMedia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """리뷰가 잡은 것. 플래그만 켜면 그 서버의 모든 면접이 열려 있었다.

    데모를 켜 둔 동안 같은 서버의 다른 면접관이 화살표를 눌러도, 그 세션이 목록에
    없으면 실제 지원자의 전사에 아무것도 들어가지 않는다.
    """
    monkeypatch.setattr(settings, "demo_injection_enabled", True)
    monkeypatch.setattr(settings, "demo_injection_sessions", "ses_someone_elses_demo")
    started(client, session_id)

    assert inject(client, session_id).status_code == 404
    assert media.sent == []


def test_an_empty_list_opens_no_session(
    client: TestClient,
    session_id: str,
    media: FakeMedia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패는 닫히는 쪽으로. 세션을 적는 걸 잊어도 전체가 열리지 않는다."""
    monkeypatch.setattr(settings, "demo_injection_enabled", True)
    monkeypatch.setattr(settings, "demo_injection_sessions", "")
    started(client, session_id)

    assert inject(client, session_id).status_code == 404
    assert media.sent == []


def test_the_list_alone_does_not_arm_it(
    client: TestClient,
    session_id: str,
    media: FakeMedia,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """플래그가 꺼져 있으면 목록에 올라 있어도 안 된다. 둘 다 있어야 한다."""
    monkeypatch.setattr(settings, "demo_injection_enabled", False)
    monkeypatch.setattr(settings, "demo_injection_sessions", session_id)
    started(client, session_id)

    assert inject(client, session_id).status_code == 404
    assert media.sent == []


#: BE·AI·브라우저가 같게 읽어야 하는 입력들. 세 쪽에 같은 목록을 둔다 —
#: 한쪽만 고치면 「BE 는 허용하는데 Agent 는 핸들러를 안 붙인다」가 되고, 그때
#: BE 는 204 를 주면서 아무 일도 일어나지 않는다.
SESSION_LIST_CASES = [
    ("", []),
    ("   ", []),
    (",,", []),
    ("ses_a", ["ses_a"]),
    (" ses_a , ses_b ", ["ses_a", "ses_b"]),
    # 브라우저 쪽은 JSON 배열을 받는다. 서버 env 에 그 모양을 붙여넣는 실수가 나므로
    # 양쪽 모양을 다 받는다 — 안 받으면 조용히 404 만 나고 이유가 안 보인다.
    ('["ses_a","ses_b"]', ["ses_a", "ses_b"]),
    ('["ses_a"]', ["ses_a"]),
    ("['ses_a']", ["ses_a"]),
    ('"ses_a"', ["ses_a"]),
    # 와일드카드는 없다. 그런 이름의 세션 id 로 읽히고 아무것과도 안 맞는다.
    ("*", ["*"]),
    ("all", ["all"]),
    # 구분자를 잘못 적으면 쓸모없는 id 한 개 — 닫히는 쪽이다.
    ("ses_a;ses_b", ["ses_a;ses_b"]),
]


@pytest.mark.parametrize(("raw", "expected"), SESSION_LIST_CASES)
def test_the_session_list_is_read_like_the_agent_reads_it(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    """BE 와 Agent 가 같은 문자열을 같게 읽어야 한다.

    AI 쪽 `irya_ai.demo_injection.allowed_sessions` 와 **같은 목록**으로 시험한다
    (`ai/tests/test_demo_injection.py` 의 `SESSION_LIST_CASES`). 둘이 갈리면 BE 는
    허용하는데 Agent 는 핸들러를 안 붙이고, BE 가 204 를 주면서 아무 일도 일어나지
    않는다 — 무대에서 가장 알아차리기 어려운 고장이다.
    """
    monkeypatch.setattr(settings, "demo_injection_sessions", raw)

    assert settings.demo_injection_session_ids == frozenset(expected)


# ── 전달 실패 ────────────────────────────────────────────


def test_a_delivery_failure_is_not_a_404(
    client: TestClient, session_id: str, media: FakeMedia, demo_on: None
) -> None:
    """무대에서 「안 켰다」와 「LiveKit 이 안 받는다」를 구분할 수 있어야 한다."""
    started(client, session_id)
    media.send_error = RuntimeError("livekit down")

    response = inject(client, session_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
