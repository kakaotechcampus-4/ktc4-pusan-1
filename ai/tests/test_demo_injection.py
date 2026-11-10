"""Stage-demo injection: what it builds, what it refuses, and where it lands.

The point of the feature is that an injected answer is indistinguishable from
a transcribed one *downstream*, so the tests that matter are the ones about
the utterance's shape and its place on the timeline - a wrong ``seq`` breaks
Q&A pairing without any error - and the ones about refusing a packet that did
not come from the backend.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from irya_ai.demo_injection import (
    DEMO_TOPIC,
    DEMO_TRACK_ID,
    MAX_CONTENT_CHARS,
    DemoInjector,
    allowed_sessions,
    attach_demo_injector,
    estimated_duration_ms,
    parse_packet,
)
from irya_ai.pipeline.qa_segmentation import QASegmenter
from irya_ai.schemas.transcript import PassType, SpeakerRole, Utterance
from irya_ai.stt.rtc_bridge import RoomTranscriber

ORIGIN = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)

#: 이 방이 데모 세션이라는 설정. 목록에 없으면 핸들러가 붙지 않는다.
ALLOWED = frozenset({"ses_demo"})

#: 주입된 발화의 id 는 놓인 밀리초에서 나온다. e2e 시험은 7초에 넣는다.
_DEMO_ID = f"utt_{DEMO_TRACK_ID}_00007000"


class FakeSttClient:
    """Enough of ``EliceSttClient`` for ``RoomTranscriber`` to accept it."""


@dataclass
class FakeParticipant:
    identity: str


@dataclass
class FakePacket:
    data: bytes
    topic: str | None
    participant: FakeParticipant | None = None


class FakeRoom:
    """Records ``on`` registrations so a test can fire the handler itself."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, event: str, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def fire(self, event: str, *args) -> None:
        for handler in self.handlers.get(event, []):
            handler(*args)


def build_transcriber(*, now: datetime = ORIGIN, origin: bool = True):
    """A transcriber with a clock a test controls, and sinks that collect."""

    received: list[Utterance] = []

    async def collect(utterance: Utterance) -> None:
        received.append(utterance)

    clock = {"now": now}
    transcriber = RoomTranscriber(
        room=FakeRoom(),
        session_id="ses_demo",
        client=FakeSttClient(),
        sinks=[collect],
        wall_clock=lambda: clock["now"],
    )
    if origin:
        transcriber._origin_at = ORIGIN
    return transcriber, received, clock


# --- the packet ------------------------------------------------------------


def test_parse_packet_reads_the_agreed_shape() -> None:
    payload = json.dumps(
        {"type": "demo.utterance", "content": "  초당 2만 건까지 올렸습니다.  "}
    ).encode()
    assert parse_packet(payload) == "초당 2만 건까지 올렸습니다."


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'"a string, not an object"',
        b"[1, 2, 3]",
        json.dumps({"type": "something.else", "content": "x"}).encode(),
        json.dumps({"type": "demo.utterance"}).encode(),
        json.dumps({"type": "demo.utterance", "content": 42}).encode(),
        json.dumps({"type": "demo.utterance", "content": "   "}).encode(),
        b"\xff\xfe not utf-8",
    ],
    ids=[
        "not-json",
        "not-an-object",
        "a-list",
        "wrong-type",
        "no-content",
        "content-not-a-string",
        "blank-content",
        "not-utf8",
    ],
)
def test_parse_packet_refuses_anything_else(payload: bytes) -> None:
    assert parse_packet(payload) is None


def test_parse_packet_refuses_content_over_the_limit() -> None:
    content = "가" * (MAX_CONTENT_CHARS + 1)
    payload = json.dumps({"type": "demo.utterance", "content": content}).encode()
    assert parse_packet(payload) is None


def test_estimated_duration_is_never_zero() -> None:
    assert estimated_duration_ms("가") >= 1
    # Roughly seconds, not milliseconds or minutes: a 55-character answer
    # should land near ten seconds at 5.5 chars/s.
    assert 9_000 <= estimated_duration_ms("가" * 55) <= 11_000


# --- the utterance ---------------------------------------------------------


def test_injected_utterance_is_a_final_candidate_utterance() -> None:
    transcriber, _, _ = build_transcriber()
    injector = DemoInjector(transcriber, sink=_null_sink)

    utterance = injector.build("초당 2만 건까지 올렸습니다.", at_ms=12_000)

    assert utterance.speaker is SpeakerRole.CANDIDATE
    assert utterance.pass_type is PassType.FINAL
    assert utterance.is_final
    assert utterance.session_id == "ses_demo"
    assert utterance.track_id == DEMO_TRACK_ID
    assert utterance.start_ms == 12_000
    assert utterance.end_ms > utterance.start_ms
    assert utterance.content == "초당 2만 건까지 올렸습니다."


def test_successive_injections_get_distinct_ids_in_order() -> None:
    transcriber, _, _ = build_transcriber()
    injector = DemoInjector(transcriber, sink=_null_sink)

    first = injector.build("첫 번째 답변입니다.", at_ms=1_000)
    second = injector.build("두 번째 답변입니다.", at_ms=2_000)

    assert first.utterance_id != second.utterance_id
    assert first.seq < second.seq


def test_the_id_says_it_is_a_demo_utterance() -> None:
    """읽는 사람이 전사에서 이게 주입된 것임을 알 수 있어야 한다."""

    transcriber, _, _ = build_transcriber()
    injector = DemoInjector(transcriber, sink=_null_sink)

    utterance = injector.build("답변입니다.", at_ms=1_000)

    assert "demo" in utterance.utterance_id
    assert "demo" in utterance.track_id


def test_the_id_is_a_pure_function_of_the_placement() -> None:
    """id 가 놓인 밀리초만으로 정해진다 — 세어 둔 횟수가 섞이지 않는다.

    색인으로 만들면 재시작한 주입기가 ``_0000`` 부터 다시 내주고, BE 의 upsert 가
    먼저 저장된 답변을 덮어쓴다. 그래서 봐야 하는 성질은 「다른 밀리초면 다른 id」가
    아니라 — 그건 밀리초가 들어간 어떤 형식이든 만족한다 — **같은 밀리초면 몇 번째
    주입이든 같은 id** 라는 쪽이다.
    """

    transcriber, _, _ = build_transcriber()
    first_run = DemoInjector(transcriber, sink=_null_sink)
    after_restart = DemoInjector(transcriber, sink=_null_sink)

    # 재시작 전의 세 번째 주입과 재시작 후의 첫 주입이 같은 자리에 놓이면 같은 id 다.
    first_run.build("첫 번째입니다.", at_ms=1_000)
    first_run.build("두 번째입니다.", at_ms=2_000)
    third = first_run.build("세 번째입니다.", at_ms=3_000)
    after = after_restart.build("재시작 뒤 첫 번째입니다.", at_ms=3_000)

    assert third.utterance_id == after.utterance_id
    assert third.seq == after.seq
    # 그리고 다른 자리는 다른 id 다.
    assert after_restart.build("다른 자리입니다.", at_ms=4_000).utterance_id != (
        third.utterance_id
    )


def test_the_demo_track_registers_once() -> None:
    """A second injection must not raise on re-registering the same track."""

    transcriber, _, _ = build_transcriber()
    injector = DemoInjector(transcriber, sink=_null_sink)

    injector.build("첫 번째 답변입니다.", at_ms=1_000)
    injector.build("두 번째 답변입니다.", at_ms=2_000)

    assert [t.track_id for t in transcriber.ordering.tracks] == [DEMO_TRACK_ID]


def test_the_answer_sorts_after_a_question_asked_at_the_same_moment() -> None:
    """``seq`` has to place the answer second, or Q&A sees an orphan answer.

    The interviewer's microphone registers first in a real room, so the demo
    track's ordinal must break the tie in the question's favour.
    """

    transcriber, _, _ = build_transcriber()
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    injector = DemoInjector(transcriber, sink=_null_sink)

    answer = injector.build("초당 2만 건까지 올렸습니다.", at_ms=5_000)
    question_seq = interviewer.seq(5_000)

    assert question_seq < answer.seq


def test_an_injected_answer_pairs_with_a_spoken_question() -> None:
    """The whole point, at the segmenter: one real question, one injected answer."""

    transcriber, _, _ = build_transcriber()
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    injector = DemoInjector(transcriber, sink=_null_sink)

    question = Utterance(
        utterance_id="utt_trk_interviewer_0000",
        session_id="ses_demo",
        track_id="trk_interviewer",
        speaker=SpeakerRole.INTERVIEWER,
        seq=interviewer.seq(2_000),
        start_ms=2_000,
        end_ms=6_000,
        content="그 트래픽에서 가장 먼저 막힌 병목은 어떤 것이었나요?",
    )
    answer = injector.build(
        "읽기 쪽 커넥션 풀이 먼저 말라서 초당 2만 건에서 응답이 밀렸습니다.",
        at_ms=7_000,
    )

    segmenter = QASegmenter()
    segmenter.feed(question)
    segmenter.feed(answer)
    pair = segmenter.current()

    assert pair is not None
    assert answer.utterance_id in pair.answer_utterance_ids
    assert "병목" in pair.question_text


# --- injecting -------------------------------------------------------------


@pytest.mark.asyncio
async def test_inject_hands_the_utterance_to_the_sink() -> None:
    transcriber, received, clock = build_transcriber()
    clock["now"] = ORIGIN + timedelta(seconds=9)
    injector = DemoInjector(transcriber, sink=_collect_into(received))

    utterance = await injector.inject("초당 2만 건까지 올렸습니다.")

    assert utterance is not None
    assert received == [utterance]
    assert utterance.start_ms == 9_000
    assert injector.injected == 1


@pytest.mark.asyncio
async def test_inject_drops_the_answer_before_the_timeline_exists() -> None:
    transcriber, received, _ = build_transcriber(origin=False)
    injector = DemoInjector(transcriber, sink=_collect_into(received))

    assert await injector.inject("초당 2만 건까지 올렸습니다.") is None
    assert received == []
    assert injector.refused == 1


# --- the room handler ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_server_packet_on_the_demo_topic_is_injected() -> None:
    transcriber, received, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    room.fire(
        "data_received",
        FakePacket(
            data=json.dumps(
                {"type": "demo.utterance", "content": "초당 2만 건까지 올렸습니다."}
            ).encode(),
            topic=DEMO_TOPIC,
        ),
    )
    await _drain()

    assert [u.content for u in received] == ["초당 2만 건까지 올렸습니다."]


@pytest.mark.asyncio
async def test_a_participant_packet_is_refused() -> None:
    """Only the backend may inject. A human token must not be able to.

    Human tokens are issued without ``can_publish_data``, so this cannot
    happen today; the check is what keeps it from becoming possible by a
    one-line change to the grants.
    """

    transcriber, received, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    room.fire(
        "data_received",
        FakePacket(
            data=json.dumps(
                {"type": "demo.utterance", "content": "주입을 시도합니다."}
            ).encode(),
            topic=DEMO_TOPIC,
            participant=FakeParticipant(identity="INTERVIEWER"),
        ),
    )
    await _drain()

    assert received == []
    assert injector.refused == 1


@pytest.mark.asyncio
async def test_other_topics_are_left_alone() -> None:
    transcriber, received, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    room.fire(
        "data_received",
        FakePacket(data=b"{}", topic="irya.suggestion.v1"),
    )
    await _drain()

    assert received == []
    assert injector.refused == 0


@pytest.mark.asyncio
async def test_a_malformed_packet_does_not_reach_the_sink() -> None:
    transcriber, received, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    room.fire("data_received", FakePacket(data=b"not json", topic=DEMO_TOPIC))
    await _drain()

    assert received == []
    assert injector.refused == 1


def test_disabled_registers_no_handler_at_all() -> None:
    transcriber, _, _ = build_transcriber()
    room = FakeRoom()

    assert (
        attach_demo_injector(room, transcriber, enabled=False, sessions=ALLOWED) is None
    )
    assert room.handlers == {}


@pytest.mark.asyncio
async def test_injection_reaches_every_sink_the_worker_installed_later() -> None:
    """The injector must read ``sinks`` live, not copy it at attach time.

    The worker attaches the injector after replacing ``sinks`` with its
    fan-out, but a future reordering must not silently reduce the demo to
    captions only.
    """

    transcriber, first, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    second: list[Utterance] = []
    transcriber.sinks = [_collect_into(first), _collect_into(second)]

    await injector.inject("초당 2만 건까지 올렸습니다.")

    assert len(first) == 1
    assert len(second) == 1


# --- helpers ---------------------------------------------------------------


async def _null_sink(utterance: Utterance) -> None:
    return None


def _collect_into(bucket: list[Utterance]):
    async def sink(utterance: Utterance) -> None:
        bucket.append(utterance)

    return sink


async def _drain() -> None:
    """Let the fire-and-forget injection task run."""

    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_the_demo_track_joins_a_two_microphone_session_last() -> None:
    """실제 방과 같은 순서로 등록됐을 때 데모 트랙이 마지막 서수를 받는다.

    앞의 `len(tracks) == 3` 만 보던 시험은 정원이 16 이라 깨질 수 없었다. 여기서는
    방이 쓰는 그 ordering 에 등록하고, 같은 밀리초에서 **질문이 답변보다 먼저**
    정렬되는지를 본다 — Q&A 가 기대하는 방향이다.
    """

    transcriber, _, _ = build_transcriber()
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    candidate = transcriber.ordering.register("trk_candidate", offset_ms=0)
    injector = DemoInjector(transcriber, sink=_null_sink)

    answer = injector.build("답변입니다.", at_ms=5_000)

    assert [t.track_id for t in transcriber.ordering.tracks] == [
        "trk_interviewer",
        "trk_candidate",
        DEMO_TRACK_ID,
    ]
    assert interviewer.seq(5_000) < answer.seq
    assert candidate.seq(5_000) < answer.seq


# --- end to end: a spoken question, an injected answer, a real round --------


@pytest.mark.asyncio
async def test_an_injected_answer_produces_a_posted_follow_up() -> None:
    """The whole chain, with the generator stubbed and nothing else.

    This is the claim the presenter makes on stage, as a test: the question is
    a real transcribed utterance, the answer is injected, and the follow-up
    comes out of the production wiring - the same fan-out, the same runner, the
    same grounding checks - and is posted to the Backend.

    Only the model is a stand-in. Its draft has to cite the injected answer
    verbatim or ``_verify_evidence`` drops it, which is exactly the behaviour
    being relied on.
    """

    from irya_ai.schemas import (
        CitationDraft,
        SuggestionBatchDraft,
        SuggestionDraft,
        SuggestionPayload,
    )
    from irya_ai.sinks import FanOutSink
    from irya_ai.suggestion_runner import SuggestionRunner
    from irya_ai.suggestions import FakeSuggestionGenerator, LiveSuggestionAgent

    answer_text = (
        "읽기 쪽 커넥션 풀이 먼저 말라서 초당 2만 건에서 응답이 밀렸습니다. "
        "풀 크기를 20에서 80으로 올렸습니다."
    )
    # 인용은 꼬리질문이 쓴 숫자까지 받쳐 줘야 한다. 「80」이 들어간 꼬리질문을
    # 「...먼저 말라서」만 인용하면 ``unsupported_numbers_in_text`` 가 버린다 —
    # 아래 test_a_number_the_quote_does_not_support_is_dropped 가 그 경우다.
    quote = "풀 크기를 20에서 80으로 올렸습니다"

    posted: list[SuggestionPayload] = []

    async def post(session_id: str, payload: SuggestionPayload) -> None:
        posted.append(payload)

    generator = FakeSuggestionGenerator(
        SuggestionBatchDraft(
            suggestions=[
                SuggestionDraft(
                    content="풀 크기를 80으로 정한 근거는 무엇이었나요?",
                    reason="커넥션 풀 조정의 근거를 확인한다.",
                    evidence=[CitationDraft(utterance_id=_DEMO_ID, quote=quote)],
                )
            ]
        )
    )
    agent = LiveSuggestionAgent(generator, model="fake")
    runner = SuggestionRunner(agent, session_id="ses_demo", post=post)
    runner.start()

    transcriber, captions, clock = build_transcriber()
    # The worker's wiring: captions first, then the follow-up loop, behind the
    # fan-out that isolates one consumer's failure from the others.
    transcriber.sinks = [FanOutSink([_collect_into(captions), runner])]
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    injector = attach_demo_injector(
        FakeRoom(), transcriber, enabled=True, sessions=ALLOWED
    )
    assert injector is not None

    # The interviewer really said this; it came off the microphone.
    question = Utterance(
        utterance_id="utt_trk_interviewer_0000",
        session_id="ses_demo",
        track_id="trk_interviewer",
        speaker=SpeakerRole.INTERVIEWER,
        seq=interviewer.seq(2_000),
        start_ms=2_000,
        end_ms=6_000,
        content="그 트래픽에서 가장 먼저 막힌 병목은 어떤 것이었나요?",
    )
    await transcriber.sinks[0](question)

    # The presenter presses the key.
    clock["now"] = ORIGIN + timedelta(seconds=7)
    answer = await injector.inject(answer_text)
    assert answer is not None
    assert answer.utterance_id == _DEMO_ID

    await runner.stop()

    # The caption saw both, in spoken order.
    assert [u.speaker for u in captions] == [
        SpeakerRole.INTERVIEWER,
        SpeakerRole.CANDIDATE,
    ]
    # The round ran on the pair and the follow-up went to the Backend.
    assert generator.calls, "모델이 호출되지 않았습니다 — 짝이 안 맞은 것입니다"
    assert [p.content for p in posted] == ["풀 크기를 80으로 정한 근거는 무엇이었나요?"]
    assert posted[0].evidence_utterance_ids == [_DEMO_ID]


@pytest.mark.asyncio
async def test_a_follow_up_that_misquotes_the_injected_answer_is_dropped() -> None:
    """Grounding is not relaxed for an injected answer.

    A quote that is not a verbatim substring is refused here exactly as it is
    in an interview, so the presenter's claim about the guardrail holds for
    what the audience is watching.
    """

    from irya_ai.schemas import (
        CitationDraft,
        SuggestionBatchDraft,
        SuggestionDraft,
        SuggestionPayload,
    )
    from irya_ai.sinks import FanOutSink
    from irya_ai.suggestion_runner import SuggestionRunner
    from irya_ai.suggestions import FakeSuggestionGenerator, LiveSuggestionAgent

    posted: list[SuggestionPayload] = []

    async def post(session_id: str, payload: SuggestionPayload) -> None:
        posted.append(payload)

    generator = FakeSuggestionGenerator(
        SuggestionBatchDraft(
            suggestions=[
                SuggestionDraft(
                    content="그 수치는 어떻게 측정했나요?",
                    reason="측정 방법을 확인한다.",
                    evidence=[
                        CitationDraft(
                            utterance_id=_DEMO_ID,
                            # 답변에 없는 말이다 — 뜻은 같아도 글자가 다르다.
                            quote="커넥션 풀이 고갈되었습니다",
                        )
                    ],
                )
            ]
        )
    )
    agent = LiveSuggestionAgent(generator, model="fake")
    runner = SuggestionRunner(agent, session_id="ses_demo", post=post)
    runner.start()

    transcriber, _, clock = build_transcriber()
    transcriber.sinks = [FanOutSink([runner])]
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    injector = attach_demo_injector(
        FakeRoom(), transcriber, enabled=True, sessions=ALLOWED
    )
    assert injector is not None

    await transcriber.sinks[0](
        Utterance(
            utterance_id="utt_trk_interviewer_0000",
            session_id="ses_demo",
            track_id="trk_interviewer",
            speaker=SpeakerRole.INTERVIEWER,
            seq=interviewer.seq(2_000),
            start_ms=2_000,
            end_ms=6_000,
            content="그 트래픽에서 가장 먼저 막힌 병목은 어떤 것이었나요?",
        )
    )
    clock["now"] = ORIGIN + timedelta(seconds=7)
    await injector.inject(
        "읽기 쪽 커넥션 풀이 먼저 말라서 초당 2만 건에서 응답이 밀렸습니다. "
        "풀 크기를 20에서 80으로 올렸습니다."
    )
    await runner.stop()

    assert generator.calls, "모델이 호출되지 않았습니다"
    assert posted == [], "인용이 글자 그대로가 아닌데 저장됐습니다"


@pytest.mark.asyncio
async def test_a_number_the_quote_does_not_support_is_dropped() -> None:
    """A figure the evidence does not contain is refused, injection or not.

    This is the deck's loudest claim - "we check the numbers inside the
    follow-up too" - exercised against injected speech. It is also the case
    the first draft of these tests got wrong, which is the point: the check
    bites whether or not the author meant it to.
    """

    from irya_ai.schemas import (
        CitationDraft,
        SuggestionBatchDraft,
        SuggestionDraft,
        SuggestionPayload,
    )
    from irya_ai.sinks import FanOutSink
    from irya_ai.suggestion_runner import SuggestionRunner
    from irya_ai.suggestions import FakeSuggestionGenerator, LiveSuggestionAgent

    posted: list[SuggestionPayload] = []

    async def post(session_id: str, payload: SuggestionPayload) -> None:
        posted.append(payload)

    generator = FakeSuggestionGenerator(
        SuggestionBatchDraft(
            suggestions=[
                SuggestionDraft(
                    # 「80」은 아래 인용에도, 질문에도 없다.
                    content="풀 크기를 80으로 정한 근거는 무엇이었나요?",
                    reason="커넥션 풀 조정의 근거를 확인한다.",
                    evidence=[
                        CitationDraft(
                            utterance_id=_DEMO_ID,
                            quote="읽기 쪽 커넥션 풀이 먼저 말라서",
                        )
                    ],
                )
            ]
        )
    )
    agent = LiveSuggestionAgent(generator, model="fake")
    runner = SuggestionRunner(agent, session_id="ses_demo", post=post)
    runner.start()

    transcriber, _, clock = build_transcriber()
    transcriber.sinks = [FanOutSink([runner])]
    interviewer = transcriber.ordering.register("trk_interviewer", offset_ms=0)
    injector = attach_demo_injector(
        FakeRoom(), transcriber, enabled=True, sessions=ALLOWED
    )
    assert injector is not None

    await transcriber.sinks[0](
        Utterance(
            utterance_id="utt_trk_interviewer_0000",
            session_id="ses_demo",
            track_id="trk_interviewer",
            speaker=SpeakerRole.INTERVIEWER,
            seq=interviewer.seq(2_000),
            start_ms=2_000,
            end_ms=6_000,
            content="그 트래픽에서 가장 먼저 막힌 병목은 어떤 것이었나요?",
        )
    )
    clock["now"] = ORIGIN + timedelta(seconds=7)
    await injector.inject(
        "읽기 쪽 커넥션 풀이 먼저 말라서 초당 2만 건에서 응답이 밀렸습니다. "
        "풀 크기를 20에서 80으로 올렸습니다."
    )
    await runner.stop()

    assert generator.calls, "모델이 호출되지 않았습니다"
    assert posted == [], "인용이 받쳐 주지 않는 숫자가 저장됐습니다"
    [result] = runner.results
    assert any("80" in reason for reason in result.rejections), result.rejections


# --- which rooms this can happen in ---------------------------------------


#: BE·AI·브라우저가 같게 읽어야 하는 입력들. 세 쪽에 같은 목록을 둔다 —
#: 한쪽만 고치면 「BE 는 허용하는데 Agent 는 핸들러를 안 붙인다」가 되고, 그때
#: BE 는 204 를 주면서 아무 일도 일어나지 않는다.
SESSION_LIST_CASES = [
    ("", []),
    ("   ", []),
    (",,", []),
    ("ses_a", ["ses_a"]),
    (" ses_a , ses_b ", ["ses_a", "ses_b"]),
    # 브라우저 쪽은 JSON 배열을 받는다. 서버 env 에 그 모양을 붙여넣는 실수가 나므로
    # 양쪽 모양을 다 받는다 — 안 받으면 조용히 404 만 나고 이유가 안 보인다.
    ('["ses_a","ses_b"]', ["ses_a", "ses_b"]),
    ('["ses_a"]', ["ses_a"]),
    ("['ses_a']", ["ses_a"]),
    ('"ses_a"', ["ses_a"]),
    # 와일드카드는 없다. 그런 이름의 세션 id 로 읽히고 아무것과도 안 맞는다.
    ("*", ["*"]),
    ("all", ["all"]),
    # 구분자를 잘못 적으면 쓸모없는 id 한 개 — 닫히는 쪽이다.
    ("ses_a;ses_b", ["ses_a;ses_b"]),
]


@pytest.mark.parametrize(("raw", "expected"), SESSION_LIST_CASES)
def test_allowed_sessions_reads_the_list(raw: str, expected: list[str]) -> None:
    """BE 의 `Settings.demo_injection_session_ids` 와 **같은 결과**여야 한다.

    두 쪽이 갈리면 BE 가 허용한 세션에 Agent 가 핸들러를 안 붙이고, 그때 BE 는 204
    를 주면서 아무 일도 일어나지 않는다 — 무대에서 가장 알아차리기 어려운 고장이다.
    BE 쪽 같은 이름의 시험이 같은 목록을 쓴다.
    """

    assert allowed_sessions(raw) == frozenset(expected)


def test_a_room_that_is_not_the_demo_session_gets_no_handler() -> None:
    """이게 리뷰가 잡은 것이다. 플래그만으로는 모든 면접이 열려 있었다.

    목록에 없는 방에는 핸들러 자체가 붙지 않으므로, 그 방의 면접관이 키를 눌러도
    패킷이 파싱조차 되지 않는다.
    """

    transcriber, _, _ = build_transcriber()
    room = FakeRoom()

    injector = attach_demo_injector(
        room, transcriber, enabled=True, sessions=frozenset({"ses_other"})
    )

    assert injector is None
    assert room.handlers == {}


def test_an_empty_list_opens_no_room_even_when_enabled() -> None:
    """실패는 닫히는 쪽으로. 세션을 적는 걸 잊어도 전체가 열리지 않는다."""

    transcriber, _, _ = build_transcriber()
    room = FakeRoom()

    assert attach_demo_injector(room, transcriber, enabled=True) is None
    assert (
        attach_demo_injector(room, transcriber, enabled=True, sessions=frozenset())
        is None
    )
    assert room.handlers == {}


# --- the timeline stays sound ---------------------------------------------


@pytest.mark.asyncio
async def test_two_injections_in_the_same_millisecond_stay_distinct() -> None:
    """``seq`` 는 유일해야 한다 (`stt/session.py`). 같은 밀리초면 한 칸 밀어 둔다."""

    transcriber, received, clock = build_transcriber()
    clock["now"] = ORIGIN + timedelta(seconds=7)
    injector = DemoInjector(transcriber, sink=_collect_into(received))

    first = await injector.inject("첫 번째 답변입니다.")
    second = await injector.inject("두 번째 답변입니다.")

    assert first is not None and second is not None
    assert first.seq < second.seq
    assert first.utterance_id != second.utterance_id
    assert second.start_ms == first.start_ms + 1


@pytest.mark.asyncio
async def test_a_clock_that_goes_backwards_does_not_reorder_the_transcript() -> None:
    transcriber, received, clock = build_transcriber()
    clock["now"] = ORIGIN + timedelta(seconds=9)
    injector = DemoInjector(transcriber, sink=_collect_into(received))

    first = await injector.inject("첫 번째 답변입니다.")
    clock["now"] = ORIGIN + timedelta(seconds=3)
    second = await injector.inject("두 번째 답변입니다.")

    assert first is not None and second is not None
    assert first.seq < second.seq


# --- in flight at shutdown ------------------------------------------------


@pytest.mark.asyncio
async def test_two_quick_presses_both_land() -> None:
    """두 번 빨리 누르면 둘 다 들어가야 한다.

    앞서는 진행 중인 작업을 한 칸에만 들고 있어서, 두 번째가 첫 번째의 참조를
    덮어썼다 — 수집되면 사라질 수 있는 상태였다.
    """

    transcriber, received, _ = build_transcriber()
    room = FakeRoom()
    injector = attach_demo_injector(room, transcriber, enabled=True, sessions=ALLOWED)
    assert injector is not None

    for content in ("첫 번째 답변입니다.", "두 번째 답변입니다."):
        room.fire(
            "data_received",
            FakePacket(
                data=json.dumps(
                    {"type": "demo.utterance", "content": content}
                ).encode(),
                topic=DEMO_TOPIC,
            ),
        )
    assert injector.in_flight == 2

    await injector.aclose()

    assert [u.content for u in received] == [
        "첫 번째 답변입니다.",
        "두 번째 답변입니다.",
    ]
    assert injector.in_flight == 0
    assert injector.injected == 2


@pytest.mark.asyncio
async def test_closing_an_idle_injector_is_a_no_op() -> None:
    transcriber, _, _ = build_transcriber()
    injector = attach_demo_injector(
        FakeRoom(), transcriber, enabled=True, sessions=ALLOWED
    )
    assert injector is not None

    await injector.aclose()

    assert injector.injected == 0


@pytest.mark.asyncio
async def test_closing_does_not_hang_on_a_sink_that_never_returns() -> None:
    """종료 경로다. 매달리면 작업 전체가 안 끝난다.

    LiveKit 은 종료 콜백들을 **자기 시간 제한 없이** 모은다
    (`agents/ipc/job_proc_lazy_main.py`). 그래서 여기서 끝없이 기다리면 그 방의
    작업이 영원히 안 닫힌다. 남은 작업은 작업의 다른 대기 작업과 함께 취소되게
    둔다.
    """

    transcriber, _, _ = build_transcriber()
    started = asyncio.Event()

    async def never_returns(utterance: Utterance) -> None:
        started.set()
        await asyncio.Event().wait()

    injector = DemoInjector(transcriber, sink=never_returns)
    task = asyncio.create_task(injector._inject_safely("답변입니다."))
    injector._pending.add(task)
    task.add_done_callback(injector._pending.discard)
    await started.wait()

    await asyncio.wait_for(injector.aclose(timeout=0.05), timeout=1.0)

    assert not task.done(), "남은 작업은 취소되지 않고 그대로 남는다"
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
