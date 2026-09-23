"""Agent → BE 전사 수신 — `WS /internal/v1/sessions/{sessionId}/transcripts`.

Agent 가 확정 발화를 하나씩 보내고 우리가 하나씩 답한다 (#76 의 계약).

    →  {"type": "transcript.upsert", "utteranceId": "utt_001", ...}
    ←  {"type": "transcript.ack",    "utteranceId": "utt_001"}

**ACK 는 "받았다"가 아니라 "우리가 들고 있다"는 뜻이다.** Agent 는 ACK 를 받은
발화를 버퍼에서 지우고, 못 받은 것은 다음 연결에서 다시 보낸다. 그래서 저장에
실패했으면 ACK 를 보내면 안 된다.

받을 수 없는 프레임에는 **NACK** 으로 답한다.

    ←  {"type": "transcript.nack", "utteranceId": "utt_001", "reason": "SCHEMA"}

ACK 과 반대로 **다시 보내지 말라**는 뜻이다. 계약이 어긋난 프레임은 다시 보내도
같은 답이라, 끊어서 재전송을 유도하면 그 발화에서 영원히 막힌다. 연결은 살려 둔다 —
발화 하나가 잘못됐다고 면접 전체의 전사를 끊을 이유가 없다.

⚠️ **Agent 는 아직 NACK 을 처리하지 않는다** (`irya_ai.transcripts` 가 ACK 이 아닌
프레임을 전부 넘긴다). #76 에 요청해 두었다. 그 사이 NACK 이 실제로 나가면 그 발화가
버퍼에 남아 재연결이 반복되므로, 계약이 조금 갈라졌다고 NACK 이 쏟아지지 않도록
프레임 모델을 `extra="ignore"` 로 두었다.

⚠️ **아직 저장하지 않는다.** 전사 테이블이 없다 (#85). 지금은 검증하고 로그만
남긴 뒤 ACK 한다 — Agent 가 핸드셰이크·인증·프레임 모양·ACK 까지 한 번 통과시켜
보기 위한 단계다. #85 가 붙기 전까지 이 경로로 들어온 전사는 사라진다.

세션이 없으면 `accept()` 전에 끊는다. 붙은 뒤에 끊으면 Agent 가 연결 문제로 보고
같은 세션으로 계속 다시 붙는다.
"""

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.api.deps import StoreDep
from app.api.internal.deps import websocket_authorized
from app.api.internal.schemas import TranscriptAck, TranscriptNack, TranscriptUpsert

logger = logging.getLogger(__name__)

router = APIRouter()

#: 세션당 살아 있는 연결 하나. 새 연결이 오면 옛 것을 끊는다.
#:
#: Agent 가 끊긴 걸 눈치채지 못하고 새로 붙는 경우가 대부분이라 새 쪽이 최신이다.
#: 옛 연결을 살려 두면 같은 세션의 전사가 두 소켓으로 갈라져 순서가 섞인다.
#:
#: ⚠️ 프로세스 안에서만 맞는 규칙이다. uvicorn 워커를 둘 이상으로 늘리면 워커마다
#: 따로 세게 되므로, 그때는 이 표를 프로세스 밖으로 빼야 한다.
_live: dict[str, WebSocket] = {}


def _utterance_id(raw: Any) -> str | None:
    """검증에 실패한 프레임에서 NACK 에 실을 id 만 최선을 다해 꺼낸다.

    id 를 못 찾으면 어느 발화를 버리라고 할 수가 없다. 그때는 NACK 이 의미가 없어
    부르는 쪽에서 연결을 끊는다.
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("utteranceId")
    return value if isinstance(value, str) and value else None


async def _replace_live(session_id: str, websocket: WebSocket) -> None:
    previous = _live.get(session_id)
    if previous is not None:
        logger.info("전사 WebSocket 교체 session_id=%s — 옛 연결을 끊는다", session_id)
        try:
            await previous.close(code=status.WS_1012_SERVICE_RESTART)
        except RuntimeError:
            # 이미 끊긴 소켓이다. 표에서 지우는 것이 목적이라 그냥 넘어간다.
            pass
    _live[session_id] = websocket


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
    await _replace_live(sessionId, websocket)
    logger.info("전사 WebSocket 연결 session_id=%s", sessionId)
    received = 0
    refused = 0

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except (ValueError, KeyError):
                # JSON 도 아니다. 어느 발화인지 알 수 없어 NACK 을 못 보낸다.
                #
                # `KeyError` 는 바이너리 프레임이다 — Starlette 의 `receive_json`
                # 이 텍스트 키를 찾다 터진다. 1003 은 Agent 가 일시 장애로 보고
                # 다시 붙는 코드라, 텍스트로 고쳐 보내면 이어진다.
                logger.error("전사 프레임을 읽을 수 없음 session_id=%s", sessionId)
                await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return

            try:
                frame = TranscriptUpsert.model_validate(raw)
            except ValidationError as exc:
                # 본문은 남기지 않는다. 면접 발화가 그대로 로그에 쌓인다.
                utterance_id = _utterance_id(raw)
                logger.error(
                    "전사 프레임 검증 실패 session_id=%s utterance_id=%s errors=%d",
                    sessionId,
                    utterance_id,
                    exc.error_count(),
                )
                if utterance_id is None:
                    # 어느 발화를 버리라고 할 수가 없어 NACK 이 의미가 없다.
                    #
                    # 1008 은 Agent 에게 "다시 오지 마라"로 읽힌다 — 채널을 영구
                    # 폐기하고 그 면접의 남은 전사를 전부 버린다. 자기 발화에 id 를
                    # 못 붙이는 쪽은 우리 Agent 가 아니므로 그게 맞다.
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                refused += 1
                nack = TranscriptNack(utterance_id=utterance_id, reason="SCHEMA")
                await websocket.send_json(nack.model_dump(by_alias=True))
                continue

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
            "전사 WebSocket 종료 session_id=%s 받은 발화=%d 거절=%d",
            sessionId,
            received,
            refused,
        )
    finally:
        # 교체된 뒤에 옛 연결이 정리될 수 있다. 내가 아직 주인일 때만 지운다.
        if _live.get(sessionId) is websocket:
            del _live[sessionId]
