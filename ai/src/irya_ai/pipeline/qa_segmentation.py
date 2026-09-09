"""Rule-based Q&A segmentation driven by speaker transitions (TechSpec F4).

The speaker of every utterance is known from its audio track, so the
structure of the interview can be recovered without a model:

1. Drop interviewer back-channels ("네", "그렇군요") so they do not split a
   candidate's answer in two.
2. Merge consecutive FINAL utterances from the same speaker into one turn.
3. Every interviewer turn opens a new ``QAPair``; the candidate turn that
   follows is its answer. Interviewer turns that are neither questions nor
   answered (closing remarks) are dropped.

The output is deterministic, so it can be tested against golden data and
keeps working when the LLM is unavailable (TechSpec N4).
"""

import re
from dataclasses import dataclass, field

from irya_ai.schemas.analysis import QAPair
from irya_ai.schemas.transcript import SpeakerRole, Utterance

QUESTION_ROLE = "QUESTION"
ANSWER_ROLE = "ANSWER"

# Interrogative and request forms common in Korean interview speech.
_QUESTION_MARKERS = re.compile(
    r"(\?|나요|까요|세요|시죠|셨어요|셨나요|셨죠|건가요|주세요|주시겠|"
    r"부탁|말씀해|설명해|궁금|어떤|어떻게|무엇|뭐|왜|얼마나|있나요|있으세요)"
)
_STRIP = re.compile(r"[\s.,!?~…'\"]+")
_BACKCHANNEL_MAX_CHARS = 10


@dataclass(frozen=True, slots=True)
class _Turn:
    speaker: SpeakerRole
    utterances: tuple[Utterance, ...]

    @property
    def text(self) -> str:
        return " ".join(u.content for u in self.utterances)

    @property
    def start_ms(self) -> int:
        return self.utterances[0].start_ms

    @property
    def end_ms(self) -> int:
        return max(u.end_ms for u in self.utterances)


@dataclass(slots=True)
class SegmentationResult:
    """Q&A pairs plus the utterances annotated with ``qa_id`` / ``qa_role``."""

    qa_pairs: list[QAPair]
    utterances: list[Utterance]
    dropped: list[tuple[Utterance, str]] = field(default_factory=list)

    def by_qa_id(self, qa_id: str) -> QAPair | None:
        return next((p for p in self.qa_pairs if p.qa_id == qa_id), None)


def is_question(text: str) -> bool:
    """Heuristic: does this interviewer turn ask for something?"""

    return bool(_QUESTION_MARKERS.search(text))


def is_backchannel(text: str) -> bool:
    """Short interviewer acknowledgement that is not a question."""

    core = _STRIP.sub("", text)
    return len(core) <= _BACKCHANNEL_MAX_CHARS and not is_question(text)


def _merge_turns(utterances: list[Utterance]) -> list[_Turn]:
    turns: list[_Turn] = []
    for u in utterances:
        if turns and turns[-1].speaker is u.speaker:
            turns[-1] = _Turn(u.speaker, turns[-1].utterances + (u,))
        else:
            turns.append(_Turn(u.speaker, (u,)))
    return turns


def segment_qa(utterances: list[Utterance]) -> SegmentationResult:
    """Batch segmentation over FINAL utterances of one session."""

    finals = sorted((u for u in utterances if u.is_final), key=lambda u: u.seq)
    if not finals:
        return SegmentationResult(qa_pairs=[], utterances=[])
    session_id = finals[0].session_id
    dropped: list[tuple[Utterance, str]] = []

    # A short interviewer acknowledgement is only a back-channel when it sits
    # inside candidate speech. The same words at the start of an interviewer
    # turn ("알겠습니다. 그럼 ...") are part of the question and stay.
    kept: list[Utterance] = []
    for idx, u in enumerate(finals):
        prev_speaker = finals[idx - 1].speaker if idx > 0 else None
        next_speaker = finals[idx + 1].speaker if idx + 1 < len(finals) else None
        if (
            u.speaker is SpeakerRole.INTERVIEWER
            and is_backchannel(u.content)
            and next_speaker is SpeakerRole.CANDIDATE
            and prev_speaker is not SpeakerRole.INTERVIEWER
        ):
            dropped.append((u, "backchannel"))
        else:
            kept.append(u)

    turns = _merge_turns(kept)
    qa_pairs: list[QAPair] = []
    role_by_id: dict[str, tuple[str, str]] = {}

    i = 0
    while i < len(turns):
        turn = turns[i]
        if turn.speaker is SpeakerRole.CANDIDATE:
            for u in turn.utterances:
                dropped.append((u, "candidate speech before any question"))
            i += 1
            continue

        answer = turns[i + 1] if i + 1 < len(turns) else None
        if answer is not None and answer.speaker is not SpeakerRole.CANDIDATE:
            answer = None
        if answer is None and not is_question(turn.text):
            for u in turn.utterances:
                dropped.append((u, "unanswered non-question"))
            i += 1
            continue

        qa_id = f"qa_{turn.utterances[0].utterance_id}"
        answer_utts = answer.utterances if answer else ()
        answer_text = answer.text if answer else ""
        qa_pairs.append(
            QAPair(
                qa_id=qa_id,
                session_id=session_id,
                question_utterance_ids=[u.utterance_id for u in turn.utterances],
                answer_utterance_ids=[u.utterance_id for u in answer_utts],
                start_ms=turn.start_ms,
                end_ms=answer.end_ms if answer else turn.end_ms,
                answer_word_count=len(answer_text.split()),
                question_text=turn.text,
                answer_text=answer_text,
            )
        )
        for u in turn.utterances:
            role_by_id[u.utterance_id] = (qa_id, QUESTION_ROLE)
        for u in answer_utts:
            role_by_id[u.utterance_id] = (qa_id, ANSWER_ROLE)
        i += 2 if answer else 1

    annotated: list[Utterance] = []
    for u in finals:
        if u.utterance_id in role_by_id:
            qa_id, role = role_by_id[u.utterance_id]
            u = u.model_copy(update={"qa_id": qa_id, "qa_role": role})
        annotated.append(u)
    return SegmentationResult(qa_pairs=qa_pairs, utterances=annotated, dropped=dropped)


class QASegmenter:
    """Incremental wrapper for live use.

    Feed FINAL utterances as they arrive. ``feed`` returns the pairs that
    became closed by this utterance, i.e. pairs whose answer can no longer
    grow because a newer interviewer question has started. ``current``
    exposes the still-open pair, which is what the Live Agent looks at when
    deciding whether to suggest a follow-up question.
    """

    def __init__(self) -> None:
        self._finals: list[Utterance] = []
        self._emitted: set[str] = set()
        self._last: SegmentationResult = SegmentationResult([], [])

    def feed(self, utterance: Utterance) -> list[QAPair]:
        if not utterance.is_final:
            return []
        self._finals.append(utterance)
        self._last = segment_qa(self._finals)
        closed = self._last.qa_pairs[:-1]
        new = [p for p in closed if p.qa_id not in self._emitted]
        self._emitted.update(p.qa_id for p in new)
        return new

    def current(self) -> QAPair | None:
        pairs = self._last.qa_pairs
        return pairs[-1] if pairs else None

    def flush(self) -> list[QAPair]:
        """Close the last open pair at the end of the interview."""

        pairs = self._last.qa_pairs
        remaining = [p for p in pairs if p.qa_id not in self._emitted]
        self._emitted.update(p.qa_id for p in remaining)
        return remaining

    def result(self) -> SegmentationResult:
        return self._last
