"""Command-line entry point for local development.

uv run irya-ai validate data/samples/*.json
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json
uv run irya-ai simulate <script> --interim --realtime --speed 20
uv run irya-ai segment <script> [--split-sentences]
uv run irya-ai ground <findings.json> <script>
uv run irya-ai analyze <snapshot.json> [--backend extractive]
uv run irya-ai timeline <chunks.json> [--backend extractive] [--frontend]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import TypeAdapter, ValidationError

from irya_ai.analysis import ContextAnalysisAgent
from irya_ai.config import Settings
from irya_ai.openai_summary import OpenAISummarizer
from irya_ai.openai_timeline import OpenAITimelineGenerator
from irya_ai.pipeline import ground_findings, segment_qa
from irya_ai.schemas.analysis import Finding
from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.transcript import TranscriptSnapshot, Utterance
from irya_ai.simulator import TranscriptSimulator, load_script
from irya_ai.simulator.script import TranscriptScript
from irya_ai.summarize import ExtractiveSummarizer
from irya_ai.timeline import (
    DEFAULT_MAX_MOMENTS,
    ExtractiveTimelineGenerator,
    ReviewTimelineAgent,
    snapshot_from_chunks,
)

_FINDINGS = TypeAdapter(list[Finding])
_UTTERANCES = TypeAdapter(list[Utterance])


def _format_ms(ms: int) -> str:
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _format_utterance(u: Utterance) -> str:
    marker = "  " if u.is_final else "~ "
    return (
        f"{marker}[{_format_ms(u.start_ms)} - {_format_ms(u.end_ms)}] "
        f"{u.speaker.value:<11} {u.utterance_id} {u.content}"
    )


def _detect_kind(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        _FINDINGS.validate_python(data)
        return f"findings ({len(data)})"
    if "turns" in data:
        TranscriptScript.model_validate(data)
        return f"transcript script ({len(data['turns'])} turns)"
    if "jobDescription" in data or "job_description" in data:
        InterviewContext.model_validate(data)
        return "interview context"
    raise ValueError("unrecognised file: expected 'turns', 'jobDescription' or a list")


def _simulator(args: argparse.Namespace) -> TranscriptSimulator:
    return TranscriptSimulator(
        load_script(args.path),
        interim_chunks=args.interim_chunks if getattr(args, "interim", False) else 0,
        split_sentences=getattr(args, "split_sentences", False),
        latency_ms=getattr(args, "latency_ms", 0),
        synthesize_words=getattr(args, "words", False),
    )


def cmd_validate(args: argparse.Namespace) -> int:
    failures = 0
    for raw in args.paths:
        path = Path(raw)
        try:
            kind = _detect_kind(path)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            failures += 1
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            continue
        print(f"ok   {path}: {kind}")
    return 1 if failures else 0


def cmd_simulate(args: argparse.Namespace) -> int:
    simulator = _simulator(args)
    script = simulator.script
    print(f"# {script.title} ({script.session_id}, {_format_ms(script.duration_ms)})")

    if args.json:
        for utterance in simulator.events():
            print(utterance.model_dump_json(by_alias=True))
        return 0

    async def run() -> None:
        async for utterance in simulator.stream(
            realtime=args.realtime, speed=args.speed
        ):
            print(_format_utterance(utterance), flush=True)

    asyncio.run(run())
    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    simulator = _simulator(args)
    result = segment_qa(simulator.finals())
    script = simulator.script
    print(f"# {script.title} ({script.session_id}) - {len(result.qa_pairs)} Q&A pairs")

    if args.json:
        for pair in result.qa_pairs:
            print(pair.model_dump_json(by_alias=True))
        return 0

    for pair in result.qa_pairs:
        q_ids = ",".join(pair.question_utterance_ids)
        print(f"\n{pair.qa_id} [{_format_ms(pair.start_ms)}] Q ({q_ids})")
        print(f"    {pair.question_text}")
        if pair.answer_utterance_ids:
            a_ids = ",".join(pair.answer_utterance_ids)
            print(f"  A ({a_ids}, {pair.answer_word_count} words)")
            print(f"    {pair.answer_text}")
        else:
            print("  A (no answer)")
    if result.dropped:
        print("\n# dropped")
        for u, reason in result.dropped:
            print(f"  {u.utterance_id} {u.speaker.value:<11} {reason}: {u.content}")
    return 0


def cmd_ground(args: argparse.Namespace) -> int:
    findings = _FINDINGS.validate_json(Path(args.findings).read_text(encoding="utf-8"))
    simulator = TranscriptSimulator(
        load_script(args.path),
        interim_chunks=0,
        split_sentences=args.split_sentences,
        synthesize_words=args.words,
    )
    report = ground_findings(findings, simulator.finals())
    print(f"# {len(report.kept)} grounded / {len(report.rejected)} rejected")
    for f in report.kept:
        t = _format_ms(f.evidence_t_ms) if f.evidence_t_ms is not None else "--:--"
        print(f"  ok   {f.finding_id} [{t}] {f.type.value}: {f.summary}")
    for r in report.rejected:
        where = f" (found in {', '.join(r.found_in)})" if r.found_in else ""
        print(f"  DROP {r.finding_id} {r.reason}{where}: {r.finding.summary}")
    return 1 if report.rejected and args.strict else 0


async def _analyze_snapshot(args: argparse.Namespace) -> int:
    try:
        transcript = TranscriptSnapshot.model_validate_json(
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
    print(result.model_dump_json(by_alias=True, indent=2))
    return 1 if result.status in {"failed", "partial"} else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    return asyncio.run(_analyze_snapshot(args))


def load_chunks(path: Path) -> TranscriptSnapshot:
    """Read what an STT stream appended: a JSON array, JSON lines, or a snapshot."""

    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        return snapshot_from_chunks(_UTTERANCES.validate_json(text))
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1 and all(line.lstrip().startswith("{") for line in lines):
        # One JSON object per line, as ``simulate --json`` and a stream log emit.
        try:
            return snapshot_from_chunks(
                Utterance.model_validate_json(line) for line in lines
            )
        except ValidationError:
            pass  # a pretty-printed single object also starts every line with {
    data = json.loads(text)
    if isinstance(data, dict) and "utterances" in data:
        return TranscriptSnapshot.model_validate(data)
    return snapshot_from_chunks([Utterance.model_validate(data)])


async def _timeline(args: argparse.Namespace) -> int:
    try:
        snapshot = load_chunks(Path(args.input))
    except (OSError, UnicodeError, ValidationError, ValueError):
        print(json.dumps({"error": {"code": "INVALID_CHUNKS", "retryable": False}}))
        return 2

    if args.backend == "extractive":
        agent = ReviewTimelineAgent(
            ExtractiveTimelineGenerator(),
            model="extractive-baseline",
            max_moments=args.max_moments,
        )
        result = await agent.run(snapshot)
    else:
        try:
            settings = Settings()
        except ValidationError:
            print(
                json.dumps({"error": {"code": "INVALID_SETTINGS", "retryable": False}})
            )
            return 2
        missing = None
        if not settings.llm_api_key.get_secret_value().strip():
            missing = "LLM_API_KEY_MISSING"
        elif not settings.llm_base_url.strip():
            missing = "LLM_BASE_URL_MISSING"
        if missing:
            print(json.dumps({"error": {"code": missing, "retryable": False}}))
            return 2
        async with AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        ) as client:
            generator = OpenAITimelineGenerator(
                client,
                model=args.model or settings.llm_model,
                reasoning_effort=settings.llm_reasoning_effort,
            )
            agent = ReviewTimelineAgent(
                generator,
                model=generator.model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_moments=args.max_moments,
            )
            result = await agent.run(snapshot)

    if args.frontend:
        print(json.dumps(result.frontend_moments(), ensure_ascii=False, indent=2))
    else:
        print(result.model_dump_json(by_alias=True, indent=2))
    return 1 if result.status in {"failed", "partial"} else 0


def cmd_timeline(args: argparse.Namespace) -> int:
    return asyncio.run(_timeline(args))


def _add_simulator_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--split-sentences",
        action="store_true",
        help="split turns at sentence boundaries, like a VAD-chunked STT",
    )
    parser.add_argument(
        "--words", action="store_true", help="synthesize word-level timestamps"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irya-ai", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate script / context files")
    validate.add_argument("paths", nargs="+", help="JSON files to validate")
    validate.set_defaults(func=cmd_validate)

    simulate = sub.add_parser("simulate", help="replay a script as STT events")
    simulate.add_argument("path", help="transcript script JSON")
    simulate.add_argument(
        "--interim", action="store_true", help="also emit INTERIM utterances"
    )
    simulate.add_argument(
        "--interim-chunks", type=int, default=2, help="INTERIM events per turn"
    )
    simulate.add_argument(
        "--latency-ms", type=int, default=0, help="delay every event's arrival"
    )
    _add_simulator_options(simulate)
    simulate.add_argument(
        "--realtime", action="store_true", help="pace output by timestamps"
    )
    simulate.add_argument(
        "--speed", type=float, default=1.0, help="realtime speed multiplier"
    )
    simulate.add_argument(
        "--json", action="store_true", help="print one camelCase JSON per line"
    )
    simulate.set_defaults(func=cmd_simulate)

    segment = sub.add_parser("segment", help="group a script into Q&A pairs")
    segment.add_argument("path", help="transcript script JSON")
    _add_simulator_options(segment)
    segment.add_argument(
        "--json", action="store_true", help="print one camelCase JSON per line"
    )
    segment.set_defaults(func=cmd_segment)

    ground = sub.add_parser("ground", help="check findings against a script")
    ground.add_argument("findings", help="JSON list of Finding objects")
    ground.add_argument("path", help="transcript script JSON")
    _add_simulator_options(ground)
    ground.add_argument(
        "--strict", action="store_true", help="exit 1 if any finding is rejected"
    )
    ground.set_defaults(func=cmd_ground)

    analyze = sub.add_parser("analyze", help="summarize a transcript snapshot")
    analyze.add_argument("input", help="backend TranscriptSnapshot JSON file")
    analyze.add_argument(
        "--backend", choices=["openai", "extractive"], default="openai"
    )
    analyze.add_argument("--model", choices=["gpt-4o-mini", "gpt-4o"])
    analyze.set_defaults(func=cmd_analyze)

    timeline = sub.add_parser(
        "timeline", help="build the review timeline from STT chunks"
    )
    timeline.add_argument(
        "input", help="Utterance JSON array / JSON lines / TranscriptSnapshot file"
    )
    timeline.add_argument("--backend", choices=["llm", "extractive"], default="llm")
    timeline.add_argument("--model", help="override LLM_MODEL from .env")
    timeline.add_argument(
        "--max-moments",
        type=int,
        choices=range(1, DEFAULT_MAX_MOMENTS + 1),
        default=DEFAULT_MAX_MOMENTS,
        help="marker cap (1-8)",
    )
    timeline.add_argument(
        "--frontend",
        action="store_true",
        help="print only the moments in the frontend Moment shape (atSec)",
    )
    timeline.set_defaults(func=cmd_timeline)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page; transcripts are UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
