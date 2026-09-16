"""LiveKit Webhook 수신 — 전사 타임라인 원점(t=0) 기록.

멘토 1차 리뷰에서 나온 항목이다. `startedAt`(「면접 시작」 버튼)은 안 누르면
비어 있어 마스터 클럭으로 쓸 수 없고, 세 파트가 공유할 원점이 따로 필요하다.
합의는 **t=0 = 첫 참가자 접속 시각**이고, 그 시각을 아는 건 LiveKit 뿐이다.

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
from datetime import UTC, datetime

from fastapi import APIRouter, Header, Request, status

from app.api.deps import MediaDep, StoreDep
from app.domain.models import session_id_from_room
from app.services.media import WebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/livekit", tags=["LiveKit"])

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
    """첫 참가자 입장 시각을 세션에 기록한다.

    LiveKit 은 실패한 Webhook 을 재시도한다. 그래서 **어떤 경우에도 4xx/5xx 를
    돌려주지 않는다** — 모르는 방이든 관심 없는 이벤트든 204 다. 에러를 주면
    LiveKit 이 같은 이벤트를 계속 다시 보낸다. 서명 검증 실패도 204 다 —
    응답을 갈라 놓으면 서명이 맞았는지를 밖에서 알 수 있게 된다.

    ⚠️ 응답은 한 가지여도 **로그는 갈라 놓는다.** 응답을 숨기는 목적은 밖에서
    구분하지 못하게 하는 것이지, 우리가 모르게 하는 게 아니다. 특히 서명 실패는
    설정이 어긋났다는 신호인데 — `livekit.yaml` 의 `webhook.api_key` 가
    `LIVEKIT_KEYS` 와 다르면 **모든 이벤트가 조용히 버려지고 t=0 이 영원히 비어
    있다** — 로그가 없으면 원인을 찾을 단서가 없다. LiveKit 쪽도 204 를 받아
    성공으로 알고 재시도하지 않는다.
    """
    body = (await request.body()).decode("utf-8")

    event = media.verify_webhook(body, authorization)
    if event is None:
        # 설정 오류일 가능성이 높아 warning 이다. 본문은 남기지 않는다 —
        # 우리가 발급한 서명이 아니므로 내용을 신뢰할 수 없다.
        logger.warning(
            "LiveKit webhook 서명 검증 실패. livekit.yaml 의 webhook.api_key 가 "
            "LIVEKIT_KEYS 의 키와 같은지 확인이 필요합니다."
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

    session = store.get_session(session_id)
    if session is None:
        # 방 이름은 우리 규칙인데 세션이 없다. 저장소가 비었거나(인메모리 재시작)
        # 세션이 지워진 경우라 짚어볼 값이 있다.
        logger.warning("LiveKit webhook: 세션을 찾을 수 없음 session_id=%s", session_id)
        return

    joined_at = _event_time(event)
    if joined_at is None:
        logger.warning("LiveKit webhook: createdAt 이 비어 원점을 정할 수 없음")
        return

    # mark_origin 이 처음 한 번만 참을 준다. 두 참가자가 각각 이벤트를 만들고
    # 재전송까지 겹치므로, 저장도 값이 실제로 바뀐 경우에만 한다.
    if session.mark_origin(joined_at):
        store.save_session(session)
        logger.info("전사 원점 기록 session_id=%s t0=%s", session_id, joined_at)


def _event_time(event: WebhookEvent) -> datetime | None:
    """이벤트 생성 시각(epoch 초)을 aware datetime 으로.

    수신 시각이 아니라 생성 시각을 쓴다 — 재전송이나 큐 지연이 그대로
    원점에 실리면 전사 타임스탬프가 통째로 밀린다.
    """
    if not event.created_at:
        return None
    return datetime.fromtimestamp(event.created_at, tz=UTC)
