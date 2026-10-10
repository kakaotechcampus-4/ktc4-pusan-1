"""The prep poller: one job from Backend's queue, through the agent, back.

Backend is a fake over ``httpx.MockTransport`` that keeps a queue of pending
jobs and records what was put back, so each test states what Backend holds
and checks what the poller did with it.
"""

import asyncio
import json
import logging

import httpx
import pytest

from irya_ai.backend import BackendClient
from irya_ai.config import Settings
from irya_ai.prep import FakePrepGenerator, PrepAgent, PrepError
from irya_ai.prep_poller import (
    HOLD_PRUNE_SIZE,
    PollerError,
    PrepPoller,
    build_prep_agent,
    context_from_response,
)
from irya_ai.schemas.jobs import PendingJob
from irya_ai.schemas.prep import CompetencyDraft, PrepDraft, ResumeClaimDraft

REQUESTED_AT = "2026-10-06T00:00:00.123456Z"
RESUME_TEXT = (
    "경력\n- 상품 조회 API에 Redis 캐시를 도입하여 응답 시간을 60% 단축했습니다."
)
QUOTE = "상품 조회 API에 Redis 캐시를 도입하여 응답 시간을 60% 단축했습니다."


def job(
    interview_id: str = "int_1",
    session_id: str = "ses_1",
    requested_at: str = REQUESTED_AT,
    kind: str = "PREP",
) -> dict:
    return {
        "kind": kind,
        "sessionId": session_id,
        "interviewId": interview_id,
        "requestedAt": requested_at,
    }


def context(
    session_id: str = "ses_1", *, resume: dict | None | str = "default"
) -> dict:
    """Backend's context answer as #165 shapes it, utterances included."""

    data = {
        "sessionId": session_id,
        "company": {"companyId": "ctx_1", "name": "누리뱅크", "culture": None},
        "jobDescription": {
            "jdId": "ctx_1",
            "companyId": "ctx_1",
            "title": "백엔드 개발자",
            "description": "상품 조회·주문 API를 개발하고 운영합니다.",
        },
        "competencies": [],
        "rubric": None,
        "candidate": {"candidateId": "int_1", "name": ""},
        "resumeClaims": [],
        "utterances": [
            {
                "utteranceId": "utt_TR_b_0016",
                "sessionId": session_id,
                "trackId": "TR_b",
                "speaker": "CANDIDATE",
                "seq": 268900000003,
                "startMs": 268900,
                "endMs": 274100,
                "content": "네, 안녕하세요.",
            }
        ],
    }
    if resume == "default":
        data["resume"] = {
            "resumeId": "doc_1",
            "candidateId": "int_1",
            "storageKey": None,
            "text": RESUME_TEXT,
        }
    else:
        data["resume"] = resume
    return data


def draft() -> PrepDraft:
    return PrepDraft(
        competencies=[
            CompetencyDraft(
                name="성능 개선", required=True, description="캐시로 병목 해결"
            )
        ],
        resume_claims=[ResumeClaimDraft(quote=QUOTE, section="경력")],
    )


class FakeBackend:
    """Backend's three poller routes with a queue the test fills."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.contexts: dict[str, dict] = {}
        self.put_status: int = 204
        self.put_bodies: list[dict] = []
        self.pending_calls = 0
        self.context_status: int = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/internal/v1/jobs/pending":
            self.pending_calls += 1
            return httpx.Response(200, json=self.jobs[0] if self.jobs else None)
        if request.method == "GET" and path.endswith("/context"):
            if self.context_status != 200:
                return httpx.Response(self.context_status)
            session_id = path.split("/")[-2]
            if session_id not in self.contexts:
                return httpx.Response(404)
            return httpx.Response(200, json=self.contexts[session_id])
        if request.method == "PUT" and path.endswith("/prep"):
            self.put_bodies.append(json.loads(request.content))
            if self.put_status == 204:
                # A stored result leaves the queue, like Backend's row does.
                interview_id = path.split("/")[-2]
                self.jobs = [j for j in self.jobs if j["interviewId"] != interview_id]
                return httpx.Response(204)
            return httpx.Response(self.put_status)
        return httpx.Response(404)

    def client(self) -> BackendClient:
        return BackendClient(
            httpx.AsyncClient(
                base_url="https://backend.invalid",
                transport=httpx.MockTransport(self.handler),
            ),
            backoff_seconds=0.0,
        )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Failing:
    """A generator that fails the way the model call can."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable

    async def generate(self, context):  # noqa: ANN001
        raise PrepError(self.code, retryable=self.retryable)


def poller_for(
    backend: FakeBackend,
    generator=None,  # noqa: ANN001
    *,
    clock: Clock | None = None,
    **kwargs,
) -> PrepPoller:
    agent = PrepAgent(generator or FakePrepGenerator(draft()), model="fake")
    return PrepPoller(backend.client(), agent, clock=clock or Clock(), **kwargs)


# --- one pass ----------------------------------------------------------------


async def test_an_empty_queue_is_an_idle_pass() -> None:
    backend = FakeBackend()

    done = await poller_for(backend).run_once()

    assert done.outcome == "idle"
    assert backend.put_bodies == []


async def test_a_prep_job_is_run_and_stored_with_the_request_it_answers() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()

    done = await poller_for(backend).run_once()

    assert done.outcome == "stored"
    assert done.result is not None and done.result.status == "completed"
    body = backend.put_bodies[0]
    # The result as it stands, plus the request it answers, byte for byte.
    assert body["requestedAt"] == REQUESTED_AT
    assert body["status"] == "completed"
    assert body["sessionId"] == "ses_1"
    assert [c["name"] for c in body["competencies"]] == ["성능 개선"]
    assert [c["quote"] for c in body["resumeClaims"]] == [QUOTE]
    assert body["competencies"][0]["competencyId"].startswith("cpt_")
    assert body["resumeClaims"][0]["claimId"].startswith("clm_")
    # Stored, so the queue moved on.
    assert backend.jobs == []


async def test_the_utterances_in_the_context_answer_are_set_aside() -> None:
    payload = context()
    assert payload["utterances"]  # the fixture carries one

    parsed = context_from_response(payload)

    assert parsed.session_id == "ses_1"
    assert parsed.resume is not None and parsed.resume.text == RESUME_TEXT


async def test_a_context_without_a_resume_still_prepares() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context(resume=None)
    # The model drafts only competencies when there is nothing to quote.
    no_claims = PrepDraft(competencies=draft().competencies, resume_claims=[])

    done = await poller_for(backend, FakePrepGenerator(no_claims)).run_once()

    assert done.outcome == "stored"
    assert done.result is not None
    assert done.result.status == "completed"
    assert done.result.resume_claims == []
    assert "NO_RESUME_TEXT" in done.result.warnings


def test_a_context_that_does_not_fit_the_model_is_a_contract_mismatch() -> None:
    payload = context()
    payload["somethingNew"] = 1

    with pytest.raises(PollerError) as caught:
        context_from_response(payload)

    assert caught.value.code == "CONTEXT_INVALID"
    assert caught.value.retryable is False


async def test_an_outdated_result_is_dropped_and_the_pass_moves_on() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()
    backend.put_status = 409

    done = await poller_for(backend).run_once()

    assert done.outcome == "outdated"
    assert done.code == "BACKEND_CONFLICT"
    assert len(backend.put_bodies) == 1


async def test_a_job_kind_it_does_not_know_is_left_to_backend() -> None:
    backend = FakeBackend()
    backend.jobs = [job(kind="REVIEW")]
    poller = poller_for(backend)

    done = await poller.run_once()

    assert done.outcome == "held"
    assert done.code == "UNSUPPORTED_JOB_KIND"
    assert backend.put_bodies == []
    assert ("int_1", REQUESTED_AT) in poller.holds


# --- holds: a job this process cannot finish is not asked for at the poll rate


async def test_a_retryable_agent_failure_is_held_not_stored() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()
    clock = Clock()
    poller = poller_for(
        backend,
        Failing("LLM_RATE_LIMITED", retryable=True),
        clock=clock,
        retry_after_seconds=30.0,
    )

    done = await poller.run_once()

    assert done.outcome == "held"
    assert done.code == "LLM_RATE_LIMITED"
    assert backend.put_bodies == []  # not stored as FAILED
    # Within the hold the same job is skipped without touching the agent.
    clock.now += 29.0
    assert (await poller.run_once()).outcome == "idle"
    # After it, the job is tried again.
    clock.now += 2.0
    assert (await poller.run_once()).outcome == "held"


async def test_a_failure_that_would_repeat_is_stored_as_failed() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()
    poller = poller_for(backend, Failing("LLM_REFUSED", retryable=False))

    done = await poller.run_once()

    assert done.outcome == "stored"
    assert backend.put_bodies[0]["status"] == "failed"
    assert backend.put_bodies[0]["error"] == {"code": "LLM_REFUSED", "retryable": False}
    assert backend.put_bodies[0]["requestedAt"] == REQUESTED_AT


async def test_a_context_that_cannot_be_read_is_held_for_the_give_up_time() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context() | {"somethingNew": 1}
    clock = Clock()
    poller = poller_for(
        backend, clock=clock, retry_after_seconds=30.0, give_up_seconds=600.0
    )

    done = await poller.run_once()

    assert done.outcome == "held"
    assert done.code == "CONTEXT_INVALID"
    clock.now += 599.0
    assert (await poller.run_once()).outcome == "idle"
    clock.now += 2.0
    assert (await poller.run_once()).outcome == "held"


async def test_a_context_about_another_session_is_not_stored() -> None:
    backend = FakeBackend()
    backend.jobs = [job(session_id="ses_1")]
    backend.contexts["ses_1"] = context(session_id="ses_other")

    done = await poller_for(backend).run_once()

    assert done.outcome == "held"
    assert done.code == "CONTEXT_SESSION_MISMATCH"
    assert backend.put_bodies == []


async def test_a_backend_that_cannot_serve_the_context_is_retried_later() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.context_status = 503
    clock = Clock()
    poller = poller_for(backend, clock=clock, retry_after_seconds=30.0)

    done = await poller.run_once()

    assert done.outcome == "held"
    assert done.code == "BACKEND_REQUEST_FAILED"
    clock.now += 31.0
    backend.context_status = 200
    backend.contexts["ses_1"] = context()
    assert (await poller.run_once()).outcome == "stored"


async def test_a_replaced_request_is_a_new_job_even_while_the_old_one_is_held() -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()
    poller = poller_for(backend, Failing("LLM_TIMEOUT", retryable=True))
    assert (await poller.run_once()).outcome == "held"

    # The resume was re-uploaded: same interview, new requestedAt.
    backend.jobs = [job(requested_at="2026-10-06T00:01:00.000000Z")]
    poller.agent = PrepAgent(FakePrepGenerator(draft()), model="fake")

    done = await poller.run_once()

    assert done.outcome == "stored"
    assert backend.put_bodies[0]["requestedAt"] == "2026-10-06T00:01:00.000000Z"


async def test_a_backend_that_is_down_is_an_idle_pass() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = BackendClient(
        httpx.AsyncClient(
            base_url="https://backend.invalid", transport=httpx.MockTransport(refuse)
        ),
        backoff_seconds=0.0,
    )
    poller = PrepPoller(client, PrepAgent(FakePrepGenerator(draft()), model="fake"))

    done = await poller.run_once()

    assert done.outcome == "idle"
    assert done.code == "BACKEND_REQUEST_FAILED"


def test_holds_are_pruned_once_they_pile_up() -> None:
    backend = FakeBackend()
    clock = Clock()
    poller = poller_for(backend, clock=clock, give_up_seconds=10.0)
    for i in range(HOLD_PRUNE_SIZE):
        poller._hold(PendingJob.model_validate(job(interview_id=f"int_{i}")), 10.0)
    clock.now += 11.0

    poller._hold(PendingJob.model_validate(job(interview_id="int_new")), 10.0)

    assert list(poller.holds) == [("int_new", REQUESTED_AT)]


# --- the loop ----------------------------------------------------------------


async def test_the_loop_works_the_queue_down_and_then_waits() -> None:
    backend = FakeBackend()
    backend.jobs = [job("int_1", "ses_1"), job("int_2", "ses_2")]
    backend.contexts["ses_1"] = context("ses_1")
    backend.contexts["ses_2"] = context("ses_2")
    poller = poller_for(backend, poll_interval_seconds=0.05)
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.2)
        stop.set()

    await asyncio.gather(poller.run_forever(stop), stop_soon())

    assert [b["sessionId"] for b in backend.put_bodies] == ["ses_1", "ses_2"]
    # Two jobs, then idle polls at the interval - not a hot loop.
    assert 3 <= backend.pending_calls <= 8


async def test_the_loop_survives_a_pass_that_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = FakeBackend()
    poller = poller_for(backend, poll_interval_seconds=0.02)
    calls = 0

    async def explode() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    poller.run_once = explode  # type: ignore[method-assign]
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.1)
        stop.set()

    with caplog.at_level(logging.ERROR):
        await asyncio.gather(poller.run_forever(stop), stop_soon())

    assert calls >= 2
    assert "prep poller pass failed" in caplog.text


async def test_the_loop_stops_promptly_when_asked() -> None:
    backend = FakeBackend()
    poller = poller_for(backend, poll_interval_seconds=60.0)
    stop = asyncio.Event()
    task = asyncio.create_task(poller.run_forever(stop))
    await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=1.0)


# --- logs name ids and outcomes, never the resume or the candidate -----------


async def test_logs_carry_ids_and_outcome_but_not_the_resume(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = FakeBackend()
    backend.jobs = [job()]
    backend.contexts["ses_1"] = context()
    backend.contexts["ses_1"]["candidate"]["name"] = "김도현"

    with caplog.at_level(logging.INFO, logger="irya_ai.prep_poller"):
        await poller_for(backend).run_once()

    line = next(r.getMessage() for r in caplog.records if "prep job" in r.getMessage())
    assert "interview=int_1" in line and "status=completed" in line
    assert "agent=" in line and "total=" in line
    assert "김도현" not in caplog.text
    assert "Redis" not in caplog.text


# --- wiring ------------------------------------------------------------------


def test_the_agent_is_the_project_llm_only_when_both_values_are_set() -> None:
    bare = Settings(_env_file=None)
    agent, client = build_prep_agent(bare)
    assert client is None
    assert agent.model == "extractive-baseline"

    configured = Settings(
        _env_file=None, llm_base_url="https://gateway.invalid/dep", llm_api_key="k"
    )
    agent, client = build_prep_agent(configured)
    try:
        assert client is not None
        assert agent.model == configured.llm_model
        assert agent.timeout_seconds == configured.llm_timeout_seconds
    finally:
        if client is not None:
            asyncio.run(client.close())


def test_poller_settings_have_sane_defaults_and_bounds() -> None:
    settings = Settings(_env_file=None)
    assert settings.prep_poll_interval_seconds == 5
    assert settings.prep_retry_after_seconds == 30
    with pytest.raises(ValueError):
        Settings(_env_file=None, prep_poll_interval_seconds=0)


def test_a_pending_job_ignores_fields_backend_adds_later() -> None:
    parsed = PendingJob.model_validate(job() | {"claimedAt": None})

    assert parsed.key == ("int_1", REQUESTED_AT)
    assert parsed.requested_at == REQUESTED_AT
