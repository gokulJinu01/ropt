"""Build-order step 1, headless: does the plumbing work?

Sends a generated tone through the server in PET_MODE=echo and checks the exact
bytes come back. Needs no microphone, no speakers and no API keys, so it is the
one check that can run anywhere.

    PET_MODE=echo uv run uvicorn server.app:app     # terminal 1
    uv run python -m clients.echo_check             # terminal 2
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import numpy as np
import websockets

from protocol import audio, messages

URL = "ws://127.0.0.1:8000/ws"
N_FRAMES = 50  # one second


def tone() -> bytes:
    t = np.arange(audio.RATE, dtype=np.float32) / audio.RATE
    wave = 0.3 * np.sin(2 * np.pi * 440 * t)
    return (wave * 32767).astype(np.int16).tobytes()


async def main(url: str = URL) -> int:
    sent = list(audio.frames(tone()))[:N_FRAMES]

    async with websockets.connect(url, max_size=1_000_000) as ws:
        await ws.send(messages.encode(messages.Hello(dev="echo-check")))
        assert isinstance(messages.decode_server(await ws.recv()), messages.Ready)

        await ws.send(messages.encode(messages.UttStart()))
        assert isinstance(messages.decode_server(await ws.recv()), messages.SayStart)

        for frame in sent:
            await ws.send(frame)

        got: list[bytes] = []
        while len(got) < len(sent):
            got.append(await asyncio.wait_for(ws.recv(), timeout=5))

        await ws.send(messages.encode(messages.UttEnd()))

    ok = got == sent
    print(f"frames out {len(sent)}  in {len(got)}  identical={ok}")
    if ok:
        print("\n  step 1 passes: the plumbing works.")
    else:
        print("\n  MISMATCH — the transport is mangling audio.", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL)
    raise SystemExit(asyncio.run(main(parser.parse_args().url)))
