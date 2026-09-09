"""Analysis pipeline stages.

Cheap, deterministic stages come first and define the boundaries that the
LLM-backed stages later work within:

- ``qa_segmentation``: group utterances into question / answer pairs using the
  speaker track alone. No model calls.
- ``grounding``: verify that every ``Finding`` cites text that really exists in
  the transcript, and drop the ones that do not.
"""

from irya_ai.pipeline.grounding import (
    GroundingReport,
    GroundingResult,
    ground_finding,
    ground_findings,
    locate_quote,
)
from irya_ai.pipeline.qa_segmentation import (
    QASegmenter,
    SegmentationResult,
    is_question,
    segment_qa,
)

__all__ = [
    "GroundingReport",
    "GroundingResult",
    "QASegmenter",
    "SegmentationResult",
    "ground_finding",
    "ground_findings",
    "is_question",
    "locate_quote",
    "segment_qa",
]
