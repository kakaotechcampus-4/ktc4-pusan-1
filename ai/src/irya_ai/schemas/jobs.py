"""What Backend hands the poller: one analysis job to do (#137, #162).

``GET /internal/v1/jobs/pending`` answers with the oldest job still waiting,
or ``null`` when there is none. The poller does the job and puts the result
back with the same ``requestedAt`` it was given, which is how Backend tells a
result for the current request from one for a request that was replaced in
the meantime (a resume re-uploaded while the model was still reading the old
one): a mismatch is a 409 and the result is thrown away.

``requested_at`` is kept as the string Backend sent, not parsed into a
datetime. Backend compares the two instants exactly, down to the microsecond,
and the surest way to send back the same instant is to send back the same
characters.
"""

from pydantic import ConfigDict, Field

from irya_ai.schemas.base import CamelModel

JOB_KIND_PREP = "PREP"
JOB_KIND_REVIEW = "REVIEW"


class PendingJob(CamelModel):
    """One row of Backend's work queue.

    Unknown keys are ignored rather than refused: this is Backend's object,
    and a field it adds later must not stop the poller from reading the ones
    it needs.
    """

    model_config = ConfigDict(extra="ignore")

    kind: str = Field(examples=[JOB_KIND_PREP, JOB_KIND_REVIEW])
    session_id: str = Field(examples=["ses_123"])
    interview_id: str = Field(examples=["int_123"])
    requested_at: str = Field(examples=["2026-10-06T00:00:00.123456Z"])

    @property
    def key(self) -> tuple[str, str]:
        """What makes a job distinct: the interview and the request it is for."""

        return (self.interview_id, self.requested_at)
