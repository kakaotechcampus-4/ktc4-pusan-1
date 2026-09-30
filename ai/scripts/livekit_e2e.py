"""Local LiveKit end-to-end check for the STT worker, without the frontend or backend.

Plays a WAV into a room as the candidate and listens as the interviewer, the
way the two browsers would, then reports what arrived. Run it against a
LiveKit server the worker is registered with::

    docker run -d --name lk-dev -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \\
        livekit/livekit-server --dev --bind 0.0.0.0
    LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret \\
        uv run python -m irya_ai.worker dev
    uv run python scripts/livekit_e2e.py --wav path/to/korean_16k_mono.wav

With ``--interviewer-wav`` the interviewer speaks first, so the answer that
follows opens a Q&A pair and the follow-up loop (#83) has something to run
on; the worker then posts suggestions to the Backend named by its
``BACKEND_BASE_URL``, which this script does not observe - read the
Backend's ``꼬리질문 수신`` log or the worker's ``suggestion round`` line.
When the Backend created the session (and so the room), pass its id with
``--session-id`` so the worker's posts land on a session the Backend knows.

The room is created first and empty, so the worker is dispatched before either
human joins - the same order the backend produces. Elice STT is the one thing
this does not fake: the worker's ``ELICE_*`` settings must point at a real
deployment, and the WAV must hold real Korean speech (a tone is rejected by
the hallucination guard, as it should be).
"""

import argparse
import asyncio
import json
import os
import sys
import time
import wave
from dataclasses import dataclass, field

from livekit import api, rtc

TOPIC = "irya.transcript.v1"
FRAME_MS = 20


@dataclass
class Received:
    at: float
    identity: str
    event: dict


@dataclass
class Report:
    started_at: float | None = None
    interviewer: list[Received] = field(default_factory=list)
    candidate: list[Received] = field(default_factory=list)


def token(url_key: str, secret: str, room: str, identity: str, *, publish: bool) -> str:
    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=publish, can_subscribe=True
    )
    return (
        api.AccessToken(url_key, secret)
        .with_identity(identity)
        .with_grants(grants)
        .to_jwt()
    )


def listen(room: rtc.Room, identity: str, into: list[Received], report: Report) -> None:
    def handler(reader, _participant_identity: str) -> None:
        async def read() -> None:
            raw = await reader.read_all()
            try:
                event = json.loads(raw)
            except ValueError:
                event = {"type": "unparseable", "raw": raw[:80]}
            into.append(Received(time.monotonic(), identity, event))

        asyncio.ensure_future(read())

    room.register_text_stream_handler(TOPIC, handler)


async def publish_wav(room: rtc.Room, path: str, report: Report) -> None:
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise SystemExit("the WAV must be 16-bit mono")
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())

    source = rtc.AudioSource(rate, 1)
    track = rtc.LocalAudioTrack.create_audio_track("microphone", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    samples = rate * FRAME_MS // 1000
    step = samples * 2
    if report.started_at is None:
        report.started_at = time.monotonic()
    next_at = time.monotonic()
    for offset in range(0, len(pcm), step):
        chunk = pcm[offset : offset + step]
        if len(chunk) < step:
            chunk = chunk + b"\x00" * (step - len(chunk))
        await source.capture_frame(
            rtc.AudioFrame(
                data=chunk,
                sample_rate=rate,
                num_channels=1,
                samples_per_channel=samples,
            )
        )
        next_at += FRAME_MS / 1000
        await asyncio.sleep(max(0.0, next_at - time.monotonic()))
    await source.wait_for_playout()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--wav", required=True, help="the candidate's speech")
    parser.add_argument(
        "--interviewer-wav",
        default=None,
        help="speech the interviewer publishes before the candidate answers",
    )
    parser.add_argument(
        "--url", default=os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    )
    parser.add_argument(
        "--api-key", default=os.environ.get("LIVEKIT_API_KEY", "devkey")
    )
    parser.add_argument(
        "--api-secret", default=os.environ.get("LIVEKIT_API_SECRET", "secret")
    )
    parser.add_argument("--session-id", default=f"ses_e2e_{int(time.time())}")
    parser.add_argument(
        "--settle", type=float, default=3.0, help="seconds for the worker to join"
    )
    parser.add_argument(
        "--wait", type=float, default=20.0, help="seconds to wait after the audio"
    )
    args = parser.parse_args()

    room_name = f"interview_{args.session_id}"
    report = Report()

    lk = api.LiveKitAPI(args.url, args.api_key, args.api_secret)
    await lk.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=120))
    print(f"room created: {room_name}", file=sys.stderr)
    await asyncio.sleep(args.settle)

    interviewer = rtc.Room()
    candidate = rtc.Room()
    listen(interviewer, "INTERVIEWER", report.interviewer, report)
    listen(candidate, "CANDIDATE", report.candidate, report)
    try:
        await interviewer.connect(
            args.url,
            token(
                args.api_key,
                args.api_secret,
                room_name,
                "INTERVIEWER",
                publish=args.interviewer_wav is not None,
            ),
        )
        await candidate.connect(
            args.url,
            token(args.api_key, args.api_secret, room_name, "CANDIDATE", publish=True),
        )
        agents = [p.identity for p in interviewer.remote_participants.values()]
        print(f"interviewer sees participants: {agents}", file=sys.stderr)

        if args.interviewer_wav:
            await publish_wav(interviewer, args.interviewer_wav, report)
            print("interviewer finished; candidate answers", file=sys.stderr)
        await publish_wav(candidate, args.wav, report)
        print("audio finished; waiting for the tail", file=sys.stderr)
        await asyncio.sleep(args.wait)
    finally:
        await candidate.disconnect()
        await interviewer.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        finally:
            await lk.aclose()

    started = report.started_at or time.monotonic()
    finals = [
        r for r in report.interviewer if r.event.get("type") == "transcript.delta"
    ]
    degraded = [
        r for r in report.interviewer if r.event.get("type") == "stream.degraded"
    ]
    result = {
        "result": "PASS"
        if finals and not degraded and not report.candidate
        else "FAIL",
        "room": room_name,
        "precreated_empty_room": True,
        "interviewer_transcript_events": len(finals),
        "candidate_transcript_events": len(report.candidate),
        "degraded_events": len(degraded),
        "first_event_after_audio_start_s": (
            round(finals[0].at - started, 3) if finals else None
        ),
        "events": [
            {
                "t": round(r.at - started, 3),
                "at": r.event.get("at"),
                "speaker": r.event.get("speaker"),
                "text": r.event.get("text"),
            }
            for r in finals
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
