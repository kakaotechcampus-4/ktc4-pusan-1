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
