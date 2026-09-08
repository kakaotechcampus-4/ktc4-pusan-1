"""Pre-interview context: company, job description, rubric, candidate, resume.

Mirrors the "면접 전 데이터" entities in the TechSpec data model. These are the
inputs the analysis agent grounds its findings against.
"""

from typing import Any

from pydantic import Field

from irya_ai.schemas.base import CamelModel


class Company(CamelModel):
    company_id: str = Field(examples=["cmp_001"])
    name: str
    culture: str | None = None


class JobDescription(CamelModel):
    jd_id: str = Field(examples=["jd_001"])
    company_id: str
    title: str = Field(examples=["백엔드 신입"])
    description: str


class Competency(CamelModel):
    """A skill or trait the job requires; findings are mapped onto these."""

    competency_id: str = Field(examples=["cmp_traffic"])
    jd_id: str
    name: str = Field(examples=["대용량 트래픽"])
    required: bool = True
    description: str | None = None


class Rubric(CamelModel):
    """Evaluation levels for a job description, free-form per team."""

    rubric_id: str
    jd_id: str
    levels: dict[str, Any] = Field(default_factory=dict)


class Candidate(CamelModel):
    candidate_id: str = Field(examples=["cnd_2213"])
    name: str


class Resume(CamelModel):
    resume_id: str
    candidate_id: str
    storage_key: str | None = None


class ResumeClaim(CamelModel):
    """One verifiable statement extracted from the resume."""

    claim_id: str = Field(examples=["clm_001"])
    resume_id: str
    quote: str = Field(description="Verbatim text from the resume.")
    section: str | None = Field(default=None, examples=["경력", "프로젝트"])


class InterviewContext(CamelModel):
    """Everything the agent knows before the interview starts.

    This is the object that gets cached as the fixed prompt prefix
    (회사·JD·평가기준·지원서 고정) in the TechSpec architecture.
    """

    session_id: str = Field(examples=["ses_123"])
    company: Company
    job_description: JobDescription
    competencies: list[Competency] = Field(default_factory=list)
    rubric: Rubric | None = None
    candidate: Candidate
    resume: Resume | None = None
    resume_claims: list[ResumeClaim] = Field(default_factory=list)

    def competency_by_id(self, competency_id: str) -> Competency | None:
        return next(
            (c for c in self.competencies if c.competency_id == competency_id),
            None,
        )

    def claim_by_id(self, claim_id: str) -> ResumeClaim | None:
        return next((c for c in self.resume_claims if c.claim_id == claim_id), None)
