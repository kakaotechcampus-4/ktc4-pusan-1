import json
from pathlib import Path

from pydantic import TypeAdapter

from irya_ai.pipeline import ground_finding, ground_findings, locate_quote
from irya_ai.pipeline.grounding import normalize
from irya_ai.schemas import Finding, FindingType, SpeakerRole, Utterance, Word
from irya_ai.simulator import TranscriptSimulator, load_script

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def _utt(seq: int, content: str, words: list[Word] | None = None) -> Utterance:
    return Utterance(
        utterance_id=f"utt_{seq:03d}",
        session_id="ses_t",
        track_id="trk_candidate",
        speaker=SpeakerRole.CANDIDATE,
        seq=seq,
        start_ms=seq * 10_000,
        end_ms=seq * 10_000 + 5_000,
        content=content,
        words=words or [],
    )


def _finding(quote: str | None, cited: str | None, **overrides) -> Finding:
    base = {
        "finding_id": "fnd_t",
        "session_id": "ses_t",
        "type": FindingType.COMPETENCY_EVIDENCE,
        "evidence_quote": quote,
        "evidence_utterance_id": cited,
        "summary": "test",
    }
    return Finding(**{**base, **overrides})


UTTS = [
    _utt(0, "조회가 많은 상품 API 앞에 Redis를 뒀습니다."),
    _utt(1, "k6로 했습니다. 로컬 노트북에서 돌렸습니다."),
]


def test_normalize_collapses_whitespace_only() -> None:
    assert normalize("  Redis를   뒀습니다.\n") == "Redis를 뒀습니다."
    assert normalize("Redis를 뒀습니다") != normalize("Redis를 뒀습니다.")


def test_exact_quote_is_grounded_and_gets_timestamp() -> None:
    result = ground_finding(_finding("Redis를 뒀습니다.", "utt_000"), UTTS)

    assert result.ok
    assert result.finding.evidence_t_ms == 0  # no words -> utterance start


def test_whitespace_differences_are_tolerated() -> None:
    result = ground_finding(_finding("Redis를   뒀습니다.", "utt_000"), UTTS)
    assert result.ok


def test_paraphrase_is_rejected() -> None:
    result = ground_finding(_finding("Redis를 두었습니다.", "utt_000"), UTTS)

    assert not result.ok
    assert result.reason == "quote not found in cited utterance"
    assert result.found_in == ()


def test_quote_from_other_utterance_is_rejected_with_pointer() -> None:
    result = ground_finding(_finding("k6로 했습니다.", "utt_000"), UTTS)

    assert not result.ok
    assert result.reason == "quote found in a different utterance than cited"
    assert result.found_in == ("utt_001",)


def test_unknown_utterance_is_rejected() -> None:
    result = ground_finding(_finding("k6로 했습니다.", "utt_999"), UTTS)

    assert not result.ok
    assert "does not exist" in result.reason


def test_gap_finding_passes_without_evidence() -> None:
    gap = _finding(None, None, type=FindingType.GAP)
    result = ground_finding(gap, UTTS)
    assert result.ok


def test_timestamp_comes_from_words_when_present() -> None:
    words = [
        Word(seq=0, start_ms=100, end_ms=400, content="조회가"),
        Word(seq=1, start_ms=450, end_ms=700, content="많은"),
        Word(seq=2, start_ms=750, end_ms=1000, content="상품"),
        Word(seq=3, start_ms=1050, end_ms=1300, content="API"),
        Word(seq=4, start_ms=1350, end_ms=1600, content="앞에"),
        Word(seq=5, start_ms=1650, end_ms=2000, content="Redis를"),
        Word(seq=6, start_ms=2050, end_ms=2400, content="뒀습니다."),
    ]
    utts = [_utt(0, "조회가 많은 상품 API 앞에 Redis를 뒀습니다.", words)]

    result = ground_finding(_finding("Redis를 뒀습니다.", "utt_000"), utts)

    assert result.ok
    assert result.finding.evidence_t_ms == 1650


def test_locate_quote_reports_every_hit() -> None:
    utts = UTTS + [_utt(2, "네, k6로 했습니다.")]
    hits = locate_quote("k6로 했습니다.", utts)
    assert [h.utterance_id for h in hits] == ["utt_001", "utt_002"]
    assert locate_quote("   ", utts) == []


def test_sample_findings_split_into_kept_and_rejected() -> None:
    findings = TypeAdapter(list[Finding]).validate_json(
        (SAMPLES / "findings_backend_junior_01.json").read_text(encoding="utf-8")
    )
    script = load_script(SAMPLES / "transcript_backend_junior_01.json")
    finals = TranscriptSimulator(
        script, interim_chunks=0, synthesize_words=True
    ).finals()

    report = ground_findings(findings, finals)

    assert [f.finding_id for f in report.kept] == [
        "fnd_001",
        "fnd_002",
        "fnd_003",
        "fnd_006",
    ]
    rejected = {r.finding_id: r for r in report.rejected}
    assert rejected["fnd_004"].reason == "quote not found in cited utterance"
    assert rejected["fnd_005"].found_in == ("utt_011",)
    # Kept findings with quotes got a timestamp inside their utterance.
    for f in report.kept:
        if f.evidence_quote is not None:
            utt = next(u for u in finals if u.utterance_id == f.evidence_utterance_id)
            assert utt.start_ms <= f.evidence_t_ms <= utt.end_ms
    assert report.total == 6


def test_grounding_works_on_sentence_split_transcript() -> None:
    """A quote inside one sentence must still ground when turns are split."""
    findings = TypeAdapter(list[Finding]).validate_python(
        json.loads((SAMPLES / "findings_backend_junior_01.json").read_text("utf-8"))
    )
    script = load_script(SAMPLES / "transcript_backend_junior_01.json")
    finals = TranscriptSimulator(
        script, interim_chunks=0, split_sentences=True
    ).finals()
    # Cited ids differ after splitting, so re-point fnd_001 at the sentence
    # that actually holds its quote.
    fnd = next(f for f in findings if f.finding_id == "fnd_001")
    hit = locate_quote(fnd.evidence_quote or "", finals)[0]
    repointed = fnd.model_copy(update={"evidence_utterance_id": hit.utterance_id})

    assert ground_finding(repointed, finals).ok
