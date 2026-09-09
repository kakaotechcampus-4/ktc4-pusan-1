import argparse
import json

from irya_ai.__main__ import run
from irya_ai.config import Settings


async def test_offline_cli_reads_backend_fixture_and_prints_json(capsys) -> None:
    exit_code = await run(
        argparse.Namespace(
            input="tests/fixtures/sample_interview.json",
            backend="extractive",
            model=None,
        )
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["status"] == "completed"
    assert len(result["qa_pairs"]) == 2


async def test_invalid_input_does_not_echo_sensitive_data(tmp_path, capsys) -> None:
    source = tmp_path / "invalid.json"
    source.write_text('{"session_id":"private-data", "utterances":"bad"}')
    exit_code = await run(argparse.Namespace(input=str(source), backend="extractive"))
    output = capsys.readouterr().out
    assert exit_code == 2
    assert "INVALID_TRANSCRIPT" in output
    assert "private-data" not in output


async def test_missing_key_does_not_fall_back_to_fake_success(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "irya_ai.__main__.Settings",
        lambda: Settings(_env_file=None, openai_api_key=""),
    )
    exit_code = await run(
        argparse.Namespace(
            input="tests/fixtures/sample_interview.json", backend="openai", model=None
        )
    )
    assert exit_code == 2
    assert "OPENAI_API_KEY_MISSING" in capsys.readouterr().out
