import json
from pathlib import Path

import pytest

from irya_ai.schemas import TranscriptSnapshot

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_transcript() -> TranscriptSnapshot:
    data = json.loads(
        (FIXTURES_DIR / "sample_interview.json").read_text(encoding="utf-8")
    )
    return TranscriptSnapshot.model_validate(data)
