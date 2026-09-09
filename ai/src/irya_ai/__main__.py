"""Run analysis on a backend JSON snapshot without a backend server."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import ValidationError

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.config import Settings
from irya_ai.openai_summary import OpenAISummarizer
from irya_ai.summarize import ExtractiveSummarizer
from irya_ai.transcript import Transcript


async def run(args: argparse.Namespace) -> int:
    try:
        transcript = Transcript.model_validate_json(
            Path(args.input).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError):
        print(json.dumps({"error": {"code": "INVALID_TRANSCRIPT", "retryable": False}}))
        return 2

    if args.backend == "extractive":
        result = await ContextAnalysisAgent(ExtractiveSummarizer()).analyze(transcript)
    else:
        try:
            settings = Settings()
        except ValidationError:
            print(
                json.dumps({"error": {"code": "INVALID_SETTINGS", "retryable": False}})
            )
            return 2
        if not settings.openai_api_key.get_secret_value().strip():
            print(
                json.dumps(
                    {"error": {"code": "OPENAI_API_KEY_MISSING", "retryable": False}}
                )
            )
            return 2
        async with AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=settings.analysis_timeout_seconds,
            max_retries=0,
        ) as client:
            summarizer = OpenAISummarizer(
                client, model=args.model or settings.openai_model
            )
            result = await ContextAnalysisAgent(
                summarizer, timeout_seconds=settings.analysis_timeout_seconds
            ).analyze(transcript)
    print(result.model_dump_json(indent=2))
    return 1 if result.status in {"failed", "partial"} else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Backend Transcript JSON file")
    parser.add_argument("--backend", choices=["openai", "extractive"], default="openai")
    parser.add_argument("--model", choices=["gpt-4o-mini", "gpt-4o"])
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
