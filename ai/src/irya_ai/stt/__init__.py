"""Speech-to-text: live audio to utterances.

- ``segmentation``: decides where to cut the stream, and refuses to spend a
  request on audio that holds no speech. Pure, deterministic, no network.
- ``elice``: the Elice prediction-service client, plus the guard that spots a
  transcription describing more audio than was sent.
- ``stream``: connects the two and emits utterances in spoken order.
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
from irya_ai.stt.segmentation import (
    AudioSegment,
    CutReason,
    NoiseFloor,
    SegmentationConfig,
    StreamSegmenter,
    frame_rms,
)
from irya_ai.stt.stream import (
    RejectedSegment,
    TranscriptionStream,
    silent_probe,
    wav_bytes,
)

__all__ = [
    "DEFAULT_LANGUAGE",
    "DEFAULT_MODEL",
    "AudioSegment",
    "CutReason",
    "EliceSttClient",
    "NoiseFloor",
    "RejectedSegment",
    "SegmentationConfig",
    "SttError",
    "StreamSegmenter",
    "Transcription",
    "TranscriptionStream",
    "build_client",
    "build_http_client",
    "frame_rms",
    "is_hallucinated",
    "parse_response",
    "silent_probe",
    "wav_bytes",
]
