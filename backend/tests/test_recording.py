"""녹화 (#112) — 트랙별 녹화 시작, 합치기, 재생 URL."""

import asyncio
import base64
import shutil
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from livekit import api
from livekit.protocol.models import ParticipantInfo, TrackSource

from app.core.config import settings
from app.domain.models import (
    Interview,
    Recording,
    Session,
    SessionStatus,
    SummaryStatus,
    User,
    utcnow,
)
from app.domain.store import InMemoryStore
from app.services import recording
from tests.conftest import loop_spy

WEBHOOK = "/api/v1/livekit/webhook"
CAMERA, MIC = TrackSource.CAMERA, TrackSource.MICROPHONE
STANDARD, AGENT = ParticipantInfo.Kind.STANDARD, ParticipantInfo.Kind.AGENT
S = 10**9  # ns


def _event(name: str, room: str, identity="CANDIDATE", source=CAMERA, kind=STANDARD):
    return SimpleNamespace(
        event=name,
        room=SimpleNamespace(name=room),
        participant=SimpleNamespace(identity=identity, kind=kind, joined_at_ms=0),
        track=SimpleNamespace(sid=f"TR_{identity}_{source}", source=source),
    )


def _post(client) -> int:
    return client.post(
        WEBHOOK, content=b"{}", headers={"Authorization": "signed"}
    ).status_code


@pytest.fixture
def session(store: InMemoryStore, owner: User) -> Session:
    interview = Interview(interviewer_id=owner.id)
    store.add_interview(interview)
    created = Session(interview_id=interview.id)
    store.add_session(created)
    return created


@pytest.fixture
def bucket(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "recording_bucket", "test-bucket")
    return "test-bucket"


# ── 녹화 시작 (track_published) ─────────────────────────


def test_records_candidate_video_and_both_voices(client, media, store, session, bucket):
    """지원자 영상 · 두 사람 음성만. 면접관 영상 · 화면 공유 · 워커는 빼놓는다."""
    room = session.room_name
    for identity, source, kind in [
        ("CANDIDATE", CAMERA, STANDARD),
        ("CANDIDATE", MIC, STANDARD),
        ("INTERVIEWER", MIC, STANDARD),
        ("INTERVIEWER", CAMERA, STANDARD),
        ("CANDIDATE", TrackSource.SCREEN_SHARE, STANDARD),
        ("agent-1", MIC, AGENT),
    ]:
        media.webhook_event = _event("track_published", room, identity, source, kind)
        assert _post(client) == 204

    assert [path for _, _, path in media.egress_started] == [
        f"rec/{session.id}/CANDIDATE-TR_CANDIDATE_{CAMERA}",
        f"rec/{session.id}/CANDIDATE-TR_CANDIDATE_{MIC}",
        f"rec/{session.id}/INTERVIEWER-TR_INTERVIEWER_{MIC}",
    ]
    assert store.get_recording(session.id).status is SummaryStatus.PROCESSING


def test_no_bucket_no_recording(client, media, store, session):
    media.webhook_event = _event("track_published", session.room_name)
    assert _post(client) == 204
    assert media.egress_started == []
    assert store.get_recording(session.id) is None


def test_egress_ended_wakes_the_merger(client, media, monkeypatch):
    woken: list[bool] = []
    monkeypatch.setattr(recording, "kick", lambda: woken.append(True))
    # 녹화 이벤트에는 room 이 비어 있다.
    media.webhook_event = _event("egress_ended", "")
    assert _post(client) == 204
    assert woken == [True]


# ── 방이 닫힘 (room_finished) ───────────────────────────


def test_abandoned_interview_ends_when_the_room_closes(client, media, store, session):
    session.start()
    store.save_session(session)
    media.webhook_event = _event("room_finished", session.room_name)

    assert _post(client) == 204
    assert store.get_session(session.id).status is SessionStatus.ENDED
    assert store.get_summary(session.id) is not None


def test_room_closing_before_start_keeps_the_session(client, media, store, session):
    """시작 전 방은 다시 들어오면 새로 열린다. 면접을 끝내면 안 된다."""
    media.webhook_event = _event("room_finished", session.room_name)
    assert _post(client) == 204
    assert store.get_session(session.id).status is SessionStatus.WAITING


# ── 재생 (GET /recording) ───────────────────────────────


def _url(session: Session) -> str:
    return f"/api/v1/sessions/{session.id}/recording"


def test_no_recording_is_404(client, session):
    assert client.get(_url(session)).status_code == 404


def test_processing_is_202(client, store, session):
    store.ensure_recording(session.id)
    res = client.get(_url(session))
    assert res.status_code == 202
    assert res.json()["status"] == "PROCESSING"


def test_failed_is_404(client, store, session):
    store.ensure_recording(session.id)
    store.save_recording(Recording(session.id, status=SummaryStatus.FAILED))
    assert client.get(_url(session)).status_code == 404


def test_ready_gives_a_signed_url_and_the_offset(
    client, store, session, bucket, monkeypatch
):
    origin = utcnow()
    store.mark_origin(session.id, origin)
    store.ensure_recording(session.id)
    store.save_recording(
        Recording(
            session.id,
            status=SummaryStatus.READY,
            s3_key=f"rec/{session.id}/merged.webm",
            egress_started_at=origin + timedelta(milliseconds=840),
            duration_ms=634_500,
        )
    )
    expires = origin + timedelta(hours=3)
    monkeypatch.setattr(
        recording, "presign", lambda key: (f"https://s3/{key}?sig", expires)
    )

    res = client.get(_url(session))

    assert res.status_code == 200
    body = res.json()
    assert body["url"] == f"https://s3/rec/{session.id}/merged.webm?sig"
    # 서명한 만료 시각 그대로다 — 다르면 FE 가 아직 살아 있는 URL 을 다시 받거나,
    # 이미 죽은 URL 을 붙잡는다.
    assert datetime.fromisoformat(body["expiresAt"]) == expires
    assert body["offsetMs"] == 840
    assert body["durationSec"] == 634


# ── 재생 URL 서명 (#197) ────────────────────────────────


@pytest.fixture
def cdn(monkeypatch: pytest.MonkeyPatch) -> Iterator[rsa.RSAPrivateKey]:
    """CloudFront 를 켠다. 서명기는 캐시되므로 앞뒤로 비운다."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setattr(settings, "recording_cdn_domain", "d123.cloudfront.net")
    monkeypatch.setattr(settings, "recording_cdn_key_id", "KTEST")
    monkeypatch.setattr(
        settings, "recording_cdn_private_key", base64.b64encode(pem).decode()
    )
    recording._cdn_signer.cache_clear()
    yield key
    recording._cdn_signer.cache_clear()


def test_cloudfront_url_is_signed_with_our_key_for_three_hours(cdn):
    before = utcnow()
    url, expires = recording.presign("rec/ses_1/merged.webm")

    # 초 단위로 내린 값이라 3시간보다 1초 미만 짧을 수 있다.
    assert timedelta(hours=3, seconds=-1) < expires - before <= timedelta(hours=3)
    base, _, query = url.partition("?")
    assert base == "https://d123.cloudfront.net/rec/ses_1/merged.webm"
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert params["Key-Pair-Id"] == "KTEST"
    assert int(params["Expires"]) == expires.timestamp()

    # CloudFront 가 검사하는 그대로 — 같은 정책 문장에 RSA-SHA1 서명이 맞는지.
    policy = CloudFrontSigner("KTEST", lambda m: b"").build_policy(base, expires)
    signature = base64.b64decode(
        params["Signature"].replace("-", "+").replace("_", "=").replace("~", "/")
    )
    cdn.public_key().verify(
        signature, policy.encode(), padding.PKCS1v15(), hashes.SHA1()
    )


def test_without_a_domain_it_stays_a_ten_minute_s3_url(bucket, monkeypatch):
    # 키 ID · 개인키가 있어도 도메인이 비면 꺼진 것이다 — 켜기 전 서버의 모습이다.
    monkeypatch.setattr(settings, "recording_cdn_domain", "")
    monkeypatch.setattr(settings, "recording_cdn_key_id", "KTEST")
    monkeypatch.setattr(settings, "recording_cdn_private_key", "unused")
    recording._cdn_signer.cache_clear()
    signed: list[dict] = []

    def generate_presigned_url(op, **kw):
        signed.append({"op": op, **kw["Params"], "ttl": kw["ExpiresIn"]})
        return "https://s3/signed"

    monkeypatch.setattr(
        recording,
        "_s3",
        lambda: SimpleNamespace(generate_presigned_url=generate_presigned_url),
    )
    before = utcnow()

    url, expires = recording.presign("rec/ses_1/merged.webm")

    assert url == "https://s3/signed"
    assert signed == [
        {
            "op": "get_object",
            "Bucket": "test-bucket",
            "Key": "rec/ses_1/merged.webm",
            "ttl": 600,
        }
    ]
    assert timedelta(minutes=10) <= expires - before < timedelta(minutes=10, seconds=5)


@pytest.mark.parametrize(
    ("domain", "key_id", "private_key", "message"),
    [
        ("d123.cloudfront.net", "", "", "RECORDING_CDN_KEY_ID"),
        ("d123.cloudfront.net", "KTEST", "", "RECORDING_CDN_PRIVATE_KEY"),
        ("d123.cloudfront.net", "KTEST", "bm90IGEga2V5", "읽을 수 없습니다"),
        ("https://d123.cloudfront.net", "KTEST", "unused", "https:// 없이"),
    ],
)
def test_turning_on_with_a_broken_setting_fails_at_startup(
    monkeypatch, domain, key_id, private_key, message
):
    monkeypatch.setattr(settings, "recording_cdn_domain", domain)
    monkeypatch.setattr(settings, "recording_cdn_key_id", key_id)
    monkeypatch.setattr(settings, "recording_cdn_private_key", private_key)
    # 예외는 캐시되지 않으니 앞만 비우면 된다.
    recording._cdn_signer.cache_clear()
    with pytest.raises(RuntimeError, match=message):
        recording.check_cdn_at_startup()


# ── 합치기 ─────────────────────────────────────────────


def _info(status: api.EgressStatus, key: str = "", started: int = 0, duration: int = 0):
    files = [api.FileInfo(filename=key, started_at=started, duration=duration)]
    return api.EgressInfo(status=status, file_results=files if key else [])


COMPLETE = api.EgressStatus.EGRESS_COMPLETE


@pytest.fixture
def ended(store: InMemoryStore, session: Session) -> Session:
    store.ensure_recording(session.id)
    session.end()
    store.save_session(session)
    return session


def test_waits_while_egress_is_still_uploading(store, media, ended):
    media.egress_infos = [_info(api.EgressStatus.EGRESS_ENDING)]
    asyncio.run(recording.merge_pending(store, media))
    assert store.get_recording(ended.id).status is SummaryStatus.PROCESSING


def test_gives_up_an_hour_after_the_interview(store, media, ended):
    ended.ended_at = utcnow() - recording.GIVE_UP - timedelta(seconds=1)
    store.save_session(ended)
    media.egress_infos = [_info(api.EgressStatus.EGRESS_ACTIVE)]
    asyncio.run(recording.merge_pending(store, media))
    assert store.get_recording(ended.id).status is SummaryStatus.FAILED


def test_nothing_to_merge_is_failed(store, media, ended):
    media.egress_infos = [_info(api.EgressStatus.EGRESS_ABORTED)]
    asyncio.run(recording.merge_pending(store, media))
    assert store.get_recording(ended.id).status is SummaryStatus.FAILED


class FakeS3:
    """S3 대역. 내려받기는 로컬 파일을 복사하고, 올린 것은 남겨 둔다."""

    def __init__(self, files: dict[str, Path], out: Path) -> None:
        self.files, self.out = files, out
        self.uploaded: dict[str, str] = {}

    def download_file(self, bucket: str, key: str, path: str) -> None:
        shutil.copy(self.files[key], path)

    def upload_file(self, path: str, bucket: str, key: str, ExtraArgs: dict) -> None:
        shutil.copy(path, self.out)
        self.uploaded[key] = ExtraArgs["ContentType"]


def _make(args: str, path: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", *args.split(), str(path)], check=True
    )
    return path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 가 없다")
def test_merges_tracks_aligned_by_their_start(
    store, media, ended, bucket, monkeypatch, tmp_path
):
    """면접관 음성은 0초부터 3초. 지원자는 1초에 들어와 2초 있다가 나갔고,
    4초에 다시 들어와 2초 있었다 — 영상 · 음성이 두 조각씩이다.

    첫 영상 조각은 egress 가 키프레임을 기다려 파일 안 0.5초부터 찼다. 합본에서
    영상은 1.5초에 시작해야 하고(앞 빈 구간을 당기면 소리보다 빨라진다), 두 번째
    조각은 4초에 붙고 그 사이는 빈다.
    """
    video = "-f lavfi -i testsrc=size=160x120:rate=10 -c:v libvpx"
    sine = "-f lavfi -i sine -t 2 -c:a libopus"
    src = {
        "rec/s/v1.webm": _make(
            f"{video} -t 1.5 -output_ts_offset 0.5", tmp_path / "v1.webm"
        ),
        "rec/s/v2.webm": _make(f"{video} -t 2", tmp_path / "v2.webm"),
        "rec/s/c1.ogg": _make(sine, tmp_path / "c1.ogg"),
        "rec/s/c2.ogg": _make(sine, tmp_path / "c2.ogg"),
        "rec/s/i.ogg": _make("-f lavfi -i sine -t 3 -c:a libopus", tmp_path / "i.ogg"),
    }
    s3 = FakeS3(src, tmp_path / "merged.webm")
    on_loop: list[str] = []
    monkeypatch.setattr(recording, "_s3", loop_spy("_s3", lambda: s3, on_loop))
    t0 = 1_790_000_000 * S
    media.egress_infos = [
        _info(COMPLETE, "rec/s/v2.webm", t0 + 4 * S, 2 * S),
        _info(COMPLETE, "rec/s/v1.webm", t0 + S, 2 * S),
        _info(COMPLETE, "rec/s/c1.ogg", t0 + S, 2 * S),
        _info(COMPLETE, "rec/s/c2.ogg", t0 + 4 * S, 2 * S),
        _info(COMPLETE, "rec/s/i.ogg", t0, 3 * S),
    ]

    asyncio.run(recording.merge_pending(store, media))

    done = store.get_recording(ended.id)
    assert done.status is SummaryStatus.READY
    assert done.s3_key == f"rec/{ended.id}/merged.webm"
    assert done.egress_started_at.timestamp() == 1_790_000_000
    assert done.duration_ms == 6000
    assert s3.uploaded == {done.s3_key: "video/webm"}
    # 클라이언트를 처음 만들 때 자격증명을 찾으러 간다. 루프 밖에서 만든다 (#183).
    assert on_loop == []

    def packets(stream: str) -> list[float]:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                stream,
                "-of",
                "csv=p=0",
                "-show_entries",
                "packet=pts_time",
                str(tmp_path / "merged.webm"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return [float(t.split(",")[0]) for t in probe.stdout.split()]

    frames = packets("v")
    assert frames[0] == pytest.approx(1.5, abs=0.02)
    assert max(t for t in frames if t < 3.5) < 3.0  # 첫 조각은 3초 전에 끝난다
    assert min(t for t in frames if t > 3.0) == pytest.approx(4.0, abs=0.02)
    # 소리는 지원자의 두 번째 조각(4~6초)에서 끝난다. 밀지 않으면 3초에 끝난다.
    assert packets("a")[-1] == pytest.approx(6.0, abs=0.05)
