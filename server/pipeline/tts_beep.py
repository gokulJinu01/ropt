"""Stub TTS: a short tone per sentence, at the real frame size and rate.

Not speech, but it is the right number of bytes arriving at roughly the right
time, which is what the playback path and the latency numbers actually care
about.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import numpy as np

from protocol import audio

_TTFB_S = 0.18  # stand-in for a real provider's time-to-first-byte
_MS_PER_CHAR = 55  # rough speaking rate


class BeepTTS:
    async def stream(self, sentences: AsyncIterator[str]) -> AsyncIterator[bytes]:
        self.characters = 0
        first = True
        async for sentence in sentences:
            self.characters += len(sentence)
            if first:
                await asyncio.sleep(_TTFB_S)
                first = False

            ms = max(300, len(sentence) * _MS_PER_CHAR)
            n = int(audio.RATE * ms / 1000)
            t = np.arange(n, dtype=np.float32) / audio.RATE
            # A wobbling tone reads as "something spoke" without pretending to be speech.
            wave = 0.18 * np.sin(2 * np.pi * (420 + 60 * np.sin(2 * np.pi * 3 * t)) * t)
            pcm = (wave * 32767).astype(np.int16).tobytes()

            for frame in audio.frames(pcm):
                yield frame
