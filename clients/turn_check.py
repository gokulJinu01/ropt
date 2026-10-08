"""One full turn, headless: does the pipeline work, and how fast?

Pushes a synthetic "utterance" through the real WebSocket and reports what came
back and when. Needs no microphone and, with the stub pipeline, no API keys —
so it is the check to run after every change to the turn logic.

    uv run uvicorn server.app:app                   # terminal 1
    uv run python -m clients.turn_check             # terminal 2
"""

from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np
import websockets

from protocol import audio, messages

URL = "ws://127.0.0.1:8000/ws"


def loud() -> bytes:
    t = np.arange(audio.FRAME_SAMPLES, dtype=np.float32) / audio.RATE
    return (0.5 * 32767 * np.sin(2 * np.pi * 300 * t)).astype(np.int16).tobytes()


QUIET = b"\x00" * audio.FRAME_BYTES


async def main(url: str = URL) -> int:
    async with websockets.connect(url, max_size=1_000_000) as ws:
        await ws.send(messages.encode(messages.Hello(dev="turn-check")))
        assert isinstance(messages.decode_server(await ws.recv()), messages.Ready)
        await ws.send(messages.encode(messages.UttStart()))

        # 800 ms of "speech", then silence past the VAD hangover.
        for _ in range(40):
            await ws.send(loud())
        for _ in range(45):
            await ws.send(QUIET)
        endpoint = time.perf_counter()  # t = 0

        marks: dict[str, float] = {}
        audio_frames = 0

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            dt = (time.perf_counter() - endpoint) * 1000

            if isinstance(raw, bytes):
                assert len(raw) == audio.FRAME_BYTES
                audio_frames += 1
                marks.setdefault("first audio", dt)
                continue

            frame = messages.decode_server(raw)
            if isinstance(frame, messages.Cancel):
                raise RuntimeError(f"Turn cancelled: {frame.reason}")
            if isinstance(frame, messages.Act):
                marks.setdefault("action", dt)
                print(f"  [SERVO] {frame.name} ({frame.dur_ms} ms)")
            elif isinstance(frame, messages.SayEnd):
                marks["say_end"] = dt
                await ws.send(messages.encode(messages.Played()))
                break

        print()
        for k, v in marks.items():
            print(f"  {k:<12} {v:7.0f} ms")
        print(
            f"  {'audio':<12} {audio_frames:7d} frames "
            f"({audio_frames * audio.FRAME_MS / 1000:.1f}s of audio)"
        )

        ok = (
            audio_frames > 0
            and "action" in marks
            and marks["action"] < marks["first audio"]
        )
        print("\n  motion before speech:", "yes" if ok else "NO — check the tag parser")
        return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL)
    raise SystemExit(asyncio.run(main(parser.parse_args().url)))
