"""Pre-interview preparation: job description and resume -> competencies and claims.

Runs before the interview, once per interview (#137 ``PREP``). A model reads
the job description and the resume body and drafts two lists; this module
decides what survives and gives each survivor its identifier.

Two rules shape everything here.

**A resume claim must quote the resume.** The ``quote`` is checked as a
literal substring of ``Resume.text`` under the same normalisation the
transcript grounding uses (:func:`irya_ai.pipeline.grounding.normalize`: NFC
and whitespace runs, nothing else). A claim that paraphrases, fixes a typo or
changes letter case is dropped whole. Findings later say "the resume states X,
the candidate said Y", and that sentence is only worth showing if X is really
on the page. Competencies carry no such check: a competency is a name the
model gives to a group of requirements, and it is not expected to appear in
the job description word for word.

**Identifiers come from content, not from position.** ``clm_`` and ``cpt_``
ids are a hash of the normalised quote or name. A sequence number would point
at different content the next time the model listed the same items in another
order, and the marks an interviewer left on that id, and the findings attached
to it, would silently move with it. A content hash stays put while the content
does, and changes when the content changes - at which point Backend treats the
old marks as gone (#137 1-4), which is the honest outcome. The price is that a
competency the model renames gets a new id; that is accepted.

Nothing here logs or returns resume text. Rejections name a draft by its
position in the list the model returned, never by what it said.
"""

import asyncio
import hashlib
import re
from time import perf_counter
from typing import Protocol, runtime_checkable

from irya_ai.pipeline.grounding import normalize
from irya_ai.schemas.context import Competency, InterviewContext, ResumeClaim
from irya_ai.schemas.prep import (
    CLAIM_QUOTE_MAX_CHARS,
    CLAIM_QUOTE_MIN_CHARS,
    CLAIM_SECTION_MAX_CHARS,
    COMPETENCY_DESCRIPTION_MAX_CHARS,
    COMPETENCY_NAME_MAX_CHARS,
    CompetencyDraft,
    PrepDraft,
    PrepResult,
    ResumeClaimDraft,
)
from irya_ai.schemas.summary import AnalysisError
from irya_ai.schemas.timeline import LlmUsage

# Coverage is drawn as one chip per competency; past six it stops being a
# glance and starts being a list.
DEFAULT_MAX_COMPETENCIES = 6
# Fewer than this is still usable, but usually means the job description was
# thin. Worth a warning, not a failure.
MIN_COMPETENCIES_WARNING = 3
# Each claim can become a finding the interviewer has to look at.
DEFAULT_MAX_CLAIMS = 12

_ID_HEX_CHARS = 8
# List markers a resume line starts with. They are layout, not wording: the
# same sentence quoted with and without its bullet is the same claim, and
# must hash to the same id. A marker is only a marker when whitespace
# follows it: "- 10도" is a bullet, "-10도" is a temperature, and a quote
# that starts with a sign or a dash-joined word keeps it. Numbered markers
# ("1.", "2)") are left alone, since a bare number can also start a real
# sentence.
_LIST_MARKER = re.compile(r"^[-*•·∙▪◦–—]+\s+")


class PrepError(Exception):
    """A safe, structured failure; provider error bodies are never forwarded."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


# --- identifiers -------------------------------------------------------------


def _digest(text: str) -> str:
    # An identifier, not a secret: sha1 is used for its stable short output.
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False)
    return digest.hexdigest()[:_ID_HEX_CHARS]


def _competency_key(name: str) -> str:
    """What makes two competency names the same competency.

    Letter case is folded here and nowhere else in this module: ``API 설계``
    and ``api 설계`` are one competency, whereas a resume quote that changes
    case is a different string and fails verification.
    """

    return normalize(name).casefold()


def competency_id(name: str) -> str:
    """``cpt_`` plus a hash of the normalised name. Stable across runs."""

    return f"cpt_{_digest(_competency_key(name))}"


def claim_id(quote: str) -> str:
    """``clm_`` plus a hash of the normalised quote. Stable across runs."""

    return f"clm_{_digest(_unbulleted(quote))}"


# --- verification ------------------------------------------------------------


def _unbulleted(quote: str) -> str:
    """A quote without the list marker the resume line began with."""

    return _LIST_MARKER.sub("", normalize(quote), count=1).strip()


def _clean(text: str) -> str:
    """The one normalisation every field goes through before it is measured.

    NFC and whitespace runs, via the same :func:`normalize` the ids and the
    quote check use. Length limits are counted on this form: a Hangul name
    arriving decomposed (NFD, as macOS writes it) has more code points than
    the same name composed, and measuring the raw string would reject it
    while its id - a hash of the normalised form - says it is the same name.
    """

    return normalize(text)


def _resume_text(context: InterviewContext) -> str:
    """The normalised resume body, or ``""`` when there is nothing to quote."""

    if context.resume is None or context.resume.text is None:
        return ""
    return normalize(context.resume.text)


def build_prep(
    context: InterviewContext,
    draft: PrepDraft,
    *,
    max_competencies: int = DEFAULT_MAX_COMPETENCIES,
    max_claims: int = DEFAULT_MAX_CLAIMS,
) -> tuple[list[Competency], list[ResumeClaim], list[str]]:
    """Turn model drafts into verified competencies and claims.

    Returns ``(competencies, resume_claims, rejections)``. Survivors keep the
    order the model listed them in; a draft past a limit is rejected rather
    than silently cut, so the count of what was dropped is always visible.
    Each rejection is ``"competency N: reason"`` or ``"claim N: reason"``
    with ``N`` counted from 1 - a position, never the text of the draft.
    """

    if max_competencies < 1:
        raise ValueError("max_competencies must be at least 1")
    if max_claims < 1:
        raise ValueError("max_claims must be at least 1")

    rejections: list[str] = []

    competencies: list[Competency] = []
    seen_competencies: set[str] = set()
    jd_id = context.job_description.jd_id
    for index, d in enumerate(draft.competencies, start=1):
        label = f"competency {index}"
        name = _clean(d.name)
        if not name:
            rejections.append(f"{label}: empty name")
            continue
        if len(name) > COMPETENCY_NAME_MAX_CHARS:
            rejections.append(
                f"{label}: name longer than {COMPETENCY_NAME_MAX_CHARS} chars"
            )
            continue
        description = _clean(d.description)
        if not description:
            rejections.append(f"{label}: empty description")
            continue
        if len(description) > COMPETENCY_DESCRIPTION_MAX_CHARS:
            rejections.append(
                f"{label}: description longer than "
                f"{COMPETENCY_DESCRIPTION_MAX_CHARS} chars"
            )
            continue
        key = _competency_key(name)
        if key in seen_competencies:
            rejections.append(f"{label}: duplicate of an earlier competency")
            continue
        if len(competencies) >= max_competencies:
            rejections.append(f"{label}: over the {max_competencies} competency limit")
            continue
        seen_competencies.add(key)
        competencies.append(
            Competency(
                competency_id=competency_id(name),
                jd_id=jd_id,
                name=name,
                required=d.required,
                description=description,
            )
        )

    claims: list[ResumeClaim] = []
    seen_claims: set[str] = set()
    resume_text = _resume_text(context)
    for index, d in enumerate(draft.resume_claims, start=1):
        label = f"claim {index}"
        if context.resume is None or not resume_text:
            # A model handed no resume has nothing to quote; whatever it
            # wrote here did not come from the candidate.
            rejections.append(f"{label}: no resume text to quote")
            continue
        quote = _unbulleted(d.quote)
        if not quote:
            rejections.append(f"{label}: empty quote")
            continue
        if len(quote) < CLAIM_QUOTE_MIN_CHARS:
            rejections.append(
                f"{label}: quote shorter than {CLAIM_QUOTE_MIN_CHARS} chars"
            )
            continue
        if len(quote) > CLAIM_QUOTE_MAX_CHARS:
            rejections.append(
                f"{label}: quote longer than {CLAIM_QUOTE_MAX_CHARS} chars"
            )
            continue
        if quote not in resume_text:
            rejections.append(f"{label}: quote not found in resume")
            continue
        section = _clean(d.section) if d.section is not None else ""
        if len(section) > CLAIM_SECTION_MAX_CHARS:
            rejections.append(
                f"{label}: section longer than {CLAIM_SECTION_MAX_CHARS} chars"
            )
            continue
        if quote in seen_claims:
            rejections.append(f"{label}: duplicate of an earlier claim")
            continue
        if len(claims) >= max_claims:
            rejections.append(f"{label}: over the {max_claims} claim limit")
            continue
        seen_claims.add(quote)
        claims.append(
            ResumeClaim(
                claim_id=claim_id(quote),
                resume_id=context.resume.resume_id,
                # Stored normalised: a quote that spanned a PDF line break
                # reads as one line, and the id is a hash of exactly this.
                quote=quote,
                section=section or None,
            )
        )

    return competencies, claims, rejections


# --- generators --------------------------------------------------------------


@runtime_checkable
class PrepGenerator(Protocol):
    """Writes the draft. Implementations must quote the resume, never restate it."""

    async def generate(self, context: InterviewContext) -> PrepDraft: ...


_SENTENCE_END = re.compile(r"(?<=[.?!])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]


class ExtractivePrepGenerator:
    """Offline baseline: the job description and the resume, sentence by sentence.

    Adds no information, so every claim it drafts is grounded by construction:
    each one is a whole sentence of the resume, and each competency is a
    sentence of the job description under a name cut from its first words.
    It lets the pipeline run without a key and gives a model a floor to beat;
    the names it produces are not ones anybody would put on a screen.
    """

    async def generate(self, context: InterviewContext) -> PrepDraft:
        competencies = [
            CompetencyDraft(
                name=sentence[:COMPETENCY_NAME_MAX_CHARS],
                required=True,
                description=sentence[:COMPETENCY_DESCRIPTION_MAX_CHARS],
            )
            for sentence in _sentences(context.job_description.description)
        ][:DEFAULT_MAX_COMPETENCIES]
        claims: list[ResumeClaimDraft] = []
        if context.resume is not None and context.resume.text:
            claims = [
                ResumeClaimDraft(quote=sentence, section=None)
                for sentence in _sentences(context.resume.text)
                if CLAIM_QUOTE_MIN_CHARS <= len(sentence) <= CLAIM_QUOTE_MAX_CHARS
            ][:DEFAULT_MAX_CLAIMS]
        return PrepDraft(competencies=competencies, resume_claims=claims)


class FakePrepGenerator:
    """Test double that returns a preset draft for any input."""

    def __init__(self, draft: PrepDraft) -> None:
        self.draft = draft
        self.calls: list[str] = []

    async def generate(self, context: InterviewContext) -> PrepDraft:
        self.calls.append(context.session_id)
        return self.draft


# --- agent -------------------------------------------------------------------


class PrepAgent:
    """One preparation run: ask the generator, keep what verifies.

    The statuses are the contract Backend stores (#137 2-4):

    - ``empty`` - the job description body is blank. The generator is not
      called; there is nothing to derive competencies from.
    - ``failed`` - the generator failed, timed out, or no competency survived.
      Preparation without competencies gives coverage and findings nothing to
      attach to, so it is not reported as a partial success.
    - ``partial`` - competencies survived and at least one draft was dropped.
    - ``completed`` - every draft survived.

    A missing resume is not a failure. The resume is optional (#137), so the
    run completes with ``resume_claims == []`` and a ``NO_RESUME_TEXT``
    warning.
    """

    def __init__(
        self,
        generator: PrepGenerator,
        *,
        model: str = "",
        timeout_seconds: float = 60,
        max_competencies: int = DEFAULT_MAX_COMPETENCIES,
        max_claims: int = DEFAULT_MAX_CLAIMS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_competencies < 1:
            raise ValueError("max_competencies must be at least 1")
        if max_claims < 1:
            raise ValueError("max_claims must be at least 1")
        self.generator = generator
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_competencies = max_competencies
        self.max_claims = max_claims

    async def run(self, context: InterviewContext) -> PrepResult:
        started = perf_counter()
        result = PrepResult(
            session_id=context.session_id, status="empty", model=self.model
        )
        if not context.job_description.description.strip():
            result.warnings.append("NO_JOB_DESCRIPTION")
            return self._finish(result, started)
        if not _resume_text(context):
            result.warnings.append("NO_RESUME_TEXT")

        try:
            async with asyncio.timeout(self.timeout_seconds):
                draft = await self.generator.generate(context)
        except TimeoutError:
            return self._failed(result, "LLM_TIMEOUT", retryable=True, started=started)
        except PrepError as exc:
            return self._failed(
                result, exc.code, retryable=exc.retryable, started=started
            )

        usage = getattr(self.generator, "last_usage", None)
        if isinstance(usage, LlmUsage):
            result.usage = usage
        served_model = getattr(self.generator, "last_model", None)
        if served_model:
            result.model = served_model
        if getattr(self.generator, "last_truncated", False):
            # The generator saw only the head of a body; what it did not see
            # it could not quote, so a short claim list is expected here.
            result.warnings.append("INPUT_TRUNCATED")

        competencies, claims, rejections = build_prep(
            context,
            draft,
            max_competencies=self.max_competencies,
            max_claims=self.max_claims,
        )
        result.rejections = rejections
        if not competencies:
            return self._failed(
                result, "NO_COMPETENCIES", retryable=False, started=started
            )
        result.competencies = competencies
        result.resume_claims = claims
        if rejections:
            result.status = "partial"
            result.warnings.append("DRAFTS_REMOVED")
        else:
            result.status = "completed"
        if len(competencies) < MIN_COMPETENCIES_WARNING:
            result.warnings.append("FEWER_THAN_THREE_COMPETENCIES")
        return self._finish(result, started)

    def _failed(
        self, result: PrepResult, code: str, *, retryable: bool, started: float
    ) -> PrepResult:
        result.status = "failed"
        result.error = AnalysisError(code=code, retryable=retryable)
        return self._finish(result, started)

    @staticmethod
    def _finish(result: PrepResult, started: float) -> PrepResult:
        result.elapsed_ms = round((perf_counter() - started) * 1000)
        return result
