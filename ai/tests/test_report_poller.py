import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from irya_ai.backend import BackendClient
from irya_ai.prep import FakePrepGenerator, PrepAgent
from irya_ai.prep_poller import PrepPoller
from irya_ai.report import ExtractiveReportGenerator, ReportAgent, ReportError
from irya_ai.schemas.prep import PrepDraft

REQUESTED = "2026-10-30T10:00:00.123456Z"
SAMPLE = json.loads(
    (Path(__file__).parents[1] / "data/samples/report_context.json").read_text()
)


@pytest.mark.parametrize("conflict", [False, True])
async def test_report_job_reads_generates_and_stores_with_exact_requested_at(conflict):
    saved = []

    def handler(request):
        if request.url.path.endswith("/jobs/pending"):
            return httpx.Response(
                200,
                json={
                    "kind": "REPORT",
                    "interviewId": SAMPLE["interviewId"],
                    "sessionId": SAMPLE["sessionId"],
                    "requestedAt": REQUESTED,
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json={**SAMPLE, "requestedAt": REQUESTED})
        saved.append(json.loads(request.content))
        return httpx.Response(409 if conflict else 204)

    async with httpx.AsyncClient(
        base_url="http://backend.test", transport=httpx.MockTransport(handler)
    ) as http:
        poller = PrepPoller(
            BackendClient(http, retries=0),
            PrepAgent(FakePrepGenerator(PrepDraft(competencies=[], resume_claims=[]))),
            report=ReportAgent(ExtractiveReportGenerator(), model="extractive"),
            wall_clock=lambda: datetime.fromisoformat(REQUESTED),
        )
        result = await poller.run_once()
    assert result.outcome == ("outdated" if conflict else "stored")
    assert saved[0]["requestedAt"] == REQUESTED
    assert saved[0]["status"] in {"completed", "partial"}
    assert saved[0]["model"] == "extractive"


@pytest.mark.parametrize("mismatch", [False, True])
async def test_retryable_report_failure_is_held_but_wrong_session_is_stored_as_failed(
    mismatch,
):
    saved = []

    class BusyGenerator:
        async def generate(self, context):
            raise ReportError("LLM_RATE_LIMITED", retryable=True)

    def handler(request):
        if request.url.path.endswith("/jobs/pending"):
            return httpx.Response(
                200,
                json={
                    "kind": "REPORT",
                    "interviewId": SAMPLE["interviewId"],
                    "sessionId": SAMPLE["sessionId"],
                    "requestedAt": REQUESTED,
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    **SAMPLE,
                    "sessionId": "wrong" if mismatch else SAMPLE["sessionId"],
                },
            )
        saved.append(json.loads(request.content))
        return httpx.Response(204)

    async with httpx.AsyncClient(
        base_url="http://backend.test", transport=httpx.MockTransport(handler)
    ) as http:
        poller = PrepPoller(
            BackendClient(http, retries=0),
            PrepAgent(FakePrepGenerator(PrepDraft(competencies=[], resume_claims=[]))),
            report=ReportAgent(BusyGenerator()),
            wall_clock=lambda: datetime.fromisoformat(REQUESTED),
        )
        result = await poller.run_once()
    assert result.outcome == ("stored" if mismatch else "held")
    if mismatch:
        assert saved[0]["status"] == "failed"
        assert saved[0]["requestedAt"] == REQUESTED
    else:
        assert saved == []


@pytest.mark.parametrize("mismatch", [False, True])
async def test_report_failure_logs_the_cause(mismatch, caplog):
    """시범 운영 기록의 '실패 n건(원인)' 칸을 로그만으로 채울 수 있어야 한다."""

    class BusyGenerator:
        async def generate(self, context):
            raise ReportError("LLM_RATE_LIMITED", retryable=True)

    def handler(request):
        if request.url.path.endswith("/jobs/pending"):
            return httpx.Response(
                200,
                json={
                    "kind": "REPORT",
                    "interviewId": SAMPLE["interviewId"],
                    "sessionId": SAMPLE["sessionId"],
                    "requestedAt": REQUESTED,
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    **SAMPLE,
                    "sessionId": "wrong" if mismatch else SAMPLE["sessionId"],
                },
            )
        return httpx.Response(204)

    with caplog.at_level("INFO", logger="irya_ai.prep_poller"):
        async with httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ) as http:
            poller = PrepPoller(
                BackendClient(http, retries=0),
                PrepAgent(
                    FakePrepGenerator(PrepDraft(competencies=[], resume_claims=[]))
                ),
                report=ReportAgent(BusyGenerator()),
                wall_clock=lambda: datetime.fromisoformat(REQUESTED),
            )
            result = await poller.run_once()

    lines = [record.getMessage() for record in caplog.records]
    assert result.outcome == ("stored" if mismatch else "held")
    if mismatch:
        stored = [line for line in lines if "stored as failed" in line]
        assert len(stored) == 1
        assert "code=CONTEXT_SESSION_MISMATCH" in stored[0]
        info = [line for line in lines if "status=failed" in line]
        assert len(info) == 1
        assert "since_request=" in info[0]
    else:
        held = [line for line in lines if "held" in line]
        assert len(held) == 1
        assert "code=LLM_RATE_LIMITED" in held[0]
        assert "since_request=" in held[0]


async def test_report_context_fetch_failure_is_held_with_the_cause_logged(caplog):
    def handler(request):
        if request.url.path.endswith("/jobs/pending"):
            return httpx.Response(
                200,
                json={
                    "kind": "REPORT",
                    "interviewId": SAMPLE["interviewId"],
                    "sessionId": SAMPLE["sessionId"],
                    "requestedAt": REQUESTED,
                },
            )
        return httpx.Response(503)

    with caplog.at_level("INFO", logger="irya_ai.prep_poller"):
        async with httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ) as http:
            poller = PrepPoller(
                BackendClient(http, retries=0),
                PrepAgent(
                    FakePrepGenerator(PrepDraft(competencies=[], resume_claims=[]))
                ),
                report=ReportAgent(ExtractiveReportGenerator(), model="extractive"),
                wall_clock=lambda: datetime.fromisoformat(REQUESTED),
            )
            result = await poller.run_once()

    assert result.outcome == "held"
    held = [
        record.getMessage()
        for record in caplog.records
        if "report job" in record.getMessage() and "held" in record.getMessage()
    ]
    assert len(held) == 1
    assert f"code={result.code}" in held[0]
    assert "since_request=" in held[0]
