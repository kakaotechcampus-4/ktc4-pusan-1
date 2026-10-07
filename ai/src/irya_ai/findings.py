"""Prepared context + stored FINAL revisions -> grounded review observations.

The generator may draft references and text, never IDs, timestamps or human
review state. Structural validation and existing literal grounding decide
which drafts survive. Semantic relevance still requires human review.
"""

import asyncio
import hashlib
import json
from time import perf_counter
from typing import Protocol

from irya_ai.evaluation import unsupported_numbers_in_text
from irya_ai.pipeline.grounding import ground_finding, normalize
from irya_ai.schemas.analysis import Finding, FindingType
from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.findings import (
    SUMMARY_MAX_CHARS,
    FindingDraft,
    FindingsDraft,
    FindingsResult,
)
from irya_ai.schemas.summary import AnalysisError
from irya_ai.schemas.timeline import LlmUsage
from irya_ai.schemas.transcript import (
    SpeakerRole,
    TranscriptSnapshot,
    TranscriptStage,
    Utterance,
)

DEFAULT_MAX_FINDINGS = 24
_CLAIM_TYPES = {
    FindingType.CLAIM_VERIFIED,
    FindingType.CLAIM_CONTRADICTED,
    FindingType.CLAIM_UNVERIFIED,
}


class FindingsError(Exception):
    """Safe provider failure; no response body or interview text."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def finding_id(draft: FindingDraft) -> str:
    """Opaque content identity; order and summary wording do not move marks."""
    identity = [
        draft.type.value,
        draft.competency_id,
        draft.claim_id,
        draft.evidence_utterance_id,
        normalize(draft.evidence_quote) if draft.evidence_quote else None,
    ]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return "fnd_" + hashlib.sha256(encoded.encode()).hexdigest()[:24]


def build_findings(
    context: InterviewContext,
    finals: list[Utterance],
    draft: FindingsDraft,
    *,
    max_findings: int = DEFAULT_MAX_FINDINGS,
) -> tuple[list[Finding], list[str]]:
    if max_findings < 1:
        raise ValueError("max_findings must be positive")
    if any(u.session_id != context.session_id for u in finals):
        raise ValueError("utterance session must match context")
    competencies = {c.competency_id for c in context.competencies}
    claims = {c.claim_id: c for c in context.resume_claims}
    sources = {
        u.utterance_id: u
        for u in finals
        if u.is_final and u.speaker is SpeakerRole.CANDIDATE
    }
    kept: dict[str, Finding] = {}
    rejections: list[str] = []
    for index, d in enumerate(draft.findings, 1):
        reason = None
        if d.competency_id is not None and d.competency_id not in competencies:
            reason = "unknown competency"
        elif d.claim_id is not None and d.claim_id not in claims:
            reason = "unknown claim"
        elif d.type in _CLAIM_TYPES and d.claim_id is None:
            reason = "claim type requires a claim"
        elif d.type not in _CLAIM_TYPES and (
            d.competency_id is None or d.claim_id is not None
        ):
            reason = "competency type requires a competency and no claim"
        summary = normalize(d.summary)
        if reason is None and (not summary or len(summary) > SUMMARY_MAX_CHARS):
            reason = "invalid summary length"
        if reason is None and d.type is FindingType.GAP:
            if d.evidence_quote is not None or d.evidence_utterance_id is not None:
                reason = "gap must not carry transcript evidence"
        elif reason is None:
            if not d.evidence_quote or d.evidence_utterance_id not in sources:
                reason = "evidence requires a candidate FINAL utterance"
        if reason is not None:
            rejections.append(f"finding {index}: {reason}")
            continue
        item = Finding(
            finding_id=finding_id(d),
            session_id=context.session_id,
            type=d.type,
            competency_id=d.competency_id,
            claim_id=d.claim_id,
            evidence_utterance_id=d.evidence_utterance_id,
            evidence_quote=normalize(d.evidence_quote)
            if d.evidence_quote is not None
            else None,
            summary=summary,
        )
        grounded = ground_finding(item, list(sources.values()))
        if not grounded.ok:
            rejections.append(f"finding {index}: quote not found in cited utterance")
            continue
        supporting_text = item.evidence_quote or ""
        if item.claim_id:
            supporting_text += " " + claims[item.claim_id].quote
        if unsupported_numbers_in_text(supporting_text, summary):
            rejections.append(f"finding {index}: summary contains unsupported numbers")
            continue
        if item.finding_id in kept:
            rejections.append(f"finding {index}: duplicate finding")
            continue
        if len(kept) >= max_findings:
            rejections.append(f"finding {index}: finding limit exceeded")
            continue
        kept[item.finding_id] = grounded.finding
    return sorted(
        kept.values(),
        key=lambda f: (f.evidence_t_ms is None, f.evidence_t_ms or 0, f.finding_id),
    ), rejections


class FindingsGenerator(Protocol):
    async def generate(
        self, context: InterviewContext, finals: list[Utterance]
    ) -> FindingsDraft: ...


class FakeFindingsGenerator:
    def __init__(self, draft: FindingsDraft) -> None:
        self.draft = draft
        self.calls = 0

    async def generate(
        self, context: InterviewContext, finals: list[Utterance]
    ) -> FindingsDraft:
        self.calls += 1
        return self.draft


class ExtractiveFindingsGenerator:
    """Offline baseline: only exact resume-claim mentions, no semantic inference."""

    async def generate(
        self, context: InterviewContext, finals: list[Utterance]
    ) -> FindingsDraft:
        items = []
        for claim in context.resume_claims:
            quote = normalize(claim.quote)
            if not quote:
                continue
            source = next(
                (
                    u
                    for u in finals
                    if u.is_final
                    and u.speaker is SpeakerRole.CANDIDATE
                    and quote in normalize(u.content)
                ),
                None,
            )
            if source:
                items.append(
                    FindingDraft(
                        type=FindingType.CLAIM_VERIFIED,
                        competency_id=None,
                        claim_id=claim.claim_id,
                        evidence_utterance_id=source.utterance_id,
                        evidence_quote=quote,
                        summary="이력서 주장과 같은 문장이 면접 답변에서 언급됐습니다.",
                    )
                )
        return FindingsDraft(findings=items)


class FindingsAgent:
    def __init__(
        self,
        generator: FindingsGenerator,
        *,
        model: str = "",
        timeout_seconds: float = 60,
        max_findings: int = DEFAULT_MAX_FINDINGS,
    ) -> None:
        if timeout_seconds <= 0 or max_findings < 1:
            raise ValueError("timeout and finding limit must be positive")
        self.generator = generator
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_findings = max_findings

    async def run(
        self, context: InterviewContext, snapshot: TranscriptSnapshot
    ) -> FindingsResult:
        started = perf_counter()
        result = FindingsResult(
            session_id=snapshot.session_id,
            transcript_stage=snapshot.stage,
            status="empty",
            model=self.model,
        )
        if context.session_id != snapshot.session_id:
            return self._fail(result, "CONTEXT_SESSION_MISMATCH", started=started)
        for ids in [
            [c.competency_id for c in context.competencies],
            [c.claim_id for c in context.resume_claims],
        ]:
            if len(ids) != len(set(ids)):
                return self._fail(result, "DUPLICATE_CONTEXT_IDS", started=started)
        finals = snapshot.final_utterances()
        if snapshot.stage is TranscriptStage.LIVE:
            result.warnings.append("PROVISIONAL_TRANSCRIPT")
        if not context.competencies and not context.resume_claims:
            result.warnings.append("NO_PREPARED_CONTEXT")
            return self._finish(result, started)
        if not any(u.speaker is SpeakerRole.CANDIDATE for u in finals):
            result.warnings.append("NO_CANDIDATE_FINALS")
            return self._finish(result, started)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                draft = await self.generator.generate(context, finals)
        except TimeoutError:
            return self._fail(result, "LLM_TIMEOUT", started=started, retryable=True)
        except FindingsError as exc:
            return self._fail(
                result, exc.code, started=started, retryable=exc.retryable
            )
        usage = getattr(self.generator, "last_usage", None)
        if isinstance(usage, LlmUsage):
            result.usage = usage
        result.model = getattr(self.generator, "last_model", "") or self.model
        result.findings, result.rejections = build_findings(
            context, finals, draft, max_findings=self.max_findings
        )
        if result.rejections and not result.findings:
            return self._fail(result, "NO_GROUNDED_FINDINGS", started=started)
        result.status = "partial" if result.rejections else "completed"
        return self._finish(result, started)

    @staticmethod
    def _finish(result: FindingsResult, started: float) -> FindingsResult:
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result

    def _fail(
        self,
        result: FindingsResult,
        code: str,
        *,
        started: float,
        retryable: bool = False,
    ) -> FindingsResult:
        result.status = "failed"
        result.error = AnalysisError(code=code, retryable=retryable)
        return self._finish(result, started)
