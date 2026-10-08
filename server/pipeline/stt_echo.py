"""Stub STT: counts what it heard instead of transcribing it.

Exists so the whole loop runs end to end with no API keys on day one, and so
tests can drive a turn deterministically. Swap PET_STT=deepgram when you want
real words.
"""

from __future__ import annotations

from typing import AsyncIterator

from protocol import audio


class EchoSTT:
    async def stream(self, frames: AsyncIterator[bytes]) -> str:
        n = 0
        async for frame in frames:
            n += len(frame)
        secs = n / (audio.RATE * audio.SAMPLE_WIDTH)
        return f"[{secs:.1f}s of speech]"
