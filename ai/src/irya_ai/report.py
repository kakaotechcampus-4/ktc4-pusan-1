"""Adopted findings + summary -> a per-competency report with finding ids.

The model drafts sentences and names the finding each rests on. Code decides
which survive: the finding must be one the interviewer adopted, it must be
filed under the competency it belongs to (or belong to none), its type must
fit the list it is in, and numbers in the sentence must appear in that
finding's text, quote or transcript. Questions for the next interview carry
no finding: they are questions, not claims (#239). Scores, pass/fail and
rankings are never produced; the prompt forbids them and no field exists for
them.
"""

import asyncio
from time import perf_counter
from typing import Protocol

from irya_ai.evaluation import unsupported_numbers_in_text
from irya_ai.pipeline.grounding import normalize
from irya_ai.schemas.analysis import FindingType
from irya_ai.schemas.report import (
    MAX_NEXT_QUESTIONS,
    MAX_SENTENCES_PER_LIST,
    OVERVIEW_MAX_CHARS,
    QUESTION_MAX_CHARS,
    SENTENCE_MAX_CHARS,
    AdoptedFinding,
    CompetencyReport,
    CompetencyReportDraft,
    ReportContext,
    ReportDraft,
    ReportResult,
    ReportSentence,
    SentenceDraft,
)
from irya_ai.schemas.summary import AnalysisError
from irya_ai.schemas.timeline import LlmUsage

#: Finding types that confirm a competency. The other three (a contradicted
#: or unverified claim, a gap) leave it open, so they belong in ``unconfirmed``.
CONFIRMING_TYPES = frozenset(
    {FindingType.COMPETENCY_EVIDENCE, FindingType.CLAIM_VERIFIED}
)


class ReportError(Exception):
    """Safe provider failure; no response body or interview text."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def build_report(
    context: ReportContext,
    draft: ReportDraft,
    *,
    max_sentences: int = MAX_SENTENCES_PER_LIST,
    max_questions: int = MAX_NEXT_QUESTIONS,
) -> tuple[str, list[CompetencyReport], list[str]]:
    """Keep the sentences that stand on an adopted finding; say why the rest fell.

    Every competency in the context comes back, in the context's order, with
    empty lists when the draft had nothing for it: Backend shows those as
    "not covered in this interview". Rejection notes name ids and positions,
    never a sentence or a finding's text.
    """

    if max_sentences < 1 or max_questions < 0:
        raise ValueError("sentence limit must be positive, question limit not negative")
    competencies = {c.competency_id for c in context.competencies}
    findings = {f.finding_id: f for f in context.findings}
    rejections: list[str] = []
    drafted: dict[str, CompetencyReportDraft] = {}
    for index, block in enumerate(draft.competencies, 1):
        if block.competency_id not in competencies:
            rejections.append(f"competency {index}: unknown competency")
        elif block.competency_id in drafted:
            rejections.append(f"competency {index}: duplicate competency")
        else:
            drafted[block.competency_id] = block

    reports: list[CompetencyReport] = []
    for competency in context.competencies:
        cid = competency.competency_id
        block = drafted.get(cid)
        if block is None:
            reports.append(CompetencyReport(competency_id=cid))
            continue
        cited: set[str] = set()
        confirmed = _sentences(
            block.confirmed,
            cid,
            "confirmed",
            findings,
            cited,
            rejections,
            max_sentences,
        )
        unconfirmed = _sentences(
            block.unconfirmed,
            cid,
            "unconfirmed",
            findings,
            cited,
            rejections,
            max_sentences,
        )
        questions = _questions(block.next_questions, cid, rejections, max_questions)
        reports.append(
            CompetencyReport(
                competency_id=cid,
                confirmed=confirmed,
                unconfirmed=unconfirmed,
                next_questions=questions,
            )
        )

    overview = normalize(draft.overview)
    if len(overview) > OVERVIEW_MAX_CHARS:
        rejections.append("overview: too long")
        overview = ""
    return overview, reports, rejections


def _sentences(
    items: list[SentenceDraft],
    competency_id: str,
    list_name: str,
    findings: dict[str, AdoptedFinding],
    cited: set[str],
    rejections: list[str],
    limit: int,
) -> list[ReportSentence]:
    kept: list[ReportSentence] = []
    confirming = list_name == "confirmed"
    for index, item in enumerate(items, 1):
        text = normalize(item.text)
        finding = findings.get(item.finding_id)
        reason = None
        if finding is None:
            reason = "finding not adopted"
        elif finding.competency_id not in (None, competency_id):
            reason = "finding belongs to another competency"
        elif (finding.finding_type in CONFIRMING_TYPES) != confirming:
            reason = "finding type does not fit this list"
        elif not text or len(text) > SENTENCE_MAX_CHARS:
            reason = "invalid sentence length"
        elif unsupported_numbers_in_text(_support(finding), text):
            reason = "sentence contains unsupported numbers"
        elif item.finding_id in cited:
            reason = "duplicate finding"
        elif len(kept) >= limit:
            reason = "sentence limit exceeded"
        if reason is not None:
            rejections.append(f"{competency_id} {list_name} {index}: {reason}")
            continue
        cited.add(item.finding_id)
        kept.append(ReportSentence(text=text, finding_id=item.finding_id))
    return kept


def _support(finding: AdoptedFinding) -> str:
    """Everything a sentence's numbers may come from."""

    return " ".join(
        part for part in (finding.text, finding.quote, finding.transcript) if part
    )


def _questions(
    items: list[str], competency_id: str, rejections: list[str], limit: int
) -> list[str]:
    kept: list[str] = []
    for index, raw in enumerate(items, 1):
        text = normalize(raw)
        reason = None
        if not text or len(text) > QUESTION_MAX_CHARS:
            reason = "invalid question length"
        elif text in kept:
            reason = "duplicate question"
        elif len(kept) >= limit:
            reason = "question limit exceeded"
        if reason is not None:
            rejections.append(f"{competency_id} question {index}: {reason}")
            continue
        kept.append(text)
    return kept


class ReportGenerator(Protocol):
    async def generate(self, context: ReportContext) -> ReportDraft: ...


class FakeReportGenerator:
    def __init__(self, draft: ReportDraft) -> None:
        self.draft = draft
        self.calls = 0

    async def generate(self, context: ReportContext) -> ReportDraft:
        self.calls += 1
        return self.draft


class ExtractiveReportGenerator:
    """Offline baseline: each adopted finding's own sentence, filed by its type.

    No overview beyond the stored summary's and no questions; those need a
    model. Findings without a competency are left out, since the report is
    organised by competency.
    """

    async def generate(self, context: ReportContext) -> ReportDraft:
        blocks = []
        for competency in context.competencies:
            confirmed: list[SentenceDraft] = []
            unconfirmed: list[SentenceDraft] = []
            for finding in context.findings:
                if finding.competency_id != competency.competency_id:
                    continue
                sentence = SentenceDraft(
                    text=finding.text, finding_id=finding.finding_id
                )
                if finding.finding_type in CONFIRMING_TYPES:
                    confirmed.append(sentence)
                else:
                    unconfirmed.append(sentence)
            blocks.append(
                CompetencyReportDraft(
                    competency_id=competency.competency_id,
                    confirmed=confirmed,
                    unconfirmed=unconfirmed,
                    next_questions=[],
                )
            )
        return ReportDraft(overview=context.summary.overview, competencies=blocks)


class ReportAgent:
    def __init__(
        self,
        generator: ReportGenerator,
        *,
        model: str = "",
        timeout_seconds: float = 60,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self.generator = generator
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def run(self, context: ReportContext) -> ReportResult:
        started = perf_counter()
        result = ReportResult(
            interview_id=context.interview_id, status="empty", model=self.model
        )
        for ids in [
            [c.competency_id for c in context.competencies],
            [f.finding_id for f in context.findings],
        ]:
            if len(ids) != len(set(ids)):
                return self._fail(result, "DUPLICATE_CONTEXT_IDS", started=started)
        if not context.competencies:
            result.warnings.append("NO_COMPETENCIES")
            return self._finish(result, started)
        if not context.findings:
            # Backend refuses the request with no adopted finding (#238), so
            # this is a guard, not a path: there is nothing to write from.
            result.warnings.append("NO_ADOPTED_FINDINGS")
            return self._finish(result, started)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                draft = await self.generator.generate(context)
        except TimeoutError:
            return self._fail(result, "LLM_TIMEOUT", started=started, retryable=True)
        except ReportError as exc:
            return self._fail(
                result, exc.code, started=started, retryable=exc.retryable
            )
        self._record_call(result)
        result.overview, result.competencies, result.rejections = build_report(
            context, draft
        )
        if result.sentence_count == 0:
            # ``empty``: the model wrote nothing that stands on an adopted
            # finding. Backend shows it as NO_EVIDENCE; not worth a retry.
            return self._finish(result, started)
        if not result.overview:
            result.warnings.append("NO_OVERVIEW")
        result.status = "partial" if result.rejections else "completed"
        return self._finish(result, started)

    @staticmethod
    def _finish(result: ReportResult, started: float) -> ReportResult:
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result

    def _record_call(self, result: ReportResult) -> None:
        """Copy what the generator reports about its calls onto ``result``."""

        usage = getattr(self.generator, "last_usage", None)
        if isinstance(usage, LlmUsage):
            result.usage = usage
        served_model = getattr(self.generator, "last_model", None)
        if served_model:
            result.model = served_model

    def _fail(
        self,
        result: ReportResult,
        code: str,
        *,
        started: float,
        retryable: bool = False,
    ) -> ReportResult:
        # A call that came back but could not be used was still paid for.
        self._record_call(result)
        result.status = "failed"
        result.error = AnalysisError(code=code, retryable=retryable)
        return self._finish(result, started)
