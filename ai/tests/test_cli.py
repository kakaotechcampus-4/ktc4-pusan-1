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


CHUNKS = SAMPLES / "chunks_backend_junior_01.json"


def test_timeline_offline_chunks_prints_moments(capsys) -> None:
    code = main(["timeline", str(CHUNKS), "--backend", "extractive"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["status"] == "completed"
    assert 5 <= len(result["moments"]) <= 8
    assert result["moments"][0]["atMs"] == 0
    assert "evidence" in result["moments"][0]


def test_timeline_frontend_flag_emits_moment_shape(capsys) -> None:
    code = main(["timeline", str(CHUNKS), "--backend", "extractive", "--frontend"])
    moments = json.loads(capsys.readouterr().out)

    assert code == 0
    assert set(moments[0]) == {"id", "atSec", "label", "question", "answer"}
    assert moments[1]["atSec"] == 25.1


def test_timeline_accepts_json_lines_and_snapshot(tmp_path: Path, capsys) -> None:
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    lines = tmp_path / "chunks.jsonl"
    lines.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8"
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"sessionId": chunks[0]["sessionId"], "utterances": chunks}),
        encoding="utf-8",
    )

    for source in (lines, snapshot):
        code = main(["timeline", str(source), "--backend", "extractive"])
        assert code == 0
        assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_timeline_max_moments_caps_and_warns(capsys) -> None:
    code = main(
        ["timeline", str(CHUNKS), "--backend", "extractive", "--max-moments", "3"]
    )
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert len(result["moments"]) == 3
    assert "QUESTIONS_TRUNCATED" in result["warnings"]


def test_timeline_invalid_input_does_not_echo_content(tmp_path: Path, capsys) -> None:
    source = tmp_path / "bad.json"
    source.write_text('[{"utteranceId": "secret-text", "speaker": "NOBODY"}]')

    code = main(["timeline", str(source), "--backend", "extractive"])
    output = capsys.readouterr().out

    assert code == 2
    assert "INVALID_CHUNKS" in output
    assert "secret-text" not in output


def test_timeline_missing_llm_settings_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "irya_ai.cli.Settings",
        lambda: Settings(_env_file=None, llm_api_key="", llm_base_url=""),
    )

    code = main(["timeline", str(CHUNKS)])

    assert code == 2
    assert "LLM_API_KEY_MISSING" in capsys.readouterr().out
