"""Speech-to-text: live audio to utterances.

- ``segmentation``: decides where to cut the stream, and refuses to spend a
  request on audio that holds no speech. Pure, deterministic, no network.
- ``elice``: the Elice prediction-service client, plus the guard that spots a
  transcription describing more audio than was sent.
- ``http_logging``: keeps the deployment host out of the records ``httpx`` and
  ``httpcore`` write about those requests. The client wires it up itself.
- ``session``: puts a session's several tracks on one timeline, which is what
  makes their utterance ``seq`` comparable across speakers.
- ``stream``: connects them and emits utterances in spoken order.
"""

from irya_ai.stt.elice import (
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    EliceSttClient,
    SttError,
    Transcription,
    build_client,
    build_http_client,
    is_hallucinated,
    parse_response,
)
from irya_ai.stt.http_logging import (
    REDACTED_HOST,
    clear_protected_hosts,
    protect_host,
    protected_hosts,
)
from irya_ai.stt.segmentation import (
    AudioSegment,
    CutReason,
    NoiseFloor,
    SegmentationConfig,
    StreamSegmenter,
    frame_rms,
)
from irya_ai.stt.session import (
    DEFAULT_CAPACITY,
    SessionOrdering,
    TrackOrdering,
    solo_ordering,
)
from irya_ai.stt.stream import (
    DEFAULT_MAX_PENDING,
    RejectedSegment,
    SegmentTiming,
    TranscriptionStream,
    silent_probe,
    wav_bytes,
)

__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_LANGUAGE",
    "DEFAULT_MAX_PENDING",
    "DEFAULT_MODEL",
    "REDACTED_HOST",
    "AudioSegment",
    "CutReason",
    "EliceSttClient",
    "NoiseFloor",
    "RejectedSegment",
    "SegmentTiming",
    "SegmentationConfig",
    "SessionOrdering",
    "SttError",
    "StreamSegmenter",
    "TrackOrdering",
    "Transcription",
    "TranscriptionStream",
    "build_client",
    "build_http_client",
    "clear_protected_hosts",
    "frame_rms",
    "is_hallucinated",
    "parse_response",
    "protect_host",
    "protected_hosts",
    "silent_probe",
    "solo_ordering",
    "wav_bytes",
]
