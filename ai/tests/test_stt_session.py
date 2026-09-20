"""One timeline for two speakers: the ``seq`` that Q&A reads order off.

The bug these guard against: every track counted its own segments from zero,
so the interviewer's first question and the candidate's first answer both
arrived as ``seq=0``. ``final_utterances`` then broke the tie on utterance id,
``trk_candidate`` sorts before ``trk_interviewer``, and Q&A saw an answer
before any question had been asked and dropped it.
"""

import asyncio

import httpx
import pytest

from audio import silence, tone
from irya_ai.pipeline.qa_segmentation import segment_qa
from irya_ai.schemas.transcript import SpeakerRole, TranscriptSnapshot
from irya_ai.stt.elice import EliceSttClient
from irya_ai.stt.session import DEFAULT_CAPACITY, SessionOrdering, solo_ordering
from irya_ai.stt.stream import TranscriptionStream

TURN = tone(1500) + silence(800)


def ok(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "_result": {"status": "ok", "reason": None},
            "transcript": {
                "text": text,
                "chunks": [{"timestamp": [0.0, 1.5], "text": text}],
            },
        },
    )


def stream_for(handler, *, track_id, speaker, ordering, **kwargs):
    client = EliceSttClient(
        httpx.AsyncClient(
            base_url="https://stt.invalid", transport=httpx.MockTransport(handler)
        ),
        retries=0,
        backoff_seconds=0.0,
    )
    return TranscriptionStream(
        client,
        session_id="ses_test",
        track_id=track_id,
        speaker=speaker,
        ordering=ordering,
        **kwargs,
    )


# --- The mapping itself ------------------------------------------------------


def test_two_tracks_never_share_a_sequence_number() -> None:
    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    # The exact collision from the review: both speaking from 0ms.
    assert interviewer.seq(0) != candidate.seq(0)
    # Registration order decides the tie, not the track id.
    assert interviewer.seq(0) < candidate.seq(0)


def test_order_follows_the_audio_not_the_response() -> None:
    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    question = interviewer.seq(0)
    answer = candidate.seq(2460)
    later_question = interviewer.seq(9000)

    assert question < answer < later_question


def test_a_track_that_joins_late_sits_where_the_caller_put_it() -> None:
    ordering = SessionOrdering()
    early = ordering.register("trk_interviewer")
    late = ordering.register("trk_candidate", offset_ms=30_000)

    # 0ms on the late track is 30s into the session, after 10s on the early one.
    assert late.seq(0) > early.seq(10_000)
    assert late.session_ms(0) == 30_000


def test_the_same_segment_always_maps_to_the_same_number() -> None:
    """A revision recomputes ``seq``; an unstable one would trip the snapshot."""

    ordering = SessionOrdering()
    track = ordering.register("trk_candidate", offset_ms=1200)
    assert track.seq(4000) == track.seq(4000)
    assert ordering.register("trk_candidate", offset_ms=1200) is track


def test_registering_a_track_somewhere_else_is_refused() -> None:
    ordering = SessionOrdering()
    ordering.register("trk_candidate", offset_ms=1200)
    with pytest.raises(ValueError, match="already placed"):
        ordering.register("trk_candidate", offset_ms=0)


@pytest.mark.parametrize(
    ("track_id", "offset_ms", "match"),
    [
        ("", 0, "must not be empty"),
        ("trk_candidate", -1, "must not be negative"),
    ],
)
def test_a_track_that_cannot_be_placed_is_refused(track_id, offset_ms, match) -> None:
    with pytest.raises(ValueError, match=match):
        SessionOrdering().register(track_id, offset_ms=offset_ms)


def test_a_session_orders_no_more_tracks_than_it_has_room_for() -> None:
    ordering = SessionOrdering(capacity=2)
    ordering.register("trk_a")
    ordering.register("trk_b")
    with pytest.raises(ValueError, match="at most 2"):
        ordering.register("trk_c")


def test_a_capacity_that_cannot_hold_a_track_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        SessionOrdering(capacity=0)


def test_every_number_a_full_session_can_produce_is_unique() -> None:
    ordering = SessionOrdering(capacity=4)
    tracks = [ordering.register(f"trk_{i}") for i in range(4)]
    starts = [0, 1, 2, 999, 1000, 2460, 60_000]
    numbers = [track.seq(start) for track in tracks for start in starts]

    assert len(set(numbers)) == len(numbers)
    assert all(n >= 0 for n in numbers)


def test_a_solo_track_needs_no_registry() -> None:
    solo = solo_ordering("trk_candidate")
    assert solo.track_id == "trk_candidate"
    assert solo.offset_ms == 0
    assert solo.capacity == DEFAULT_CAPACITY
    assert solo.seq(0) == 0


def test_a_stream_refuses_an_ordering_belonging_to_another_track() -> None:
    ordering = SessionOrdering().register("trk_interviewer")
    with pytest.raises(ValueError, match="ordering is for trk_interviewer"):
        stream_for(
            lambda request: ok("네"),
            track_id="trk_candidate",
            speaker=SpeakerRole.CANDIDATE,
            ordering=ordering,
        )


# --- Two speakers through the live path --------------------------------------


async def transcribe_turns(
    ordering, track_id, speaker, turns, handler, **kwargs
) -> list:
    """Run one track's audio through a stream and collect its utterances."""

    stream = stream_for(
        handler,
        track_id=track_id,
        speaker=speaker,
        ordering=ordering.register(track_id, **kwargs),
    )
    for turn in turns:
        stream.push(turn)
    stream.close()
    return await asyncio.wait_for(stream.drain(), timeout=5)


async def test_a_question_and_the_answer_to_it_keep_their_order() -> None:
    """The review's reproduction: question at 0ms, answer 2460ms later."""

    ordering = SessionOrdering()
    questions = await transcribe_turns(
        ordering,
        "trk_interviewer",
        SpeakerRole.INTERVIEWER,
        [tone(1500) + silence(800)],
        lambda request: ok("가장 어려웠던 문제는 무엇인가요?"),
    )
    answers = await transcribe_turns(
        ordering,
        "trk_candidate",
        SpeakerRole.CANDIDATE,
        # 2460ms of quiet before the candidate starts: the answer follows.
        [silence(2460) + tone(2000) + silence(800)],
        lambda request: ok("동시성 버그였습니다."),
    )

    assert len(questions) == 1 and len(answers) == 1
    assert questions[0].seq < answers[0].seq


async def test_a_delayed_response_does_not_reorder_the_transcript() -> None:
    """The candidate's request finishes first; the question still sorts first."""

    answered = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        await answered.wait()
        return ok("동시성 버그였습니다.")

    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    question_stream = stream_for(
        slow,
        track_id="trk_interviewer",
        speaker=SpeakerRole.INTERVIEWER,
        ordering=interviewer,
    )
    answer_stream = stream_for(
        lambda request: ok("동시성 버그였습니다."),
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        ordering=candidate,
    )
    question_stream.push(tone(1500) + silence(800))
    question_stream.close()
    answer_stream.push(silence(2460) + tone(2000) + silence(800))
    answer_stream.close()

    answers = await asyncio.wait_for(answer_stream.drain(), timeout=5)
    answered.set()
    questions = await asyncio.wait_for(question_stream.drain(), timeout=5)

    assert questions[0].seq < answers[0].seq


async def test_several_segments_of_one_answer_stay_inside_it() -> None:
    """A long answer cut into pieces sorts between the two questions."""

    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    first_question = stream_for(
        lambda request: ok("첫 질문입니다, 어떤가요?"),
        track_id="trk_interviewer",
        speaker=SpeakerRole.INTERVIEWER,
        ordering=interviewer,
    )
    first_question.push(tone(1200) + silence(800))
    first_question.close()
    questions = await asyncio.wait_for(first_question.drain(), timeout=5)

    answer = stream_for(
        lambda request: ok("이어지는 답변입니다."),
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        ordering=candidate,
    )
    answer.push(silence(2100) + tone(1500) + silence(800))
    answer.push(tone(1500) + silence(800))
    answer.push(tone(1500) + silence(800))
    answer.close()
    parts = await asyncio.wait_for(answer.drain(), timeout=5)

    assert len(parts) == 3
    seqs = [u.seq for u in parts]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 3
    assert all(u.seq > questions[0].seq for u in parts)


async def test_a_rejected_chunk_does_not_shift_what_came_after_it() -> None:
    """The numbering is a function of the audio, so a hole leaves no gap."""

    def handler(request: httpx.Request) -> httpx.Response:
        if b'filename="seg_0001.wav"' in request.content:
            return httpx.Response(500, json={"_result": {"status": "error"}})
        return ok("남은 말")

    ordering = SessionOrdering()
    interviewer = ordering.register("trk_interviewer")
    candidate = ordering.register("trk_candidate")

    candidate_stream = stream_for(
        handler,
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        ordering=candidate,
    )
    candidate_stream.push(TURN * 3)
    candidate_stream.close()
    kept = await asyncio.wait_for(candidate_stream.drain(), timeout=5)

    assert len(kept) == 2
    assert [r.reason for r in candidate_stream.rejected] == ["REQUEST_FAILED"]
    # The survivors keep both their order and the numbers they would have had.
    assert kept[0].seq == candidate.seq(kept[0].start_ms)
    assert kept[1].seq == candidate.seq(kept[1].start_ms)
    assert kept[0].seq < kept[1].seq
    assert interviewer.seq(0) < kept[0].seq


async def test_unequal_start_times_place_the_late_track_late() -> None:
    """The caller's ``offset_ms``, not the first pushed sample, sets the clock."""

    ordering = SessionOrdering()
    early = await transcribe_turns(
        ordering,
        "trk_interviewer",
        SpeakerRole.INTERVIEWER,
        [TURN],
        lambda request: ok("먼저 말한 쪽"),
    )
    late = await transcribe_turns(
        ordering,
        "trk_candidate",
        SpeakerRole.CANDIDATE,
        # Same track-local audio: without the offset both would start at 0ms.
        [TURN],
        lambda request: ok("30초 뒤에 들어온 쪽"),
        offset_ms=30_000,
    )

    assert early[0].start_ms == 0
    assert late[0].start_ms == 30_000
    assert early[0].seq < late[0].seq


# --- Through to Q&A ----------------------------------------------------------


async def test_qa_reads_the_interview_in_the_order_it_was_spoken() -> None:
    """End to end: two tracks, one snapshot, a question paired to its answer."""

    ordering = SessionOrdering()
    questions = await transcribe_turns(
        ordering,
        "trk_interviewer",
        SpeakerRole.INTERVIEWER,
        [tone(1500) + silence(800)],
        lambda request: ok("가장 어려웠던 문제는 무엇인가요?"),
    )
    answers = await transcribe_turns(
        ordering,
        "trk_candidate",
        SpeakerRole.CANDIDATE,
        [silence(2460) + tone(2000) + silence(800)],
        lambda request: ok("동시성 버그를 재현해서 고쳤습니다."),
    )

    snapshot = TranscriptSnapshot(
        session_id="ses_test",
        # Deliberately in the wrong order: the snapshot must sort it out.
        utterances=answers + questions,
    )
    result = segment_qa(snapshot.final_utterances())

    assert result.dropped == []
    assert len(result.qa_pairs) == 1
    pair = result.qa_pairs[0]
    assert pair.question_text == "가장 어려웠던 문제는 무엇인가요?"
    assert pair.answer_text == "동시성 버그를 재현해서 고쳤습니다."


async def test_a_revision_of_an_utterance_keeps_its_identity() -> None:
    """Recomputed ``seq`` must match, or the snapshot rejects the revision."""

    ordering = SessionOrdering()
    utterances = await transcribe_turns(
        ordering,
        "trk_candidate",
        SpeakerRole.CANDIDATE,
        [TURN],
        lambda request: ok("첫 번째 판독"),
        offset_ms=4200,
    )
    original = utterances[0]
    revised = original.model_copy(update={"content": "고쳐 쓴 판독"})

    snapshot = TranscriptSnapshot(session_id="ses_test", utterances=[original, revised])
    finals = snapshot.final_utterances()
    assert len(finals) == 1
    assert finals[0].content == "고쳐 쓴 판독"
    assert finals[0].seq == ordering.register("trk_candidate", offset_ms=4200).seq(
        original.start_ms - 4200
    )
