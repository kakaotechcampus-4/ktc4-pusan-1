"""Command-line entry point for local development.

uv run irya-ai validate data/samples/*.json
uv run irya-ai simulate data/samples/transcript_backend_junior_01.json
uv run irya-ai simulate <script> --interim --realtime --speed 20
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from irya_ai.schemas.context import InterviewContext
from irya_ai.schemas.transcript import Utterance
from irya_ai.simulator import TranscriptSimulator, load_script
from irya_ai.simulator.script import TranscriptScript


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
    if "turns" in data:
        TranscriptScript.model_validate(data)
        return f"transcript script ({len(data['turns'])} turns)"
    if "jobDescription" in data or "job_description" in data:
        InterviewContext.model_validate(data)
        return "interview context"
    raise ValueError("unrecognised file: expected 'turns' or 'jobDescription'")


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
    script = load_script(args.path)
    simulator = TranscriptSimulator(
        script, interim_chunks=args.interim_chunks if args.interim else 0
    )
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
        "--realtime", action="store_true", help="pace output by timestamps"
    )
    simulate.add_argument(
        "--speed", type=float, default=1.0, help="realtime speed multiplier"
    )
    simulate.add_argument(
        "--json", action="store_true", help="print one camelCase JSON per line"
    )
    simulate.set_defaults(func=cmd_simulate)
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
