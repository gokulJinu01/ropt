"""Deepgram's documented streaming wire API; no SDK-version coupling."""

import asyncio
import json
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from protocol import audio


class DeepgramSTT:
    def __init__(
        self,
        api_key,
        model="nova-2",
        language="en-US",
        url="wss://api.deepgram.com/v1/listen",
    ):
        self.api_key, self.model, self.language, self.url = (
            api_key,
            model,
            language,
            url,
        )

    async def stream(self, frames):
        query = urlencode(
            dict(
                model=self.model,
                language=self.language,
                encoding="linear16",
                sample_rate=audio.RATE,
                channels=1,
                punctuate="true",
                interim_results="false",
                endpointing="false",
            )
        )
        parts = []
        async with connect(
            self.url + "?" + query,
            additional_headers={"Authorization": "Token " + self.api_key},
            open_timeout=10,
            close_timeout=2,
            max_size=1_000_000,
        ) as ws:

            async def send():
                async for pcm in frames:
                    await ws.send(pcm)
                await ws.send(json.dumps({"type": "CloseStream"}))

            async def receive():
                async for raw in ws:
                    event = json.loads(raw)
                    if event.get("type") == "Error":
                        raise RuntimeError("Deepgram reported an error")
                    if event.get("type") == "Results" and event.get("is_final"):
                        alternatives = event.get("channel", {}).get("alternatives", [])
                        if alternatives and alternatives[0].get("transcript"):
                            parts.append(alternatives[0]["transcript"])

            async with asyncio.TaskGroup() as group:
                group.create_task(send())
                group.create_task(receive())
        return " ".join(parts).strip()
