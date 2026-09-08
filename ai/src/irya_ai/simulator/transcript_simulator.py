"""Replay a ``TranscriptScript`` as a stream of ``Utterance`` events."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

from irya_ai.schemas.transcript import PassType, SpeakerRole, Track, Utterance
from irya_ai.simulator.script import ScriptTurn, TranscriptScript


@dataclass(frozen=True, slots=True)
class TimedEvent:
    """An utterance together with the moment it would arrive from STT."""

    emit_ms: int
    utterance: Utterance


def track_id_for(role: SpeakerRole) -> str:
    return f"trk_{role.value.lower()}"


class TranscriptSimulator:
    """Turns a script into the event sequence a streaming STT would produce.

    For each turn the simulator emits ``interim_chunks`` provisional
    ``INTERIM`` utterances (growing word prefixes) followed by one ``FINAL``
    utterance. Set ``interim_chunks=0`` to emit finals only.

    Events across overlapping turns are merged by arrival time so the
    consumer sees the same interleaving a real two-track STT would produce.
    """

    def __init__(self, script: TranscriptScript, *, interim_chunks: int = 2):
        if interim_chunks < 0:
            raise ValueError("interim_chunks must be >= 0")
        self.script = script
        self.interim_chunks = interim_chunks

    @property
    def session_id(self) -> str:
        return self.script.session_id

    def tracks(self) -> list[Track]:
        roles = {turn.speaker for turn in self.script.turns}
        return [
            Track(track_id=track_id_for(r), session_id=self.session_id, role=r)
            for r in sorted(roles, key=lambda r: r.value)
        ]

    def timed_events(self) -> list[TimedEvent]:
        """All events sorted by arrival time. Finals sort after interims."""

        events: list[TimedEvent] = []
        for seq, turn in enumerate(self.script.turns):
            events.extend(self._events_for_turn(seq, turn))
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

    def _events_for_turn(self, seq: int, turn: ScriptTurn) -> list[TimedEvent]:
        utterance_id = f"utt_{seq:03d}"
        common = {
            "utterance_id": utterance_id,
            "session_id": self.session_id,
            "track_id": track_id_for(turn.speaker),
            "speaker": turn.speaker,
            "seq": seq,
            "start_ms": turn.start_ms,
            "uncertain": turn.uncertain,
        }
        events: list[TimedEvent] = []

        words = turn.content.split()
        chunks = min(self.interim_chunks, max(len(words) - 1, 0))
        duration = turn.end_ms - turn.start_ms
        for i in range(1, chunks + 1):
            fraction = i / (chunks + 1)
            word_count = max(1, round(len(words) * fraction))
            partial_end = turn.start_ms + round(duration * fraction)
            events.append(
                TimedEvent(
                    emit_ms=partial_end,
                    utterance=Utterance(
                        **common,
                        pass_type=PassType.INTERIM,
                        end_ms=partial_end,
                        content=" ".join(words[:word_count]),
                    ),
                )
            )

        events.append(
            TimedEvent(
                emit_ms=turn.end_ms,
                utterance=Utterance(
                    **common,
                    pass_type=PassType.FINAL,
                    end_ms=turn.end_ms,
                    content=turn.content,
                ),
            )
        )
        return events
