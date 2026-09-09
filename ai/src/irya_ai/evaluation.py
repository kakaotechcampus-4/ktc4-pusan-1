"""Surface-level checks for summary quality (issue #6).

Both checks use normalized string matching without morphological analysis,
so they are screening signals for sample-dialogue verification, not proof
of summary quality.
"""

import re
from collections.abc import Sequence

from irya_ai.schemas.transcript import TranscriptSnapshot

_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def missing_key_facts(summary: str, key_facts: Sequence[str]) -> list[str]:
    """Key facts that do not appear in the summary.

    Key facts should be short surface strings (a name, a number, a keyword);
    matching ignores whitespace and letter case only.
    """

    normalized_summary = _normalize(summary)
    return [fact for fact in key_facts if _normalize(fact) not in normalized_summary]


def unsupported_numbers(transcript: TranscriptSnapshot, summary: str) -> list[str]:
    """Numbers in the summary that never appear in the transcript.

    A cheap hallucination signal: a summary should not introduce figures
    the conversation never mentioned.
    """

    return unsupported_numbers_in_text(transcript.full_text(), summary)


def unsupported_numbers_in_text(source_text: str, summary: str) -> list[str]:
    """Apply the same surface check to the exact citations for one claim."""
    source_numbers = set(_NUMBER_PATTERN.findall(source_text))
    found = [n for n in _NUMBER_PATTERN.findall(summary) if n not in source_numbers]
    return list(dict.fromkeys(found))
