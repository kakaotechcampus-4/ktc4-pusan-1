import json
from pathlib import Path

import pytest

from irya_ai.schemas import InterviewContext
from irya_ai.simulator import TranscriptSimulator, load_script

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SCRIPTS = sorted(SAMPLES.glob("transcript_*.json"))
CONTEXTS = sorted(SAMPLES.glob("context_*.json"))


def test_sample_directory_is_populated() -> None:
    assert SCRIPTS, "no transcript samples found"
    assert CONTEXTS, "no context samples found"


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_transcript_sample_replays_cleanly(path: Path) -> None:
    script = load_script(path)
    simulator = TranscriptSimulator(script, interim_chunks=2)

    finals = simulator.finals()
    assert len(finals) == len(script.turns)
    assert len(simulator.tracks()) == 2
    assert all(u.session_id == script.session_id for u in finals)


@pytest.mark.parametrize("path", CONTEXTS, ids=lambda p: p.name)
def test_context_sample_validates(path: Path) -> None:
    context = InterviewContext.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )

    assert context.competencies, "context should list competencies"
    assert context.resume_claims, "context should list resume claims"
    jd_id = context.job_description.jd_id
    assert all(c.jd_id == jd_id for c in context.competencies)


def test_first_sample_pair_share_session_id() -> None:
    script = load_script(SAMPLES / "transcript_backend_junior_01.json")
    context = InterviewContext.model_validate(
        json.loads(
            (SAMPLES / "context_backend_junior.json").read_text(encoding="utf-8")
        )
    )

    assert script.session_id == context.session_id
