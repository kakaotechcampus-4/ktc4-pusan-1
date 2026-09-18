"""Webhook 서명 검증 — 대역이 아니라 실제 LiveKit SDK 로.

`tests/test_webhooks.py` 는 라우터의 분기를 본다. 여기서는 그 앞단,
`LiveKitGateway.verify_webhook` 이 LiveKit 이 실제로 보내는 형식을 받아내는지 본다.
대역으로는 서명 로직이 도는지 알 수 없다.
"""

import base64
import hashlib
import json

import pytest
from livekit import api

from app.services.media import LiveKitGateway

KEY = "testkey"
SECRET = "testsecret_local_only_0123456789abcdef"

gateway = LiveKitGateway(url="", key=KEY, secret=SECRET, max_participants=2)


def _body(room: str = "interview_ses_abc", event: str = "participant_joined") -> str:
    return json.dumps(
        {
            "event": event,
            "room": {"name": room},
            "createdAt": "1789000000",
            "id": "ev_1",
        }
    )


def _sign(body: str, *, key: str = KEY, secret: str = SECRET) -> str:
    """LiveKit 이 Authorization 헤더에 싣는 것과 같은 토큰을 만든다.

    본문의 SHA-256 을 base64 로 담은 JWT 다. 본문이 바뀌면 해시가 어긋난다.
    """
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return api.AccessToken(key, secret).with_sha256(digest).to_jwt()


def test_valid_signature_is_parsed():
    body = _body()

    event = gateway.verify_webhook(body, _sign(body))

    assert event is not None
    assert event.event == "participant_joined"
    assert event.room.name == "interview_ses_abc"


def test_tampered_body_is_rejected():
    """서명은 맞지만 본문을 바꾼 경우. 해시가 안 맞아야 한다."""
    signed_for = _body(room="interview_ses_abc")
    tampered = _body(room="interview_ses_victim")

    assert gateway.verify_webhook(tampered, _sign(signed_for)) is None


def test_wrong_secret_is_rejected():
    body = _body()
    other = _sign(body, secret="someone_elses_secret_0123456789abcdef")

    assert gateway.verify_webhook(body, other) is None


@pytest.mark.parametrize("header", ["", "not-a-jwt", "Bearer x.y.z"])
def test_malformed_headers_are_rejected(header: str):
    assert gateway.verify_webhook(_body(), header) is None
