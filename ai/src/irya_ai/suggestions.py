"""Live follow-up questions: an answer in progress -> grounded, sendable suggestions.

Runs *during* the interview, which is what separates this from
:mod:`irya_ai.timeline`. The timeline looks back over a finished transcript and
can afford to be slow; a follow-up question is only worth anything while the
interviewer is still sitting in front of the answer that prompted it.

That fixes the trigger. :class:`~irya_ai.pipeline.qa_segmentation.QASegmenter`
offers two hooks: ``feed`` hands back pairs that have just *closed*, and
``current`` exposes the one still open. A pair only closes once the interviewer
has asked the next question - by then the moment to follow up has passed - so
this module watches ``current`` instead and fires once the open answer is long
enough to have something in it (``MIN_ANSWER_WORDS``).

One round is not enough for a long answer: the first fires on the first
sentence or two, and an answer that turns a corner afterwards would get no
second look. So the agent runs again each time the open answer has grown by
``RERUN_WORDS`` since the last round, up to ``DEFAULT_MAX_ROUNDS_PER_ANSWER``
rounds and ``DEFAULT_MAX_PER_ANSWER`` kept suggestions per question. Earlier
suggestions stay; later rounds add beside them. How often is often enough, and
how many an interview may carry, are not settled with the team yet, so every
knob is a constructor argument with the constants below as defaults rather
than a setting - a value nobody has decided should not look like one somebody
configured.

Grounding follows :func:`irya_ai.timeline.build_timeline` exactly: every
citation must name a candidate utterance belonging to *this* answer, the quote
must occur in that utterance verbatim, and numbers in the question must appear
in the exchange it cites. A draft that fails any check is dropped whole.
"""

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol, runtime_checkable

from irya_ai.evaluation import unsupported_numbers_in_text
from irya_ai.pipeline.grounding import locate_quote
from irya_ai.pipeline.qa_segmentation import QASegmenter
from irya_ai.schemas.analysis import QAPair, SuggestedQuestion
from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.suggestion import (
    CONTENT_MAX_CHARS,
    REASON_MAX_CHARS,
    SuggestionBatchDraft,
    SuggestionDraft,
    SuggestionResult,
)
from irya_ai.schemas.summary import AnalysisError, CitationDraft
from irya_ai.schemas.timeline import LlmUsage
from irya_ai.schemas.transcript import SpeakerRole, Utterance

# Two questions fit beside a live interview at once; more is a list nobody reads.
DEFAULT_MAX_PER_ROUND = 2
# What one question may pile up over its rounds before the panel is a list.
DEFAULT_MAX_PER_ANSWER = 3
# A whole interview's budget, so a talkative session cannot bury the panel.
DEFAULT_MAX_PER_SESSION = 12
# Below this the candidate has said hello, not answered.
MIN_ANSWER_WORDS = 8
# An answer that has grown by this much since the last round has something
# new in it; anything less is the same answer, still being finished.
RERUN_WORDS = 8
# How many times one question is looked at. A two-minute answer gets three.
DEFAULT_MAX_ROUNDS_PER_ANSWER = 3
# Closed pairs handed to the model as context, so a follow-up the interviewer
# asked themselves still reads as one. Two covers a question and its follow-up.
RECENT_EXCHANGES = 2

_COLLAPSE = re.compile(r"\s+")


class SuggestionError(Exception):
    """A safe, structured failure; provider error bodies are never forwarded."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def utcnow() -> datetime:
    """Injectable clock, so a generated suggestion can be tested for its stamp."""

    return datetime.now(UTC)


# --- verification ----------------------------------------------------------


def _verify_evidence(
    citations: list[CitationDraft],
    pair: QAPair,
    sources: Mapping[str, Utterance],
) -> list[str] | str:
    """Cited utterance ids, or the reason the first bad citation fails.

    The quote never leaves this function. It exists so that a model naming an
    utterance has to show it read it; the agreed payload carries ids alone.
    """

    if not citations:
        return "no evidence"
    allowed = set(pair.answer_utterance_ids)
    ids: list[str] = []
    for c in citations:
        source = sources.get(c.utterance_id)
        if source is None:
            return f"unknown utterance {c.utterance_id}"
        if c.utterance_id not in allowed:
            return f"evidence {c.utterance_id} is not part of this answer"
        if source.speaker is not SpeakerRole.CANDIDATE:
            return f"evidence {c.utterance_id} is not candidate speech"
        if not c.quote.strip():
            return "empty quote"
        if not locate_quote(c.quote, [source]):
            return f"quote not found in {c.utterance_id}"
        if c.utterance_id not in ids:
            ids.append(c.utterance_id)
    return ids


def _quoted_context(citations: list[CitationDraft], pair: QAPair) -> str:
    """What the follow-up is allowed to have read: the question and the quotes.

    The interviewer's own question counts as source text - a follow-up that
    repeats a figure the interviewer just said is not inventing it.
    """

    return "\n".join([pair.question_text, *(c.quote for c in citations)])


def build_suggestions(
    pair: QAPair,
    draft: SuggestionBatchDraft,
    sources: Mapping[str, Utterance],
    *,
    generated_at: datetime,
    max_per_answer: int = DEFAULT_MAX_PER_ROUND,
    seen_contents: frozenset[str] = frozenset(),
    first_index: int = 1,
) -> tuple[list[SuggestedQuestion], list[str]]:
    """Turn model drafts into verified suggestions; report every rejection.

    Returns ``(suggestions, rejections)`` in the order the model listed them,
    capped at ``max_per_answer`` - the cap for *this batch*, whatever the
    caller has left to spend. ``seen_contents`` holds normalised content
    already suggested in this session, so the panel does not repeat itself
    when two answers circle the same ground. ``first_index`` is where the
    question ids start counting, so a later round on the same pair carries
    on from the earlier one instead of reissuing ``_1``.
    """

    if max_per_answer < 1:
        raise ValueError("max_per_answer must be at least 1")

    kept: list[SuggestedQuestion] = []
    rejections: list[str] = []
    seen = set(seen_contents)

    for index, d in enumerate(draft.suggestions, start=1):
        content = _COLLAPSE.sub(" ", d.content).strip()
        if not content:
            rejections.append(f"{index}: empty content")
            continue
        if len(content) > CONTENT_MAX_CHARS:
            rejections.append(f"{index}: content longer than {CONTENT_MAX_CHARS} chars")
            continue
        reason = _COLLAPSE.sub(" ", d.reason).strip()
        if not reason:
            rejections.append(f"{index}: empty reason")
            continue
        if len(reason) > REASON_MAX_CHARS:
            rejections.append(f"{index}: reason longer than {REASON_MAX_CHARS} chars")
            continue
        if content in seen:
            rejections.append(f"{index}: duplicate of an earlier suggestion")
            continue
        verified = _verify_evidence(d.evidence, pair, sources)
        if isinstance(verified, str):
            rejections.append(f"{index}: {verified}")
            continue
        quoted = _quoted_context(d.evidence, pair)
        if numbers := unsupported_numbers_in_text(quoted, content):
            joined = ", ".join(numbers)
            rejections.append(f"{index}: numbers not in evidence: {joined}")
            continue
        if len(kept) >= max_per_answer:
            rejections.append(f"{index}: over the {max_per_answer} per answer limit")
            continue
        seen.add(content)
        kept.append(
            SuggestedQuestion(
                question_id=f"sug_{pair.qa_id}_{first_index + len(kept)}",
                session_id=pair.session_id,
                qa_id=pair.qa_id,
                content=content,
                reason=reason,
                evidence_utterance_ids=verified,
                generated_at=generated_at,
            )
        )

    return kept, rejections


# --- generators ------------------------------------------------------------


@dataclass(frozen=True)
class RoundHistory:
    """What earlier rounds and earlier questions leave for this one to read.

    ``already_suggested`` is what this question's previous rounds kept, so a
    model asked again does not offer the same thing in other words.
    ``recent_exchanges`` are the closed pairs just before this one, oldest
    first: context for a follow-up the interviewer asked themselves, never a
    source of evidence - a suggestion still has to cite the open answer.
    """

    already_suggested: tuple[str, ...] = ()
    recent_exchanges: tuple[QAPair, ...] = ()


@runtime_checkable
class SuggestionGenerator(Protocol):
    """Writes the draft. Implementations must cite, never assert."""

    async def generate(
        self,
        pair: QAPair,
        sources: Mapping[str, Utterance],
        context: InterviewContext | None = None,
        history: RoundHistory | None = None,
    ) -> SuggestionBatchDraft: ...


_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")


class ExtractiveSuggestionGenerator:
    """Offline baseline: ask the candidate to expand on their own first sentence.

    Adds no information, so it is always grounded. It lets the pipeline run
    without a key and gives a model something to beat.
    """

    template = "{sentence} 부분을 더 구체적으로 설명해달라고 질문해보세요."

    async def generate(
        self,
        pair: QAPair,
        sources: Mapping[str, Utterance],
        context: InterviewContext | None = None,
        history: RoundHistory | None = None,
    ) -> SuggestionBatchDraft:
        for uid in pair.answer_utterance_ids:
            source = sources.get(uid)
            if source is None or not source.content.strip():
                continue
            sentence = _SENTENCE_END.split(source.content.strip(), maxsplit=1)[0]
            content = self.template.format(sentence=sentence)
            if len(content) > CONTENT_MAX_CHARS:
                room = CONTENT_MAX_CHARS - len(self.template.format(sentence=""))
                sentence = sentence[:room].strip()
                if not sentence:
                    continue
                content = self.template.format(sentence=sentence)
            return SuggestionBatchDraft(
                suggestions=[
                    SuggestionDraft(
                        content=content,
                        reason="지원자가 직접 말한 부분입니다.",
                        evidence=[CitationDraft(utterance_id=uid, quote=sentence)],
                    )
                ]
            )
        return SuggestionBatchDraft(suggestions=[])


class FakeSuggestionGenerator:
    """Test double that returns a preset draft for any input."""

    def __init__(self, draft: SuggestionBatchDraft) -> None:
        self.draft = draft
        self.calls: list[str] = []
        self.histories: list[RoundHistory | None] = []

    async def generate(
        self,
        pair: QAPair,
        sources: Mapping[str, Utterance],
        context: InterviewContext | None = None,
        history: RoundHistory | None = None,
    ) -> SuggestionBatchDraft:
        self.calls.append(pair.qa_id)
        self.histories.append(history)
        return self.draft


# --- agent -----------------------------------------------------------------


@dataclass
class RoundState:
    """What the agent remembers about one question between rounds."""

    rounds: int = 0
    # ``answer_word_count`` when the last round started; growth is measured
    # from here, so a round that failed still moves the mark.
    snapshot_words: int = 0
    # Suggestions kept for this question so far, across rounds.
    kept: int = 0
    # Their content, in order, for the next round to read and not repeat.
    contents: list[str] = field(default_factory=list)


class LiveSuggestionAgent:
    """Watches one session's utterances and offers follow-ups as they arrive.

    The work is split in three so that the part sitting in the media path
    never waits on a model:

    - :meth:`ingest` records one FINAL utterance. Synchronous, no I/O.
    - :meth:`due` says which open pair deserves a round right now, if any.
    - :meth:`run_round` runs the model against that pair and verifies the
      drafts. This is the only step that awaits anything.

    A wiring loop can therefore drain a queue through ``ingest``, ask ``due``
    once, and await ``run_round`` off the audio path. :meth:`observe` chains
    the three for callers that handle utterances one at a time.

    The agent owns its own :class:`QASegmenter`; one instance is one interview.
    """

    def __init__(
        self,
        generator: SuggestionGenerator,
        *,
        context: InterviewContext | None = None,
        model: str = "",
        timeout_seconds: float = 10,
        max_per_round: int = DEFAULT_MAX_PER_ROUND,
        max_per_answer: int = DEFAULT_MAX_PER_ANSWER,
        max_per_session: int = DEFAULT_MAX_PER_SESSION,
        min_answer_words: int = MIN_ANSWER_WORDS,
        rerun_words: int = RERUN_WORDS,
        max_rounds_per_answer: int = DEFAULT_MAX_ROUNDS_PER_ANSWER,
        recent_exchanges: int = RECENT_EXCHANGES,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_per_round < 1:
            raise ValueError("max_per_round must be at least 1")
        if max_per_answer < 1:
            raise ValueError("max_per_answer must be at least 1")
        if max_per_session < 1:
            raise ValueError("max_per_session must be at least 1")
        if min_answer_words < 1:
            raise ValueError("min_answer_words must be at least 1")
        if rerun_words < 1:
            raise ValueError("rerun_words must be at least 1")
        if max_rounds_per_answer < 1:
            raise ValueError("max_rounds_per_answer must be at least 1")
        if recent_exchanges < 0:
            raise ValueError("recent_exchanges must not be negative")

        self.generator = generator
        self.context = context
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_per_round = max_per_round
        self.max_per_answer = max_per_answer
        self.max_per_session = max_per_session
        self.min_answer_words = min_answer_words
        self.rerun_words = rerun_words
        self.max_rounds_per_answer = max_rounds_per_answer
        self.recent_exchanges = recent_exchanges
        self.clock = clock

        self.segmenter = QASegmenter()
        self.kept_count = 0
        self._rounds: dict[str, RoundState] = {}
        self._seen_contents: set[str] = set()
        self._sources: dict[str, Utterance] = {}

    def ingest(self, utterance: Utterance) -> bool:
        """Record one utterance. Returns whether it added to an open answer.

        Safe to call from the media path: it touches the segmenter and the
        source map and nothing else. Non-FINAL utterances are ignored, as are
        FINAL ones from the interviewer as far as the return value goes - they
        still go into the segmenter, because that is how a pair closes.
        """

        if not utterance.is_final:
            return False
        self._sources[utterance.utterance_id] = utterance
        self.segmenter.feed(utterance)
        return utterance.speaker is SpeakerRole.CANDIDATE

    def due(self) -> QAPair | None:
        """The open pair that deserves a round now, or ``None``.

        Decided from the segmenter's state alone, not from whichever utterance
        happened to arrive last, so a caller that ingested several utterances
        in one go gets the same answer as one that asked after each. A pair
        only becomes due through candidate speech: it needs answer utterances
        and enough of them (``min_answer_words``), and an interviewer utterance
        either closes the pair - leaving a new one with no answer - or is a
        back-channel the segmenter already dropped.

        The first round on a pair is due once the answer clears
        ``min_answer_words``. A further round is due once the answer has grown
        by ``rerun_words`` since the last round started, as long as the
        question has rounds (``max_rounds_per_answer``) and suggestions
        (``max_per_answer``) left. Growth is measured from the last round's
        snapshot whether or not that round produced anything, so a round that
        timed out is not retried on the same words.
        """

        if self.kept_count >= self.max_per_session:
            return None
        pair = self.segmenter.current()
        if pair is None or not pair.answer_utterance_ids:
            return None
        if pair.answer_word_count < self.min_answer_words:
            return None
        state = self._rounds.get(pair.qa_id)
        if state is None:
            return pair
        if state.rounds >= self.max_rounds_per_answer:
            return None
        if state.kept >= self.max_per_answer:
            return None
        if pair.answer_word_count - state.snapshot_words < self.rerun_words:
            return None
        return pair

    async def observe(self, utterance: Utterance) -> SuggestionResult | None:
        """Take one utterance; run a round when it makes one due.

        :meth:`ingest`, :meth:`due` and :meth:`run_round` in one call, for a
        caller that can afford to await the model where it stands. Returns the
        round's result, or ``None`` when this utterance did not trigger one.
        """

        if not self.ingest(utterance):
            return None
        pair = self.due()
        if pair is None:
            return None
        return await self.run_round(pair)

    async def run_round(self, pair: QAPair) -> SuggestionResult:
        """Run one round against an already-chosen pair.

        Public because a caller with its own trigger - a Backend-driven one,
        say - may want to pick the pair itself. It reads the utterances
        :meth:`ingest` has been collecting, so a pair whose utterances never
        went through ``ingest`` grounds against nothing and every suggestion
        in the round is dropped.

        The round is counted and the answer's length snapshotted *before* it
        runs, not after: a round that times out or comes back ungrounded is
        deliberately not retried on the same words. The interview has already
        moved on, and a second attempt would land on an answer the interviewer
        has stopped listening to. The next round waits for ``rerun_words``
        more, like any other.
        """

        state = self._rounds.setdefault(pair.qa_id, RoundState())
        state.rounds += 1
        state.snapshot_words = pair.answer_word_count

        started = perf_counter()
        result = SuggestionResult(
            session_id=pair.session_id,
            qa_id=pair.qa_id,
            status="empty",
            model=self.model,
        )
        session_left = max(self.max_per_session - self.kept_count, 0)
        answer_left = max(self.max_per_answer - state.kept, 0)
        remaining = min(session_left, answer_left)
        if not remaining:
            result.warnings.append(
                "SESSION_LIMIT_REACHED" if not session_left else "ANSWER_LIMIT_REACHED"
            )
            result.elapsed_ms = round((perf_counter() - started) * 1000)
            return result

        history = RoundHistory(
            already_suggested=tuple(state.contents),
            recent_exchanges=self._recent_exchanges(pair),
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                draft = await self.generator.generate(
                    pair, self._sources, self.context, history
                )
        except TimeoutError:
            return self._failed(result, "LLM_TIMEOUT", retryable=True, started=started)
        except SuggestionError as exc:
            return self._failed(
                result, exc.code, retryable=exc.retryable, started=started
            )

        usage = getattr(self.generator, "last_usage", None)
        if isinstance(usage, LlmUsage):
            result.usage = usage
        served_model = getattr(self.generator, "last_model", None)
        if served_model:
            result.model = served_model

        suggestions, rejections = build_suggestions(
            pair,
            draft,
            self._sources,
            generated_at=self.clock(),
            max_per_answer=min(self.max_per_round, remaining),
            seen_contents=frozenset(self._seen_contents),
            first_index=state.kept + 1,
        )
        result.suggestions = suggestions
        result.rejections = rejections
        if suggestions:
            result.status = "partial" if rejections else "completed"
        elif rejections:
            result.status = "partial"
            result.warnings.append("UNGROUNDED_SUGGESTIONS_REMOVED")

        state.kept += len(suggestions)
        state.contents.extend(s.content for s in suggestions)
        self.kept_count += len(suggestions)
        self._seen_contents.update(s.content for s in suggestions)
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result

    def _recent_exchanges(self, pair: QAPair) -> tuple[QAPair, ...]:
        """The closed pairs just before ``pair``, oldest first, capped."""

        if not self.recent_exchanges:
            return ()
        before = [
            p
            for p in self.segmenter.result().qa_pairs
            if p.qa_id != pair.qa_id and p.start_ms < pair.start_ms
        ]
        return tuple(before[-self.recent_exchanges :])

    def _failed(
        self,
        result: SuggestionResult,
        code: str,
        *,
        retryable: bool,
        started: float,
    ) -> SuggestionResult:
        result.status = "failed"
        result.error = AnalysisError(code=code, retryable=retryable)
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result
