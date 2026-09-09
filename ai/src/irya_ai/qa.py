"""Deterministic turn grouping for backend transcript snapshots."""

from pydantic import BaseModel

from irya_ai.transcript import Speaker, Transcript, Utterance


class QAPair(BaseModel):
    qa_id: str
    question: str
    answer: str
    question_utterance_ids: list[str]
    answer_utterance_ids: list[str]
    started_at_ms: int
    ended_at_ms: int


def group_qa(transcript: Transcript) -> tuple[list[QAPair], list[str]]:
    """Group interviewer turns followed by candidate turns.

    Consecutive fragments by the same speaker stay together. This baseline
    does not distinguish an interviewer acknowledgement from a new question.
    Leading candidate speech is returned explicitly instead of discarded.
    """
    pairs: list[QAPair] = []
    unpaired: list[str] = []
    questions: list[Utterance] = []
    answers: list[Utterance] = []

    def flush() -> None:
        if not questions:
            return
        pairs.append(
            QAPair(
                qa_id=f"qa-{questions[0].utterance_id}",
                question="\n".join(u.text for u in questions),
                answer="\n".join(u.text for u in answers),
                question_utterance_ids=[u.utterance_id for u in questions],
                answer_utterance_ids=[u.utterance_id for u in answers],
                started_at_ms=questions[0].started_at_ms,
                ended_at_ms=max(u.ended_at_ms for u in questions + answers),
            )
        )

    for utterance in transcript.final_utterances():
        if utterance.speaker == Speaker.INTERVIEWER:
            if answers:
                flush()
                questions, answers = [], []
            questions.append(utterance)
        elif questions:
            answers.append(utterance)
        else:
            unpaired.append(utterance.utterance_id)
    flush()
    return pairs, unpaired
