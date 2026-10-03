"""LiveKit Webhook 수신 — 전사 타임라인 원점(t=0) 기록.

멘토 1차 리뷰에서 나온 항목이다. `startedAt`(「면접 시작」 버튼)은 안 누르면
비어 있어 마스터 클럭으로 쓸 수 없고, 세 파트가 공유할 원점이 따로 필요하다.
합의는 **t=0 = 가장 이른 사람 참가자의 입장 시각(ms)**이고, 그 시각을 아는 건
LiveKit 뿐이다. 자막 워커(Agent) · 녹화(Egress)는 사람보다 먼저 들어와도 원점이
아니다 (#86).

  현재 합의 : t=0 = 첫 참가자 접속 (이 Webhook)
  재검토    : 녹화 도입 시 Egress start 와의 오프셋 보정 때문에

AI 의 `startMs` 와 FE 의 `atSec` 은 단위만 ms·초로 두고 원점은 이 값 하나를 쓴다.

LiveKit 설정 쪽에 아래가 필요하다 (`infra/livekit/livekit.yaml`).

    webhook:
      api_key: <LIVEKIT_KEYS 의 키>
      urls:
        - http://backend:8000/api/v1/livekit/webhook
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, Request, status
from livekit.protocol.models import ParticipantInfo

from app.api.deps import MediaDep, StoreDep
from app.domain.models import session_id_from_room

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/livekit", tags=["LiveKit"])

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: 참가자가 방에 들어왔을 때 LiveKit 이 보내는 이벤트 이름.
PARTICIPANT_JOINED = "participant_joined"


@router.post(
    "/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="LiveKit Webhook 수신",
    # 클라이언트용 API 가 아니다. 공개 명세에 실으면 FE 가 부를 것처럼 읽힌다.
    include_in_schema=False,
)
async def receive_webhook(
    request: Request,
    store: StoreDep,
    media: MediaDep,
    authorization: str = Header(default=""),
) -> None:
    """가장 이른 사람 참가자의 입장 시각을 세션에 기록한다.

    **어떤 경우에도 4xx/5xx 를 돌려주지 않는다** — 모르는 방이든 관심 없는
    이벤트든 204 다. LiveKit 은 연결 오류 · 429 · 5xx 를 받으면 같은 이벤트를 최대
    4번 더 보낸다(1~30초 지수 백오프). 서명 검증 실패도 204 다 — 응답을 갈라 놓으면
    서명이 맞았는지를 밖에서 알 수 있게 된다.

    ⚠️ 응답은 한 가지여도 **로그는 갈라 놓는다.** 응답을 숨기는 목적은 밖에서
    구분하지 못하게 하는 것이지, 우리가 모르게 하는 게 아니다. 특히 서명 실패는
    BE 의 키 쌍(`LIVEKIT_API_KEY` · `LIVEKIT_API_SECRET`)이 LiveKit 의
    `LIVEKIT_KEYS` 와 어긋났다는 신호다. 그러면 **모든 이벤트가 버려지고 t=0 이
    계속 비어 있는데**, LiveKit 은 204 를 받아 성공으로 알고 재시도하지 않는다.
    로그가 유일한 단서다. (webhook 키가 `LIVEKIT_KEYS` 에 아예 없으면 LiveKit 이
    기동을 거부하므로 그쪽은 조용히 지나가지 않는다.)
    """
    body = (await request.body()).decode("utf-8")

    event = media.verify_webhook(body, authorization)
    if event is None:
        # 설정 오류일 가능성이 높아 warning 이다. 본문은 남기지 않는다 —
        # 우리가 발급한 서명이 아니므로 내용을 신뢰할 수 없다.
        logger.warning(
            "LiveKit webhook 서명 검증 실패. BE 의 LIVEKIT_API_KEY · "
            "LIVEKIT_API_SECRET 이 LiveKit 의 LIVEKIT_KEYS 와 같은 쌍인지 확인이 "
            "필요합니다."
        )
        return

    if event.event != PARTICIPANT_JOINED:
        # 우리가 구독하지 않은 이벤트. 정상이므로 debug 로만 남긴다.
        logger.debug("LiveKit webhook 무시: event=%s", event.event)
        return

    session_id = session_id_from_room(event.room.name)
    if session_id is None:
        # 로드 테스트 등 우리가 만들지 않은 방. 정상이다.
        logger.debug("LiveKit webhook 무시: 우리 방이 아님 room=%s", event.room.name)
        return

    participant = event.participant
    if participant.kind != ParticipantInfo.Kind.STANDARD:
        # 자막 워커 · 녹화는 정상적으로 들어오는 참가자다. debug 로만 남긴다.
        logger.debug("LiveKit webhook 무시: 사람이 아님 kind=%s", participant.kind)
        return

    joined_at = _joined_at(participant)
    if joined_at is None:
        logger.warning("LiveKit webhook: joinedAtMs 가 비어 원점을 정할 수 없음")
        return

    # 저장소가 한 문장으로 가장 이른 값만 남긴다 (#86). 두 참가자가 각각 이벤트를
    # 만들고 재전송 · 순서 뒤바뀜이 겹쳐도, 시작 · 종료 저장과 동시에 와도 서로를
    # 덮어쓰지 않는다. 세션이 없으면 False 라 따로 읽지 않는다.
    if store.mark_origin(session_id, joined_at):
        logger.info("전사 원점 기록 session_id=%s t0=%s", session_id, joined_at)


def _joined_at(participant: ParticipantInfo) -> datetime | None:
    """참가자가 방에 들어온 시각(ms)을 aware datetime 으로.

    이벤트를 만든 시각(`createdAt`)이 아니라 입장 시각이다. `createdAt` 은 초
    단위라 원점에서 최대 1초를 잃고, 재전송 · 큐 지연이 실리면 원점이 밀린다.
    원점은 #125 에서 실제 시각과 빼게 될 수 있어 ms 가 필요하다.
    """
    ms = participant.joined_at_ms
    if not ms:
        return None
    return _EPOCH + timedelta(milliseconds=ms)
