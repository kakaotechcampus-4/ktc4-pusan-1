import json
from pathlib import Path

import pytest

from irya_ai.transcript import Transcript

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_transcript() -> Transcript:
    data = json.loads(
        (FIXTURES_DIR / "sample_interview.json").read_text(encoding="utf-8")
    )
    return Transcript.model_validate(data)
