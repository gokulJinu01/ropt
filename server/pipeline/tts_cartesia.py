"""Cartesia streaming PCM over HTTP, re-framed to the robot audio protocol."""

import httpx

from protocol import audio


class CartesiaTTS:
    def __init__(self, api_key, voice_id, model="sonic-3.6", *, client=None):
        self._client = client or httpx.AsyncClient(timeout=20)
        self.api_key, self.voice_id, self.model = api_key, voice_id, model
        self.characters = 0

    async def stream(self, sentences):
        self.characters = 0
        tail = b""
        async for sentence in sentences:
            self.characters += len(sentence)
            async with self._client.stream(
                "POST",
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Cartesia-Version": "2026-08-14",
                },
                json={
                    "model_id": self.model,
                    "transcript": sentence,
                    "voice": self.voice_id,
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": audio.RATE,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    tail += chunk
                    whole = len(tail) - len(tail) % audio.FRAME_BYTES
                    for frame in audio.frames(tail[:whole]):
                        yield frame
                    tail = tail[whole:]
        if tail:
            yield tail + b"\x00" * (audio.FRAME_BYTES - len(tail))

    async def close(self):
        await self._client.aclose()
