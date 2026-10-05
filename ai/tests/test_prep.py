"""Pre-interview preparation: verification, identifiers and run statuses.

No model and no network. Drafts are built by hand, the way a model would
return them, and the tests pin what survives and why the rest does not.
"""

import asyncio
import json
import re

import pytest

from irya_ai.prep import (
    DEFAULT_MAX_CLAIMS,
    DEFAULT_MAX_COMPETENCIES,
    FakePrepGenerator,
    PrepAgent,
    PrepError,
    PrepGenerator,
    build_prep,
    claim_id,
    competency_id,
)
from irya_ai.schemas import (
    CompetencyDraft,
    InterviewContext,
    PrepDraft,
    ResumeClaimDraft,
)
from irya_ai.schemas.timeline import LlmUsage

RESUME_TEXT = """\
정OO | 백엔드 개발자

프로젝트
상품 조회 API에 Redis 캐시를 도입하여 응답 시간을 60% 단축했습니다.
4인 팀 프로젝트에서 백엔드 파트 리드로 API 설계와
일정 관리를 담당했습니다.

기술
Python, FastAPI, PostgreSQL, Redis
부하 테스트로 초당 3,000건 요청 처리를 확인했습니다.
"""

CACHE_QUOTE = "상품 조회 API에 Redis 캐시를 도입하여 응답 시간을 60% 단축했습니다."
LEAD_QUOTE = (
    "4인 팀 프로젝트에서 백엔드 파트 리드로 API 설계와 일정 관리를 담당했습니다."
)
LOAD_QUOTE = "부하 테스트로 초당 3,000건 요청 처리를 확인했습니다."


def make_context(
    *,
    resume_text: str | None = RESUME_TEXT,
    with_resume: bool = True,
    jd_description: str = "상품 조회·주문 API를 개발하고 운영합니다.",
) -> InterviewContext:
    data: dict = {
        "sessionId": "ses_prep_01",
        "company": {"companyId": "cmp_1", "name": "누리뱅크"},
        "jobDescription": {
            "jdId": "jd_backend",
            "companyId": "cmp_1",
            "title": "백엔드 개발자",
            "description": jd_description,
        },
        "candidate": {"candidateId": "cnd_1", "name": "정OO"},
    }
    if with_resume:
        data["resume"] = {
            "resumeId": "doc_resume_1",
            "candidateId": "cnd_1",
            "text": resume_text,
        }
    return InterviewContext.model_validate(data)


def competency(
    name: str = "성능 개선",
    *,
    required: bool = True,
    description: str = "병목을 찾아 캐시나 쿼리 개선으로 해결한 경험",
) -> CompetencyDraft:
    return CompetencyDraft(name=name, required=required, description=description)


def claim(
    quote: str = CACHE_QUOTE, section: str | None = "프로젝트"
) -> ResumeClaimDraft:
    return ResumeClaimDraft(quote=quote, section=section)


def draft_of(
    competencies: list[CompetencyDraft] | None = None,
    claims: list[ResumeClaimDraft] | None = None,
) -> PrepDraft:
    return PrepDraft(
        competencies=[competency()] if competencies is None else competencies,
        resume_claims=[] if claims is None else claims,
    )


# --- identifiers -------------------------------------------------------------


def test_ids_have_a_prefix_and_eight_hex_chars() -> None:
    assert re.fullmatch(r"cpt_[0-9a-f]{8}", competency_id("성능 개선"))
    assert re.fullmatch(r"clm_[0-9a-f]{8}", claim_id(CACHE_QUOTE))


def test_ids_depend_on_content_alone() -> None:
    assert claim_id(CACHE_QUOTE) == claim_id(CACHE_QUOTE)
    assert claim_id(CACHE_QUOTE) != claim_id(LOAD_QUOTE)
    assert competency_id("성능 개선") != competency_id("협업")


def test_ids_ignore_whitespace_runs_and_unicode_form() -> None:
    assert claim_id("API 설계와\n  일정 관리") == claim_id("API 설계와 일정 관리")
    # NFD (decomposed Hangul, as macOS produces) and NFC are one string here.
    assert competency_id("성능") == competency_id("성능")


def test_competency_id_folds_case_but_claim_id_does_not() -> None:
    assert competency_id("API 설계") == competency_id("api 설계")
    assert claim_id("API 설계와 일정 관리를 담당") != claim_id(
        "api 설계와 일정 관리를 담당"
    )


def test_reordering_the_draft_does_not_move_ids() -> None:
    context = make_context()
    forward = draft_of(
        [competency("성능 개선"), competency("협업")],
        [claim(CACHE_QUOTE), claim(LOAD_QUOTE)],
    )
    backward = draft_of(
        [competency("협업"), competency("성능 개선")],
        [claim(LOAD_QUOTE), claim(CACHE_QUOTE)],
    )

    first_competencies, first_claims, _ = build_prep(context, forward)
    second_competencies, second_claims, _ = build_prep(context, backward)

    assert {c.name: c.competency_id for c in first_competencies} == {
        c.name: c.competency_id for c in second_competencies
    }
    assert {c.quote: c.claim_id for c in first_claims} == {
        c.quote: c.claim_id for c in second_claims
    }


# --- verification: the happy path -------------------------------------------


def test_verified_drafts_become_competencies_and_claims() -> None:
    context = make_context()
    draft = draft_of(
        [competency("성능 개선"), competency("협업", required=False)],
        [claim(CACHE_QUOTE, "프로젝트"), claim(LOAD_QUOTE, None)],
    )

    competencies, claims, rejections = build_prep(context, draft)

    assert rejections == []
    assert [c.name for c in competencies] == ["성능 개선", "협업"]
    assert [c.required for c in competencies] == [True, False]
    assert all(c.jd_id == "jd_backend" for c in competencies)
    assert competencies[0].competency_id == competency_id("성능 개선")
    assert [c.quote for c in claims] == [CACHE_QUOTE, LOAD_QUOTE]
    assert [c.section for c in claims] == ["프로젝트", None]
    assert all(c.resume_id == "doc_resume_1" for c in claims)
    assert claims[0].claim_id == claim_id(CACHE_QUOTE)


def test_a_quote_across_a_line_break_is_found_and_stored_on_one_line() -> None:
    # The resume breaks this sentence over two lines, as extracted PDFs do.
    assert LEAD_QUOTE not in RESUME_TEXT

    _, claims, rejections = build_prep(
        make_context(), draft_of(claims=[claim(LEAD_QUOTE)])
    )

    assert rejections == []
    assert claims[0].quote == LEAD_QUOTE
    assert "\n" not in claims[0].quote


def test_whitespace_in_names_and_sections_is_collapsed() -> None:
    draft = draft_of(
        [competency("  성능   개선 ", description=" 병목을  찾은\n경험 ")],
        [claim(CACHE_QUOTE, "  프로젝트  ")],
    )

    competencies, claims, rejections = build_prep(make_context(), draft)

    assert rejections == []
    assert competencies[0].name == "성능 개선"
    assert competencies[0].description == "병목을 찾은 경험"
    assert claims[0].section == "프로젝트"


def test_a_blank_section_becomes_none() -> None:
    _, claims, rejections = build_prep(
        make_context(), draft_of(claims=[claim(CACHE_QUOTE, "   ")])
    )

    assert rejections == []
    assert claims[0].section is None


# --- verification: rejections -------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (competency("   "), "empty name"),
        (competency("가" * 21), "name longer than 20 chars"),
        (competency(description="  "), "empty description"),
        (competency(description="가" * 121), "description longer than 120 chars"),
    ],
)
def test_malformed_competencies_are_rejected(bad: CompetencyDraft, reason: str) -> None:
    draft = draft_of([competency("협업"), bad])

    competencies, _, rejections = build_prep(make_context(), draft)

    assert [c.name for c in competencies] == ["협업"]
    assert rejections == [f"competency 2: {reason}"]


def test_a_competency_at_the_length_limits_is_kept() -> None:
    draft = draft_of([competency("가" * 20, description="나" * 120)])

    competencies, _, rejections = build_prep(make_context(), draft)

    assert rejections == []
    assert len(competencies) == 1


def test_the_same_competency_twice_is_kept_once() -> None:
    draft = draft_of(
        [competency("API 설계"), competency("api  설계"), competency("협업")]
    )

    competencies, _, rejections = build_prep(make_context(), draft)

    assert [c.name for c in competencies] == ["API 설계", "협업"]
    assert rejections == ["competency 2: duplicate of an earlier competency"]


def test_competencies_past_the_limit_are_rejected_not_cut_silently() -> None:
    names = [f"역량 {n}" for n in range(1, DEFAULT_MAX_COMPETENCIES + 3)]

    competencies, _, rejections = build_prep(
        make_context(), draft_of([competency(n) for n in names])
    )

    assert [c.name for c in competencies] == names[:DEFAULT_MAX_COMPETENCIES]
    assert rejections == [
        f"competency {DEFAULT_MAX_COMPETENCIES + 1}: over the 6 competency limit",
        f"competency {DEFAULT_MAX_COMPETENCIES + 2}: over the 6 competency limit",
    ]


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (claim("   "), "empty quote"),
        (claim("Redis 캐시"), "quote shorter than 10 chars"),
        (claim("가" * 201), "quote longer than 200 chars"),
        # A paraphrase: every word is on the page, the sentence is not.
        (
            claim("Redis 캐시를 도입해 상품 조회 API 응답 시간을 60% 줄였습니다."),
            "quote not found in resume",
        ),
        # Letter case is part of the text. ``api`` is not what was written.
        (
            claim("상품 조회 api에 Redis 캐시를 도입하여"),
            "quote not found in resume",
        ),
        # A spacing fix is still an edit.
        (
            claim("상품조회 API에 Redis 캐시를 도입하여"),
            "quote not found in resume",
        ),
        (claim(CACHE_QUOTE, "가" * 21), "section longer than 20 chars"),
    ],
)
def test_claims_that_do_not_quote_the_resume_are_rejected(
    bad: ResumeClaimDraft, reason: str
) -> None:
    draft = draft_of(claims=[claim(LOAD_QUOTE), bad])

    _, claims, rejections = build_prep(make_context(), draft)

    assert [c.quote for c in claims] == [LOAD_QUOTE]
    assert rejections == [f"claim 2: {reason}"]


def test_the_same_quote_twice_is_kept_once() -> None:
    respaced = CACHE_QUOTE.replace(" ", "  ", 1)

    _, claims, rejections = build_prep(
        make_context(), draft_of(claims=[claim(CACHE_QUOTE), claim(respaced)])
    )

    assert len(claims) == 1
    assert rejections == ["claim 2: duplicate of an earlier claim"]


def test_claims_past_the_limit_are_rejected() -> None:
    sentences = [f"프로젝트 {n:02d}번에서 결제 모듈을 구현했습니다." for n in range(14)]
    context = make_context(resume_text="\n".join(sentences))

    _, claims, rejections = build_prep(
        context, draft_of(claims=[claim(s) for s in sentences])
    )

    assert len(claims) == DEFAULT_MAX_CLAIMS
    assert rejections == [
        "claim 13: over the 12 claim limit",
        "claim 14: over the 12 claim limit",
    ]


@pytest.mark.parametrize(
    "context",
    [
        make_context(with_resume=False),
        make_context(resume_text=None),
        make_context(resume_text="   \n "),
    ],
    ids=["no resume", "text not extracted", "blank text"],
)
def test_claims_without_a_resume_body_are_all_rejected(
    context: InterviewContext,
) -> None:
    competencies, claims, rejections = build_prep(
        context, draft_of(claims=[claim(CACHE_QUOTE)])
    )

    assert len(competencies) == 1
    assert claims == []
    assert rejections == ["claim 1: no resume text to quote"]


def test_rejections_never_carry_resume_text_or_draft_text() -> None:
    secret = "주민등록번호 뒷자리는 1234567 입니다 라는 문장"
    draft = draft_of(
        [competency("가" * 30)],
        [claim(secret), claim("본문에 없는 문장을 지어낸 인용입니다.")],
    )

    _, _, rejections = build_prep(make_context(), draft)

    assert len(rejections) == 3
    joined = "\n".join(rejections)
    assert secret not in joined
    assert "지어낸" not in joined
    assert "가가가" not in joined
    assert all(re.match(r"(competency|claim) \d+: ", r) for r in rejections)


@pytest.mark.parametrize("field", ["max_competencies", "max_claims"])
def test_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        build_prep(make_context(), draft_of(), **{field: 0})


# --- agent -----------------------------------------------------------------------


def three_competencies() -> list[CompetencyDraft]:
    return [competency("성능 개선"), competency("협업"), competency("장애 대응")]


async def test_a_clean_run_completes() -> None:
    generator = FakePrepGenerator(
        draft_of(three_competencies(), [claim(CACHE_QUOTE), claim(LOAD_QUOTE)])
    )

    result = await PrepAgent(generator, model="stub").run(make_context())

    assert result.status == "completed"
    assert result.session_id == "ses_prep_01"
    assert len(result.competencies) == 3
    assert len(result.resume_claims) == 2
    assert result.rejections == []
    assert result.warnings == []
    assert result.error is None
    assert result.model == "stub"
    assert generator.calls == ["ses_prep_01"]


async def test_dropped_drafts_make_the_run_partial() -> None:
    generator = FakePrepGenerator(
        draft_of(
            three_competencies(),
            [claim(CACHE_QUOTE), claim("이력서에 없는 문장입니다.")],
        )
    )

    result = await PrepAgent(generator).run(make_context())

    assert result.status == "partial"
    assert len(result.resume_claims) == 1
    assert result.rejections == ["claim 2: quote not found in resume"]
    assert "DRAFTS_REMOVED" in result.warnings


async def test_no_surviving_competency_is_a_failure() -> None:
    generator = FakePrepGenerator(draft_of([competency("  ")], [claim(CACHE_QUOTE)]))

    result = await PrepAgent(generator).run(make_context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "NO_COMPETENCIES"
    assert result.error.retryable is False
    assert result.competencies == []
    # Claims are not reported without the competencies they would hang on.
    assert result.resume_claims == []
    assert result.rejections == ["competency 1: empty name"]


async def test_a_blank_job_description_is_empty_and_never_reaches_the_model() -> None:
    generator = FakePrepGenerator(draft_of(three_competencies()))

    result = await PrepAgent(generator).run(make_context(jd_description="  \n"))

    assert result.status == "empty"
    assert result.warnings == ["NO_JOB_DESCRIPTION"]
    assert result.competencies == []
    assert generator.calls == []


@pytest.mark.parametrize(
    "context",
    [make_context(with_resume=False), make_context(resume_text=None)],
    ids=["no resume", "text not extracted"],
)
async def test_a_missing_resume_still_completes(context: InterviewContext) -> None:
    generator = FakePrepGenerator(draft_of(three_competencies()))

    result = await PrepAgent(generator).run(context)

    assert result.status == "completed"
    assert result.resume_claims == []
    assert result.warnings == ["NO_RESUME_TEXT"]


async def test_fewer_than_three_competencies_is_a_warning_not_a_failure() -> None:
    generator = FakePrepGenerator(
        draft_of([competency("성능 개선"), competency("협업")])
    )

    result = await PrepAgent(generator).run(make_context())

    assert result.status == "completed"
    assert result.warnings == ["FEWER_THAN_THREE_COMPETENCIES"]


class _RaisingGenerator:
    def __init__(self, error: PrepError) -> None:
        self.error = error

    async def generate(self, context: InterviewContext) -> PrepDraft:
        raise self.error


async def test_a_generator_failure_becomes_a_safe_error_code() -> None:
    generator = _RaisingGenerator(PrepError("LLM_RATE_LIMITED", retryable=True))

    result = await PrepAgent(generator).run(make_context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "LLM_RATE_LIMITED"
    assert result.error.retryable is True
    assert result.competencies == []


class _SlowGenerator:
    async def generate(self, context: InterviewContext) -> PrepDraft:
        await asyncio.sleep(5)
        return draft_of()


async def test_a_slow_generator_times_out() -> None:
    result = await PrepAgent(_SlowGenerator(), timeout_seconds=0.01).run(make_context())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "LLM_TIMEOUT"
    assert result.error.retryable is True


class _MeteredGenerator(FakePrepGenerator):
    def __init__(self, draft: PrepDraft) -> None:
        super().__init__(draft)
        self.last_usage = LlmUsage(prompt_tokens=900, completion_tokens=200)
        self.last_model = "gpt-5.6-luna-2026-02"


async def test_usage_and_the_served_model_are_reported() -> None:
    generator = _MeteredGenerator(draft_of(three_competencies()))

    result = await PrepAgent(generator, model="gpt-5.6-luna").run(make_context())

    assert result.model == "gpt-5.6-luna-2026-02"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 900


def test_the_fake_generator_satisfies_the_protocol() -> None:
    assert isinstance(FakePrepGenerator(draft_of()), PrepGenerator)


@pytest.mark.parametrize(
    "kwargs",
    [{"timeout_seconds": 0}, {"max_competencies": 0}, {"max_claims": 0}],
)
def test_agent_arguments_are_validated(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PrepAgent(FakePrepGenerator(draft_of()), **kwargs)


# --- the wire shape ----------------------------------------------------------------


async def test_result_serialises_to_the_agreed_camel_case_body() -> None:
    generator = FakePrepGenerator(draft_of(three_competencies(), [claim(CACHE_QUOTE)]))
    result = await PrepAgent(generator, model="stub").run(make_context())

    body = json.loads(result.model_dump_json(by_alias=True))

    # The two lists are the body of PUT /internal/v1/interviews/{id}/prep (#137).
    assert set(body["competencies"][0]) == {
        "competencyId",
        "jdId",
        "name",
        "required",
        "description",
    }
    assert set(body["resumeClaims"][0]) == {"claimId", "resumeId", "quote", "section"}
    assert body["status"] == "completed"
    assert body["sessionId"] == "ses_prep_01"
    assert "elapsedMs" in body


async def test_the_result_does_not_carry_the_resume_body() -> None:
    generator = FakePrepGenerator(draft_of(three_competencies(), [claim(CACHE_QUOTE)]))
    result = await PrepAgent(generator).run(make_context())

    dumped = result.model_dump_json(by_alias=True)

    # Only what was quoted leaves; the rest of the resume stays where it was.
    assert CACHE_QUOTE in dumped
    assert "PostgreSQL" not in dumped
    assert LOAD_QUOTE not in dumped
