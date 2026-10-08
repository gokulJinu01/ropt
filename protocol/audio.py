"""The audio format, in one place.

These constants are deliberately what an INMP441 I2S mic on an ESP32 produces:
16 kHz, 16-bit signed little-endian, mono. The fake robot is handicapped to
match so that transcription accuracy measured today survives contact with real
hardware.
"""

from __future__ import annotations

from typing import Iterator

RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH  # 640

FORMAT = "pcm_s16le_16k"


def duration_ms(pcm: bytes) -> float:
    """Wall-clock length of a PCM buffer."""
    return len(pcm) / (RATE * SAMPLE_WIDTH) * 1000


def frames(pcm: bytes) -> Iterator[bytes]:
    """Split a buffer into whole 20 ms frames, dropping any short tail."""
    for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
        yield pcm[i : i + FRAME_BYTES]


def silence(ms: int) -> bytes:
    return b"\x00" * int(RATE * SAMPLE_WIDTH * ms / 1000)
