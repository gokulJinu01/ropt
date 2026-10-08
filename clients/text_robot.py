"""Try the pet without a microphone or paid providers; replies appear as text."""

import argparse
import asyncio
import sys

import websockets

from protocol import messages


async def read_line(prompt):
    """Nonblocking terminal input; Ctrl-C can shut down without a stuck thread."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    print(prompt, end="", flush=True)

    def readable():
        if not future.done():
            future.set_result(sys.stdin.readline())

    loop.add_reader(sys.stdin.fileno(), readable)
    try:
        line = await future
        if not line:
            raise EOFError
        return line.rstrip("\n")
    finally:
        loop.remove_reader(sys.stdin.fileno())


async def turn(ws, text):
    await ws.send(messages.encode(messages.TextTurn(text=text)))
    reply = ""
    while True:
        raw = await asyncio.wait_for(ws.recv(), 70)
        if isinstance(raw, bytes):
            continue
        frame = messages.decode_server(raw)
        if isinstance(frame, messages.Act):
            print(f"  [pet: {frame.name}]")
        elif isinstance(frame, messages.Reply):
            reply = frame.text
            print(f"  {reply}  [memory: {frame.memory}]")
        elif isinstance(frame, messages.SayEnd):
            await ws.send(messages.encode(messages.Played()))
        elif isinstance(frame, messages.Cancel):
            print(f"  [try again: {frame.reason}]")
        elif isinstance(frame, messages.Status) and frame.phase == "idle":
            if frame.detail:
                print(f"  {frame.detail}")
            return reply


async def main(url, prompts):
    async with websockets.connect(url, max_size=1_000_000) as ws:
        await ws.send(messages.encode(messages.Hello(dev="laptop-text")))
        hello = messages.decode_server(await ws.recv())
        if not isinstance(hello, messages.Ready):
            raise RuntimeError("Server isn't ready. Run python -m clients.doctor")
        if prompts:
            for prompt in prompts:
                print("You:", prompt)
                await turn(ws, prompt)
        else:
            print(
                "Type to your pet. /quit ends the session. Default replies are scripted demos."
            )
            while True:
                try:
                    prompt = await read_line("You: ")
                except EOFError:
                    break
                if prompt.strip() == "/quit":
                    break
                if prompt.strip():
                    await turn(ws, prompt[:2000])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--say", action="append", default=[])
    args = parser.parse_args()
    try:
        asyncio.run(main(args.url, args.say))
    except (KeyboardInterrupt, OSError) as exc:
        print(
            "Disconnected."
            if isinstance(exc, KeyboardInterrupt)
            else "Can't reach the pet. Start python -m server.app first."
        )
