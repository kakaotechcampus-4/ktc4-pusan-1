"""One timeline for a session's several tracks (TechSpec F2).

:class:`~irya_ai.schemas.transcript.Utterance` carries a ``seq`` that orders
utterances *within a session regardless of speaker*:
:meth:`~irya_ai.schemas.transcript.TranscriptSnapshot.final_utterances` sorts
by it and :func:`irya_ai.pipeline.qa_segmentation.segment_qa` reads question
and answer order straight off it. A per-track counter cannot produce that
number. Two tracks each counting from zero give the interviewer's question
and the candidate's answer the same ``seq``, the tie breaks on utterance id,
and a question can sort after the answer to it - at which point Q&A sees an
answer before any question and drops it.

So the number has to be assigned somewhere that knows about more than one
track, and this module is that place and nothing more. It is a mapping, not
a merger:

- It does **not** receive audio, subscribe to LiveKit, or know when a track
  actually started. No such merger exists in this repository.
- The caller states where each track sits on the session clock, as
  ``offset_ms``, and owns the truth of that number.

``offset_ms`` defaults to 0, which says "this track began when the session
began". For a single track that is exactly right. For two tracks it is a
claim about the recording, and a wrong one silently reintroduces the bug
above in a quieter form: a candidate who joins 30s late but whose audio
starts arriving immediately would have their first answer placed at the top
of the session. A track that joins mid-session needs a real offset; leading
silence in the pushed audio carries the same information only if the capture
really did start with the session.

The mapping
-----------

``seq = (offset_ms + track_start_ms) * capacity + ordinal``

where ``ordinal`` is the order the track was registered in. It satisfies the
existing contract without redefining it:

- **An integer, never negative.** Offsets and segment starts are both
  non-negative, so the product is too.
- **Ordered by source audio, not by arrival.** ``seq`` is built from when the
  audio was *spoken* on the session clock. A response that comes back late,
  or first, does not move.
- **Unique.** Within one track, no two segments share a start. Across tracks,
  the ordinal keeps two utterances spoken at the same millisecond apart -
  deterministically, by registration order, not by whichever track id happens
  to sort first.
- **Stable.** A pure function of the track and the segment's start, so a
  revision of an utterance recomputes the same ``seq`` and does not trip
  :meth:`TranscriptSnapshot._check_revisions`, which pins ``(track_id,
  speaker, seq, start_ms)`` across revisions of one utterance id.

``seq`` is therefore **sparse**: values are far apart and carry no meaning
beyond their order. Nothing in this repository requires them to be dense -
the schema asks for ``ge=0`` and the consumers sort - but a reader expecting
0, 1, 2 will see something else, and any consumer treating ``seq`` as a count
of utterances would be wrong. Only the ordering is a contract.

Lifetime
--------

A :class:`SessionOrdering` lasts as long as its session and holds one entry
per track id; it has no eviction and no persistence. Nothing here ends, and
the caller drops the whole object when the session does.

**No reconnect continuity is implemented.** What :meth:`SessionOrdering.register`
gives back a second time is the same mapping, not the same stream. A track's
numbering also depends on state that lives in its
:class:`~irya_ai.stt.stream.TranscriptionStream`, and a new stream starts
that state over:

- the segmenter's sample clock restarts at track time 0, so audio spoken
  after a reconnect is placed as though it were spoken at the beginning;
- the segment index restarts at 0, so utterance ids (``utt_<track>_<index>``)
  are re-issued from the top and collide with the first stream's;
- ``timings`` and ``rejected`` start empty - the first stream's records go
  with the first stream.

So one :class:`~irya_ai.stt.stream.TranscriptionStream` per track per
session, for the life of that track, is the supported shape. Surviving a
dropped connection would mean carrying the sample clock and the index across
streams and reconciling the ids, and that is a design decision nobody has
made here. Until it is made, a caller that must reconnect owns the problem:
either treat the reconnected audio as a new track with its own id and a real
``offset_ms``, or accept that the two halves cannot be merged on ``seq``.
"""

import dataclasses

# How many tracks share one session's numbering. An interview is two; the
# headroom is for an observer or a second interviewer. Raising it later
# renumbers every seq, so it is a per-session constant rather than something
# that grows as tracks register.
DEFAULT_CAPACITY = 16


@dataclasses.dataclass(frozen=True)
class TrackOrdering:
    """One track's place on the session timeline.

    Handed out by :meth:`SessionOrdering.register` and carried by the track's
    :class:`~irya_ai.stt.stream.TranscriptionStream`. Frozen, and every method
    is a pure function of a segment's track-local time, so the same segment
    always maps to the same numbers.
    """

    track_id: str
    ordinal: int
    offset_ms: int
    capacity: int

    def session_ms(self, track_ms: int) -> int:
        """A track-local timestamp moved onto the session clock."""

        return self.offset_ms + track_ms

    def seq(self, track_start_ms: int) -> int:
        """The session-wide ordering key for a segment starting here."""

        return self.session_ms(track_start_ms) * self.capacity + self.ordinal


class SessionOrdering:
    """Hands out :class:`TrackOrdering` for the tracks of one session.

    Create one per session and register each track once::

        ordering = SessionOrdering()
        interviewer = ordering.register("trk_interviewer")
        candidate = ordering.register("trk_candidate", offset_ms=30_000)

    Registration order decides the tie-break between two tracks speaking at
    the same millisecond, so it is worth registering in a fixed order - the
    interviewer first, so that a question asked at the same instant as an
    answer sorts before it, which is the reading Q&A expects.
    """

    def __init__(self, *, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._tracks: dict[str, TrackOrdering] = {}

    @property
    def tracks(self) -> tuple[TrackOrdering, ...]:
        """Every registered track, in registration order."""

        return tuple(self._tracks.values())

    def register(self, track_id: str, *, offset_ms: int = 0) -> TrackOrdering:
        """Place a track on the session clock and return its ordering.

        Registering the same track twice with the same offset returns the
        same ordering. That is idempotence of *this mapping* and nothing
        wider: the ordinal and the offset are preserved, so the same track
        time still maps to the same ``seq``. It does not carry a track across
        a reconnect - see "Lifetime" in the module docstring. Registering with
        a *different* offset raises: the track's utterances are already
        numbered under the old one, and silently renumbering them would
        reorder a transcript that has been read.
        """

        if not track_id:
            raise ValueError("track_id must not be empty")
        if offset_ms < 0:
            raise ValueError("offset_ms must not be negative")

        existing = self._tracks.get(track_id)
        if existing is not None:
            if existing.offset_ms != offset_ms:
                raise ValueError(
                    f"{track_id} is already placed at {existing.offset_ms}ms"
                )
            return existing

        if len(self._tracks) >= self.capacity:
            raise ValueError(f"a session orders at most {self.capacity} tracks")

        ordering = TrackOrdering(
            track_id=track_id,
            ordinal=len(self._tracks),
            offset_ms=offset_ms,
            capacity=self.capacity,
        )
        self._tracks[track_id] = ordering
        return ordering


def solo_ordering(track_id: str) -> TrackOrdering:
    """Ordering for a track that is the only one in its session.

    The single-track case needs no registry and no offset, but it still needs
    a :class:`TrackOrdering` to produce a ``seq``. This is that, and it is
    what :class:`~irya_ai.stt.stream.TranscriptionStream` falls back to when
    no ordering is passed in.
    """

    return SessionOrdering().register(track_id)
