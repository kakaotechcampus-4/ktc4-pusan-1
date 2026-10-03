"""입장 토큰 권한과 정원 계산.

VideoGrants 는 can_publish / can_subscribe / can_publish_data 의 기본값이 True 다.
안 끄면 의도보다 넓은 권한이 나가므로 값을 직접 못 박아 둔다.

정원 쪽은 **LiveKit 과 같은 규칙으로 세는지**를 본다. 둘이 어긋나면 한쪽은
자리가 있다고 보고 다른 쪽은 거절한다.
"""

import asyncio

import pytest
from livekit import api

from app.domain.models import Role
from app.services.media import LiveKitGateway, _counts_toward_capacity, _grants_for


@pytest.mark.parametrize("role", list(Role))
def test_token_grants_are_minimal_for_every_role(role: Role):
    grants = _grants_for("ses_test", role)

    assert grants.room == "ses_test"
    assert grants.room_join is True
    assert grants.can_publish is True
    assert grants.can_subscribe is True

    # 방 종료·강퇴·녹화는 BE 가 RoomService 로 한다. 클라이언트에 실을 이유가 없다.
    assert not grants.room_admin
    assert not grants.room_record
    # SDK 기본값이 True 라 명시적으로 꺼야 한다.
    assert not grants.can_publish_data


def test_grants_do_not_differ_by_role():
    """role 은 권한이 아니라 FE 화면 분기용이다. 달라지는 순간 이 테스트가 깨진다."""
    interviewer = _grants_for("ses_test", Role.INTERVIEWER)
    candidate = _grants_for("ses_test", Role.CANDIDATE)

    assert interviewer == candidate


# ── 정원 계산 ────────────────────────────────────────────────

Kind = api.ParticipantInfo.Kind


def participant(kind: "Kind.ValueType") -> api.ParticipantInfo:
    # 스텁이 `kind: ParticipantInfo.Kind` 로 선언해 뒀는데 `Kind.AGENT` 의 타입은
    # `ValueType`(int) 이다. 생성 SDK 안에서 어긋나 있는 부분이라 여기서 끈다.
    info = api.ParticipantInfo(identity="p")
    info.kind = kind  # pyright: ignore[reportAttributeAccessIssue]
    return info


def test_agents_do_not_take_a_seat():
    """**#84 워커가 들어오면 터지던 것.**

    `ListParticipants` 는 Agent 도 돌려준다. 전부 세면 정원 2 인 방에 워커가
    들어온 뒤 두 번째 사람이 우리 사전 검사에서 ROOM_FULL 을 받는다 — LiveKit
    은 자리를 내주는데 그 앞에서 막는 것이다.
    """
    assert not _counts_toward_capacity(participant(Kind.AGENT))


def test_egress_does_not_take_a_seat():
    """녹화도 LiveKit 의 IsDependent() 에서 빠진다."""
    assert not _counts_toward_capacity(participant(Kind.EGRESS))


@pytest.mark.parametrize("kind", [Kind.STANDARD, Kind.SIP, Kind.INGRESS])
def test_everything_else_takes_a_seat(kind: "Kind.ValueType"):
    """**STANDARD 만 세면 안 된다.**

    LiveKit 의 `IsDependent()` 는 AGENT·EGRESS 만 뺀다. SIP·INGRESS 는 사람처럼
    센다. 여기서 더 많이 빼면 우리는 자리가 있다고 보는데 LiveKit 이 입장을
    거절해서, 지금과 반대 방향으로 같은 버그가 난다.
    """
    assert _counts_toward_capacity(participant(kind))


def test_two_people_and_an_agent_count_as_two():
    people = [participant(Kind.STANDARD), participant(Kind.STANDARD)]
    room = [*people, participant(Kind.AGENT)]

    assert sum(1 for p in room if _counts_toward_capacity(p)) == 2


def test_participant_count_does_not_count_the_agent(monkeypatch: pytest.MonkeyPatch):
    """**실제로 고치는 자리.** 위 규칙을 `participant_count` 가 정말 쓰는지 본다.

    규칙만 테스트하면 세는 쪽이 `len(participants)` 로 되돌아가도 안 잡힌다.
    """

    class FakeRoomService:
        async def list_participants(self, _request: object):
            return api.ListParticipantsResponse(
                participants=[
                    participant(Kind.STANDARD),
                    participant(Kind.AGENT),
                ]
            )

    class FakeClient:
        room = FakeRoomService()

        async def aclose(self) -> None:
            return None

    gateway = LiveKitGateway("http://livekit", "key", "secret", max_participants=2)
    monkeypatch.setattr(gateway, "_client", lambda: FakeClient())

    counted = asyncio.run(gateway.participant_count("interview_ses_1"))

    # 사람 하나 + Agent 하나 = 정원상 하나. 그래서 두 번째 사람이 들어올 수 있다.
    assert counted == 1
