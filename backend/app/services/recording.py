"""녹화 합치기와 재생 URL (#112).

  track_published   지원자 영상 · 두 사람 음성마다 TrackEgress 를 건다 (webhooks.py)
  Egress            트랙마다 S3 `rec/{session_id}/` 에 파일 하나 (영상 .webm, 음성 .ogg)
  egress_ended      `kick()` — 합칠 차례인지 지금 본다
  5분마다           놓친 것을 다시 본다 (webhook 유실 · BE 재시작 · 실패)
  재생              합친 파일의 10분짜리 서명 URL (sessions.py)

합치기는 BE 안에서 한 번에 하나씩, 낮은 우선순위로 돈다. BE 는 프로세스 하나라
(uvicorn 워커 1) 같은 세션을 두 번 합치지 않는다. 영상은 다시 인코딩하지 않고
음성 둘만 섞는다 — 테크스펙 「녹화」.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from boto3.session import Session as Boto3Session
from botocore.config import Config
from livekit import api

from app.core.config import settings
from app.domain.models import Recording, Session, SummaryStatus, utcnow
from app.domain.store import Store
from app.services.media import MediaGateway

logger = logging.getLogger(__name__)

REGION = "ap-northeast-2"
#: 놓친 것을 다시 보는 간격.
SWEEP_SECONDS = 300
#: 면접이 끝나고 이만큼 지나도 못 합쳤으면 FAILED 로 둔다. LiveKit 이 녹화 정보를
#: 24시간 들고 있으니 그 안이다.
GIVE_UP = timedelta(hours=1)
URL_TTL = timedelta(minutes=10)

_wake = asyncio.Event()


@cache
def _s3() -> Any:
    """처음 쓸 때 만든다. import 만으로 자격증명을 찾으러 가지 않게 하려는 것이다.

    세션을 따로 만든다 — 기본 세션은 여러 스레드가 처음에 동시에 쓰면 깨진다.
    """
    return Boto3Session().client(
        "s3", region_name=REGION, config=Config(signature_version="s3v4")
    )


def presign(key: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.recording_bucket, "Key": key},
        ExpiresIn=int(URL_TTL.total_seconds()),
    )


def kick() -> None:
    """합칠 차례인지 지금 보게 한다."""
    _wake.set()


async def run(store: Store, media: MediaGateway) -> None:
    """lifespan 이 띄우고 끈다. 깨우거나 5분이 지나면 합칠 것을 전부 본다.

    기동하자마자 한 번 돈다 — 재시작 사이에 끝난 면접을 바로 집는다.
    """
    while True:
        _wake.clear()
        try:
            await merge_pending(store, media)
        except Exception:
            logger.exception("녹화 합치기 목록을 못 읽었다")
        try:
            await asyncio.wait_for(_wake.wait(), SWEEP_SECONDS)
        except TimeoutError:
            pass


async def merge_pending(store: Store, media: MediaGateway) -> None:
    for session_id in await asyncio.to_thread(store.pending_recordings):
        session = await asyncio.to_thread(store.get_session, session_id)
        if session is None:
            continue
        try:
            recording = await _merge(session, media)
        except Exception:
            logger.exception("녹화 합치기 실패 session_id=%s", session_id)
            recording = None
        if recording is None:
            assert session.ended_at is not None  # 끝난 세션만 온다
            if utcnow() - session.ended_at < GIVE_UP:
                continue  # 다음에 다시 본다
            logger.warning("녹화를 못 합쳐 FAILED 로 둔다 session_id=%s", session_id)
            recording = _failed(session_id)
        await asyncio.to_thread(store.save_recording, recording)


@dataclass(frozen=True)
class Track:
    key: str
    #: 파일의 0초가 가리키는 시각(ns). egress 가 파이프라인을 시작한 시각이다.
    started_ns: int
    duration_ns: int

    @property
    def is_audio(self) -> bool:
        # egress 가 코덱에 맞춰 붙인 확장자다. Opus 는 .ogg, VP8 은 .webm.
        return self.key.endswith(".ogg")


def pick(infos: list[api.EgressInfo]) -> tuple[list[Track], list[Track]]:
    """합칠 트랙 — (영상, 음성). 둘 다 조각 전부를 시작 순서대로.

    오래 끊겼다 붙거나 새로고침하면 트랙이 새로 생겨 조각이 여럿이 된다. 몇 초
    끊기는 정도는 같은 트랙이 이어진다.
    """
    tracks = sorted(
        (
            Track(f.filename, f.started_at, f.duration)
            for info in infos
            if info.status == api.EgressStatus.EGRESS_COMPLETE
            for f in info.file_results
            if f.duration > 0
        ),
        key=lambda t: t.started_ns,
    )
    return [t for t in tracks if not t.is_audio], [t for t in tracks if t.is_audio]


def ffmpeg_args(videos: list[Track], audios: list[Track], tmp: Path) -> list[str]:
    """제일 먼저 시작한 트랙을 0초로 두고, 나머지를 늦게 시작한 만큼 민다.

    영상 조각은 다시 인코딩하지 않고 concat 으로 잇는다. 조각마다 다음 조각이
    시작하는 시각까지만 쓰고 사이는 비워 둔다. 그 목록 파일을 `tmp` 에 쓴다.
    """
    base = min(t.started_ns for t in [*videos, *audios])
    # -copyts: 파일 안의 시각을 그대로 쓴다. 영상 파일은 egress 가 키프레임을
    # 기다린 만큼 앞이 비어 있는데, 이게 없으면 ffmpeg 가 그만큼 앞으로 당겨서
    # 영상이 소리보다 빨라진다.
    args = ["nice", "-n", "19", "ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
    args += ["-copyts"]
    out: list[str] = []
    if videos:
        lines = ["ffconcat version 1.0"]
        for video, after in zip(videos, [*videos[1:], None], strict=True):
            # inpoint 0: concat 도 조각마다 앞을 당기므로 막는다.
            lines += [f"file '{Path(video.key).name}'", "inpoint 0"]
            if after:
                lines.append(
                    f"outpoint {(after.started_ns - video.started_ns) / 1e9:.3f}"
                )
        (tmp / "video.ffconcat").write_text("\n".join(lines) + "\n")
        args += ["-itsoffset", f"{(videos[0].started_ns - base) / 1e9:.3f}"]
        args += ["-f", "concat", "-i", str(tmp / "video.ffconcat")]
        out += ["-map", "0:v", "-c:v", "copy"]
    for audio in audios:
        args += ["-i", str(tmp / Path(audio.key).name)]
    if audios:
        # 음성 파일은 끊긴 동안도 무음으로 차 있어 시작 시각만 맞추면 된다.
        first = 1 if videos else 0
        delayed = [
            f"[{first + i}:a]adelay={(a.started_ns - base) // 1_000_000}:all=1[a{i}]"
            for i, a in enumerate(audios)
        ]
        # normalize=0: 입력 수로 소리를 나누지 않는다. 두 사람이 번갈아 말해
        # 겹치는 일이 적다.
        mix = (
            "".join(f"[a{i}]" for i in range(len(audios)))
            + f"amix=inputs={len(audios)}:duration=longest:normalize=0[a]"
        )
        args += ["-filter_complex", ";".join([*delayed, mix])]
        out += ["-map", "[a]", "-c:a", "libopus"]
    return [*args, *out, str(tmp / "merged.webm")]


async def _merge(session: Session, media: MediaGateway) -> Recording | None:
    """다 올라갔으면 합쳐서 결과를 돌려준다. 아직 올리는 중이면 None."""
    infos = await media.list_egress(session.room_name)
    if any(i.status < api.EgressStatus.EGRESS_COMPLETE for i in infos):
        return None
    videos, audios = pick(infos)
    if not videos and not audios:
        logger.warning("합칠 녹화 파일이 없다 session_id=%s", session.id)
        return _failed(session.id)

    tracks = [*videos, *audios]
    base = min(t.started_ns for t in tracks)
    end = max(t.started_ns + t.duration_ns for t in tracks)
    key = f"rec/{session.id}/merged.webm"
    bucket = settings.recording_bucket
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        for t in tracks:
            await asyncio.to_thread(
                _s3().download_file, bucket, t.key, str(tmp / Path(t.key).name)
            )
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_args(videos, audios, tmp), stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"ffmpeg {proc.returncode}: {err.decode()[-500:]}")
        await asyncio.to_thread(
            _s3().upload_file,
            str(tmp / "merged.webm"),
            bucket,
            key,
            ExtraArgs={"ContentType": "video/webm"},
        )
    logger.info("녹화 합침 session_id=%s tracks=%d", session.id, len(tracks))
    return Recording(
        session_id=session.id,
        status=SummaryStatus.READY,
        s3_key=key,
        egress_started_at=datetime.fromtimestamp(base / 1e9, UTC),
        duration_ms=(end - base) // 1_000_000,
        completed_at=utcnow(),
    )


def _failed(session_id: str) -> Recording:
    return Recording(
        session_id=session_id, status=SummaryStatus.FAILED, completed_at=utcnow()
    )
