"""Agent → BE 전사 수신 — `WS /internal/v1/sessions/{sessionId}/transcripts`.

Agent 가 확정 발화를 하나씩 보내고 우리가 하나씩 답한다 (#76 의 계약).

    →  {"type": "transcript.upsert", "utteranceId": "utt_001", ...}
    ←  {"type": "transcript.ack",    "utteranceId": "utt_001"}

**ACK 는 "받았다"가 아니라 "우리가 들고 있다"는 뜻이다.** Agent 는 ACK 를 받은
발화를 버퍼에서 지우고, 못 받은 것은 다음 연결에서 다시 보낸다. 그래서 저장에
실패했으면 ACK 를 보내면 안 된다.

⚠️ **아직 저장하지 않는다.** 전사 테이블이 없다 (#85). 지금은 검증하고 로그만
남긴 뒤 ACK 한다 — Agent 가 핸드셰이크·인증·프레임 모양·ACK 까지 한 번 통과시켜
보기 위한 단계다. #85 가 붙기 전까지 이 경로로 들어온 전사는 사라진다.

세션이 없으면 `accept()` 전에 끊는다. 붙은 뒤에 끊으면 Agent 가 연결 문제로 보고
같은 세션으로 계속 다시 붙는다.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.api.deps import StoreDep
from app.api.internal.deps import websocket_authorized
from app.api.internal.schemas import TranscriptAck, TranscriptUpsert

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/sessions/{sessionId}/transcripts")
async def receive_transcripts(
    websocket: WebSocket, sessionId: str, store: StoreDep
) -> None:
    if not await websocket_authorized(websocket):
        return

    if store.get_session(sessionId) is None:
        # 우리가 만들지 않은 세션이다. 나중에 생길 값이 아니므로 다시 붙어도
        # 같은 답이고, 그래서 핸드셰이크 단계에서 끊는다.
        logger.warning("전사 WebSocket: 세션을 찾을 수 없음 session_id=%s", sessionId)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info("전사 WebSocket 연결 session_id=%s", sessionId)
    received = 0

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                frame = TranscriptUpsert.model_validate(raw)
            except ValidationError as exc:
                # 계약이 어긋났다는 뜻이라 다시 보내도 같은 결과다. 지금 계약에는
                # 프레임 하나를 거절하는 수단(NACK)이 없어 연결을 끊는 것 말고는
                # 알릴 방법이 없다 — #76 에 NACK 을 묻고 있다.
                # 본문은 남기지 않는다. 면접 발화가 그대로 로그에 쌓인다.
                logger.error(
                    "전사 프레임 검증 실패 session_id=%s errors=%s",
                    sessionId,
                    exc.error_count(),
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            # TODO(#85): (session_id, utterance_id) 로 upsert 한다.
            received += 1
            logger.info(
                "전사 수신 session_id=%s utterance_id=%s speaker=%s %d-%dms",
                sessionId,
                frame.utterance_id,
                frame.speaker.value,
                frame.started_at_ms,
                frame.ended_at_ms,
            )

            ack = TranscriptAck(utterance_id=frame.utterance_id)
            await websocket.send_json(ack.model_dump(by_alias=True))
    except WebSocketDisconnect:
        logger.info(
            "전사 WebSocket 종료 session_id=%s 받은 발화=%d", sessionId, received
        )
