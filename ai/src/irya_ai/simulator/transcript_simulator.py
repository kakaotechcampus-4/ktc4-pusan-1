"""Replay a ``TranscriptScript`` as a stream of ``Utterance`` events."""

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

from irya_ai.schemas.transcript import PassType, SpeakerRole, Track, Utterance, Word
from irya_ai.simulator.script import ScriptTurn, TranscriptScript

# Sentence boundary: terminal punctuation followed by whitespace. Used to
# approximate where a VAD-driven STT would close a chunk, since a script has
# no audio to detect silence in.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.?!])\s+")


@dataclass(frozen=True, slots=True)
class TimedEvent:
    """An utterance together with the moment it would arrive from STT."""

    emit_ms: int
    utterance: Utterance


@dataclass(frozen=True, slots=True)
class _Segment:
    """A piece of a script turn after optional sentence splitting."""

    speaker: SpeakerRole
    start_ms: int
    end_ms: int
    content: str
    uncertain: bool


def track_id_for(role: SpeakerRole) -> str:
    return f"trk_{role.value.lower()}"


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation. Never returns an empty list."""

    parts = [p for p in _SENTENCE_BOUNDARY.split(text.strip()) if p]
    return parts or [text]


def synthesize_words(content: str, start_ms: int, end_ms: int) -> list[Word]:
    """Spread words evenly over a time span, weighted by character length.

    Stand-in for real word timestamps so downstream code that reads
    ``Utterance.words`` can be exercised without an STT provider.
    """

    tokens = content.split()
    if not tokens:
        return []
    total_chars = sum(len(t) for t in tokens)
    duration = end_ms - start_ms
    words: list[Word] = []
    cursor = start_ms
    consumed = 0
    for seq, token in enumerate(tokens):
        consumed += len(token)
        word_end = start_ms + round(duration * consumed / total_chars)
        words.append(
            Word(seq=seq, start_ms=cursor, end_ms=max(word_end, cursor), content=token)
        )
        cursor = word_end
    return words


class TranscriptSimulator:
    """Turns a script into the event sequence a streaming STT would produce.

    For each turn the simulator emits ``interim_chunks`` provisional
    ``INTERIM`` utterances (growing word prefixes) followed by one ``FINAL``
    utterance. Set ``interim_chunks=0`` to emit finals only.

    Options that make the replay closer to a VAD-chunked batch STT such as
    Whisper:

    - ``split_sentences``: each sentence of a turn becomes its own utterance,
      the way a VAD closes a chunk at every pause. A 20-second answer then
      arrives as several utterances instead of one.
    - ``latency_ms``: delay every event's arrival to model VAD hang-over plus
      inference time.
    - ``synthesize_words``: fill ``Utterance.words`` with evenly spaced word
      timings.

    Events across overlapping turns are merged by arrival time so the
    consumer sees the same interleaving a real two-track STT would produce.
    """

    def __init__(
        self,
        script: TranscriptScript,
        *,
        interim_chunks: int = 2,
        split_sentences: bool = False,
        latency_ms: int = 0,
        synthesize_words: bool = False,
    ):
        if interim_chunks < 0:
            raise ValueError("interim_chunks must be >= 0")
        if latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        self.script = script
        self.interim_chunks = interim_chunks
        self.split_sentences = split_sentences
        self.latency_ms = latency_ms
        self.synthesize_words = synthesize_words

    @property
    def session_id(self) -> str:
        return self.script.session_id

    def tracks(self) -> list[Track]:
        roles = {turn.speaker for turn in self.script.turns}
        return [
            Track(track_id=track_id_for(r), session_id=self.session_id, role=r)
            for r in sorted(roles, key=lambda r: r.value)
        ]

    def segments(self) -> list[_Segment]:
        """Script turns after optional sentence splitting, in script order."""

        result: list[_Segment] = []
        for turn in self.script.turns:
            result.extend(self._segments_for_turn(turn))
        return result

    def timed_events(self) -> list[TimedEvent]:
        """All events sorted by arrival time. Finals sort after interims."""

        events: list[TimedEvent] = []
        for seq, segment in enumerate(self.segments()):
            events.extend(self._events_for_segment(seq, segment))
        events.sort(
            key=lambda e: (
                e.emit_ms,
                e.utterance.seq,
                e.utterance.pass_type is PassType.FINAL,
            )
        )
        return events

    def events(self) -> Iterator[Utterance]:
        """Synchronous replay with no pacing."""

        for event in self.timed_events():
            yield event.utterance

    def finals(self) -> list[Utterance]:
        """Only the confirmed utterances, in seq order."""

        return sorted(
            (u for u in self.events() if u.is_final),
            key=lambda u: u.seq,
        )

    async def stream(
        self, *, realtime: bool = False, speed: float = 1.0
    ) -> AsyncIterator[Utterance]:
        """Async replay. With ``realtime=True`` it sleeps between events.

        ``speed=2.0`` replays twice as fast as the script's timestamps.
        """

        if speed <= 0:
            raise ValueError("speed must be > 0")
        last_ms = 0
        for event in self.timed_events():
            if realtime:
                delay_ms = max(event.emit_ms - last_ms, 0)
                if delay_ms:
                    await asyncio.sleep(delay_ms / 1000 / speed)
                last_ms = event.emit_ms
            yield event.utterance

    def _segments_for_turn(self, turn: ScriptTurn) -> list[_Segment]:
        if not self.split_sentences:
            return [
                _Segment(
                    turn.speaker,
                    turn.start_ms,
                    turn.end_ms,
                    turn.content,
                    turn.uncertain,
                )
            ]
        sentences = split_sentences(turn.content)
        total_chars = sum(len(s) for s in sentences)
        duration = turn.end_ms - turn.start_ms
        segments: list[_Segment] = []
        cursor = turn.start_ms
        consumed = 0
        for i, sentence in enumerate(sentences):
            consumed += len(sentence)
            end = (
                turn.end_ms
                if i == len(sentences) - 1
                else (turn.start_ms + round(duration * consumed / total_chars))
            )
            segments.append(
                _Segment(
                    turn.speaker, cursor, max(end, cursor), sentence, turn.uncertain
                )
            )
            cursor = end
        return segments

    def _events_for_segment(self, seq: int, segment: _Segment) -> list[TimedEvent]:
        utterance_id = f"utt_{seq:03d}"
        common = {
            "utterance_id": utterance_id,
            "session_id": self.session_id,
            "track_id": track_id_for(segment.speaker),
            "speaker": segment.speaker,
            "seq": seq,
            "start_ms": segment.start_ms,
            "uncertain": segment.uncertain,
        }
        events: list[TimedEvent] = []

        words = segment.content.split()
        chunks = min(self.interim_chunks, max(len(words) - 1, 0))
        duration = segment.end_ms - segment.start_ms
        for i in range(1, chunks + 1):
            fraction = i / (chunks + 1)
            word_count = max(1, round(len(words) * fraction))
            partial_end = segment.start_ms + round(duration * fraction)
            events.append(
                TimedEvent(
                    emit_ms=partial_end + self.latency_ms,
                    utterance=Utterance(
                        **common,
                        pass_type=PassType.INTERIM,
                        end_ms=partial_end,
                        content=" ".join(words[:word_count]),
                    ),
                )
            )

        final_words = (
            synthesize_words(segment.content, segment.start_ms, segment.end_ms)
            if self.synthesize_words
            else []
        )
        events.append(
            TimedEvent(
                emit_ms=segment.end_ms + self.latency_ms,
                utterance=Utterance(
                    **common,
                    pass_type=PassType.FINAL,
                    end_ms=segment.end_ms,
                    content=segment.content,
                    words=final_words,
                ),
            )
        )
        return events
