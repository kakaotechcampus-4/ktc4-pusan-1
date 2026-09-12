import json
from pathlib import Path

import pytest

from irya_ai.cli import main
from irya_ai.config import Settings

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
SCRIPT = SAMPLES / "transcript_backend_junior_01.json"
CONTEXT = SAMPLES / "context_backend_junior.json"
SNAPSHOT = Path(__file__).parent / "fixtures" / "sample_interview.json"


def test_validate_accepts_samples(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["validate", str(SCRIPT), str(CONTEXT)])
    out = capsys.readouterr().out

    assert code == 0
    assert "transcript script" in out
    assert "interview context" in out


def test_validate_reports_broken_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"turns": []}', encoding="utf-8")

    code = main(["validate", str(broken)])
    err = capsys.readouterr().err

    assert code == 1
    assert "FAIL" in err


def test_simulate_prints_final_utterances(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["simulate", str(SCRIPT)])
    lines = capsys.readouterr().out.splitlines()

    assert code == 0
    assert lines[0].startswith("# ")
    body = lines[1:]
    assert len(body) == 15
    assert all("~" not in line[:2] for line in body)
    assert "INTERVIEWER" in body[0]


def test_simulate_interim_flag_adds_provisional_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["simulate", str(SCRIPT), "--interim", "--interim-chunks", "1"])
    body = capsys.readouterr().out.splitlines()[1:]

    interim = [line for line in body if line.startswith("~")]
    assert interim
    assert len(body) > 15


def test_simulate_json_emits_camel_case_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["simulate", str(SCRIPT), "--json"])
    body = capsys.readouterr().out.splitlines()[1:]

    first = json.loads(body[0])
    assert first["utteranceId"] == "utt_000"
    assert first["passType"] == "FINAL"
    assert "start_ms" not in first


def test_analyze_offline_snapshot_prints_json(capsys) -> None:
    code = main(["analyze", str(SNAPSHOT), "--backend", "extractive"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["status"] == "completed"
    assert len(result["qaPairs"]) == 2
    assert result["transcriptStage"] == "LIVE"


def test_analyze_invalid_input_does_not_echo_sensitive_data(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "invalid.json"
    source.write_text('{"sessionId":"private-data", "utterances":"bad"}')

    code = main(["analyze", str(source), "--backend", "extractive"])
    output = capsys.readouterr().out

    assert code == 2
    assert "INVALID_TRANSCRIPT" in output
    assert "private-data" not in output


def test_analyze_missing_key_does_not_fall_back_to_fake_success(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "irya_ai.cli.Settings",
        lambda: Settings(_env_file=None, openai_api_key=""),
    )

    code = main(["analyze", str(SNAPSHOT), "--backend", "openai"])

    assert code == 2
    assert "OPENAI_API_KEY_MISSING" in capsys.readouterr().out
