"""Citation grounding: a Finding may only quote text that exists (TechSpec DEV1).

A model can invent a plausible quote. The transcript is the only source of
truth, so every ``evidence_quote`` is checked as a literal substring of the
utterance it cites. Findings that fail are dropped, not repaired: a finding
with fabricated evidence is worse than no finding.

Matching is deliberately strict. Only whitespace is normalised; wording must
match exactly. Fuzzy matching would let the model paraphrase and still pass,
which is the failure mode this stage exists to stop.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from irya_ai.schemas.analysis import Finding, FindingType
from irya_ai.schemas.transcript import Utterance

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFC + collapse whitespace. Nothing else."""

    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


@dataclass(frozen=True, slots=True)
class QuoteLocation:
    utterance_id: str
    char_offset: int
    t_ms: int


@dataclass(frozen=True, slots=True)
class GroundingResult:
    finding: Finding
    ok: bool
    reason: str = ""
    found_in: tuple[str, ...] = ()

    @property
    def finding_id(self) -> str:
        return self.finding.finding_id


@dataclass(slots=True)
class GroundingReport:
    kept: list[Finding] = field(default_factory=list)
    rejected: list[GroundingResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.rejected)


def _time_at_offset(utterance: Utterance, char_offset: int) -> int:
    """Timestamp of the word that contains ``char_offset`` in the utterance.

    Falls back to the utterance start when word timings are absent.
    """

    if not utterance.words:
        return utterance.start_ms
    normalized = normalize(utterance.content)
    cursor = 0
    for word in utterance.words:
        token = normalize(word.content)
        idx = normalized.find(token, cursor)
        if idx == -1:
            break
        if idx + len(token) > char_offset:
            return word.start_ms
        cursor = idx + len(token)
    return utterance.start_ms


def locate_quote(quote: str, utterances: list[Utterance]) -> list[QuoteLocation]:
    """Every utterance whose content contains ``quote`` verbatim."""

    needle = normalize(quote)
    if not needle:
        return []
    hits: list[QuoteLocation] = []
    for u in utterances:
        offset = normalize(u.content).find(needle)
        if offset != -1:
            hits.append(
                QuoteLocation(u.utterance_id, offset, _time_at_offset(u, offset))
            )
    return hits


def ground_finding(finding: Finding, utterances: list[Utterance]) -> GroundingResult:
    """Check one finding. Returns the finding with ``evidence_t_ms`` filled in."""

    if finding.type is FindingType.GAP and finding.evidence_quote is None:
        return GroundingResult(finding, ok=True, reason="gap finding needs no quote")

    quote = finding.evidence_quote or ""
    cited_id = finding.evidence_utterance_id
    by_id = {u.utterance_id: u for u in utterances if u.is_final}

    cited = by_id.get(cited_id or "")
    if cited is None:
        return GroundingResult(
            finding, ok=False, reason=f"cited utterance {cited_id!r} does not exist"
        )

    hits = locate_quote(quote, [cited])
    if not hits:
        elsewhere = tuple(h.utterance_id for h in locate_quote(quote, utterances))
        reason = (
            "quote not found in cited utterance"
            if not elsewhere
            else "quote found in a different utterance than cited"
        )
        return GroundingResult(finding, ok=False, reason=reason, found_in=elsewhere)

    t_ms = hits[0].t_ms
    grounded = (
        finding
        if finding.evidence_t_ms == t_ms
        else finding.model_copy(update={"evidence_t_ms": t_ms})
    )
    return GroundingResult(grounded, ok=True)


def ground_findings(
    findings: list[Finding], utterances: list[Utterance]
) -> GroundingReport:
    """Split findings into grounded (kept) and fabricated (rejected)."""

    report = GroundingReport()
    for finding in findings:
        result = ground_finding(finding, utterances)
        if result.ok:
            report.kept.append(result.finding)
        else:
            report.rejected.append(result)
    return report
