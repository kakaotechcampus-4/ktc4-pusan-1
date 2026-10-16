"""The Deepgram stream: what it yields, what it counts, and how it ends."""

import asyncio

import pytest
from livekit.agents import stt as lk_stt
from livekit.agents import vad as lk_vad

from irya_ai.config import Settings
from irya_ai.schemas.transcript import PassType, SpeakerRole
from irya_ai.stt import deepgram
from irya_ai.stt.session import SessionOrdering

_END = object()


class FakeSttStream:
    """The plugin stream: frames in, events out, ``end_input`` flushes."""

    def __init__(self) -> None:
        self.frames: list = []
        self.flushes = 0
        self.ended = False
        self.closed = False
        self._events: asyncio.Queue = asyncio.Queue()

    def push_frame(self, frame) -> None:
        if self.ended:
            raise RuntimeError("input ended")
        self.frames.append(frame)

    def flush(self) -> None:
        if self.ended:
            raise RuntimeError("input ended")
        self.flushes += 1

    def end_input(self) -> None:
        self.flush()
        self.ended = True

    async def aclose(self) -> None:
        self.closed = True
        self._events.put_nowait(_END)

    def emit(self, event: lk_stt.SpeechEvent) -> None:
        self._events.put_nowait(event)

    def finish(self) -> None:
        self._events.put_nowait(_END)

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self._events.get()
        if event is _END:
            raise StopAsyncIteration
        return event


class FakeStt:
    def __init__(self) -> None:
        self.streams: list[FakeSttStream] = []

    def stream(self, *, language: str) -> FakeSttStream:
        assert language == "ko"
        self.streams.append(FakeSttStream())
        return self.streams[-1]


class FakeVadStream(FakeSttStream):
    pass


class FakeVad:
    def __init__(self) -> None:
        self.streams: list[FakeVadStream] = []

    def stream(self) -> FakeVadStream:
        self.streams.append(FakeVadStream())
        return self.streams[-1]


def final(text: str, start: float, end: float) -> lk_stt.SpeechEvent:
    return lk_stt.SpeechEvent(
        type=lk_stt.SpeechEventType.FINAL_TRANSCRIPT,
        alternatives=[
            lk_stt.SpeechData(language="ko", text=text, start_time=start, end_time=end)
        ],
    )


def interim(text: str) -> lk_stt.SpeechEvent:
    return lk_stt.SpeechEvent(
        type=lk_stt.SpeechEventType.INTERIM_TRANSCRIPT,
        alternatives=[lk_stt.SpeechData(language="ko", text=text)],
    )


def usage(seconds: float) -> lk_stt.SpeechEvent:
    return lk_stt.SpeechEvent(
        type=lk_stt.SpeechEventType.RECOGNITION_USAGE,
        recognition_usage=lk_stt.RecognitionUsage(audio_duration=seconds),
    )


def vad_end() -> lk_vad.VADEvent:
    return lk_vad.VADEvent(
        type=lk_vad.VADEventType.END_OF_SPEECH,
        samples_index=0,
        timestamp=0.0,
        speech_duration=1.0,
        silence_duration=1.0,
    )


def open_stream(**kwargs):
    stt, vad = FakeStt(), FakeVad()
    stream = deepgram.DeepgramTranscriptionStream(
        stt,  # type: ignore[arg-type]
        session_id="ses_123",
        track_id=kwargs.pop("track_id", "trk_1"),
        speaker=SpeakerRole.CANDIDATE,
        vad=vad,  # type: ignore[arg-type]
        clock=lambda: 42.0,
        **kwargs,
    )
    return stream, stt.streams[0], vad.streams[0]


async def collect(stream) -> list:
    return [u async for u in stream]


async def test_only_non_empty_finals_become_utterances() -> None:
    stream, plugin, _ = open_stream()
    plugin.emit(interim("안녕"))
    plugin.emit(interim("안녕하세요"))
    plugin.emit(final(" 안녕하세요 ", 0.5, 1.2))
    plugin.emit(final("", 1.3, 1.3))
    plugin.emit(final("반갑습니다", 2.0, 2.8))
    plugin.finish()

    utterances = await collect(stream)

    assert [u.content for u in utterances] == ["안녕하세요", "반갑습니다"]
    assert all(u.pass_type is PassType.FINAL for u in utterances)
    assert [u.utterance_id for u in utterances] == ["utt_trk_1_0000", "utt_trk_1_0001"]
    assert stream.interims_seen == 2
    assert stream.empty_finals == 1
    assert [f.interims_before for f in stream.finals] == [2, 0]
    assert [f.received_at for f in stream.finals] == [42.0, 42.0]
    await stream.aclose()


async def test_times_and_seq_come_from_the_session_timeline() -> None:
    session = SessionOrdering()
    session.register("trk_0")
    ordering = session.register("trk_1", offset_ms=10_000)
    stream, plugin, _ = open_stream(ordering=ordering)
    plugin.emit(final("첫 답변", 0.5, 1.25))
    plugin.emit(final("시간 없는 답변", 0.0, 0.0))
    plugin.finish()

    first, second = await collect(stream)

    assert (first.start_ms, first.end_ms) == (10_500, 11_250)
    assert first.seq == ordering.seq(500)
    # A final without word timings must not reuse an earlier seq.
    assert second.start_ms == 10_501
    assert second.seq > first.seq
    assert first.speaker is SpeakerRole.CANDIDATE
    assert first.session_id == "ses_123"
    await stream.aclose()


async def test_usage_is_summed_as_billed_audio() -> None:
    stream, plugin, _ = open_stream()
    plugin.emit(usage(5.0))
    plugin.emit(usage(2.5))
    plugin.finish()

    assert await collect(stream) == []
    assert stream.billed_audio_s == pytest.approx(7.5)
    assert "billed=7.5s" in deepgram.summary(stream)
    await stream.aclose()


async def test_audio_reaches_both_deepgram_and_the_vad() -> None:
    stream, plugin, vad = open_stream()

    assert stream.push(b"\x00\x00" * 160) == 0
    assert stream.push(b"") == 0

    assert len(plugin.frames) == len(vad.frames) == 1
    assert plugin.frames[0].samples_per_channel == 160
    assert stream.audio_s == pytest.approx(0.01)
    await stream.aclose()


async def test_silence_after_speech_asks_deepgram_to_finalize() -> None:
    stream, plugin, vad = open_stream()
    vad.emit(vad_end())
    for _ in range(3):
        await asyncio.sleep(0)

    assert plugin.flushes == 1
    assert stream.vad_flushes == 1
    await stream.aclose()


async def test_close_ends_input_so_the_tail_is_still_transcribed() -> None:
    stream, plugin, vad = open_stream()
    stream.push(b"\x00\x00" * 160)

    stream.close()
    stream.close()

    assert plugin.ended and vad.ended
    assert plugin.flushes == 1, "end_input flushes once; a second close is a no-op"
    with pytest.raises(RuntimeError):
        stream.push(b"\x00\x00")
    # What Deepgram sends after the flush still comes out.
    plugin.emit(final("마지막 말", 0.0, 0.4))
    plugin.finish()
    assert [u.content for u in await collect(stream)] == ["마지막 말"]
    await stream.aclose()


async def test_aclose_releases_both_streams() -> None:
    stream, plugin, vad = open_stream()

    await stream.aclose()
    await stream.aclose()

    assert plugin.closed and vad.closed


def test_no_key_is_reported_as_not_configured() -> None:
    with pytest.raises(deepgram.DeepgramNotConfigured):
        deepgram.build_stt(Settings(_env_file=None))
