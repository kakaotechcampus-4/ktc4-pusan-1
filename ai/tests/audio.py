"""Synthetic PCM for the STT tests: something loud, and something silent.

16-bit mono at 16 kHz, the only format the STT layer accepts.
"""

import array
import math

RATE = 16000


def tone(duration_ms: int, *, amplitude: int = 8000, freq: float = 220.0) -> bytes:
    """Loud, voiced-looking audio."""

    count = RATE * duration_ms // 1000
    samples = array.array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * freq * i / RATE))
            for i in range(count)
        ),
    )
    return samples.tobytes()


def silence(duration_ms: int) -> bytes:
    return b"\x00\x00" * (RATE * duration_ms // 1000)
