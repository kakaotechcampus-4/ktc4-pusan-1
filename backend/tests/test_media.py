"""입장 토큰 권한.

VideoGrants 는 can_publish / can_subscribe / can_publish_data 의 기본값이 True 다.
안 끄면 의도보다 넓은 권한이 나가므로 값을 직접 못 박아 둔다.
"""

import pytest

from app.domain.models import Role
from app.services.media import _grants_for


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
