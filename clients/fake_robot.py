"""Laptop microphone/speaker body for the pet. Press Enter to talk."""

import argparse
import asyncio
import sys

import websockets

from clients.state import ClientState
from protocol import audio, messages


async def main(url, dev, input_device=None, output_device=None):
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    state = ClientState()
    mic = asyncio.Queue(maxsize=100)
    playback = asyncio.Queue(maxsize=1500)
    quit_event = asyncio.Event()
    pending_sends = set()

    def enqueue_mic(data, generation):
        if state.recording and generation == state.generation and not mic.full():
            mic.put_nowait((generation, data))

    def on_mic(indata, _frames, _time, status):
        if status:
            print(f"  microphone: {status}", file=sys.stderr)
        if state.recording:
            loop.call_soon_threadsafe(enqueue_mic, bytes(indata), state.generation)

    async with websockets.connect(url, max_size=1_000_000) as ws:
        await ws.send(messages.encode(messages.Hello(dev=dev)))
        hello = messages.decode_server(await ws.recv())
        if not isinstance(hello, messages.Ready):
            raise RuntimeError("Server isn't ready. Run python -m clients.doctor")
        state.accept(hello)

        with (
            sd.RawInputStream(
                samplerate=audio.RATE,
                channels=1,
                dtype="int16",
                blocksize=audio.FRAME_SAMPLES,
                callback=on_mic,
                device=input_device,
            ),
            sd.RawOutputStream(
                samplerate=audio.RATE,
                channels=1,
                dtype="int16",
                blocksize=audio.FRAME_SAMPLES,
                device=output_device,
            ) as speaker,
        ):

            def on_enter():
                line = sys.stdin.readline()
                if line == "" or line.strip() == "/quit":
                    quit_event.set()
                    return
                if state.begin():
                    task = asyncio.create_task(
                        ws.send(messages.encode(messages.UttStart()))
                    )
                    pending_sends.add(task)
                    task.add_done_callback(pending_sends.discard)
                else:
                    print("  One moment — I'm still listening or replying.")

            async def uplink():
                while True:
                    generation, data = await mic.get()
                    if state.recording and generation == state.generation:
                        await ws.send(data)

            async def play():
                while True:
                    generation, data = await playback.get()
                    if generation != state.generation:
                        continue
                    if data == "cancel":
                        await asyncio.to_thread(speaker.abort)
                        await asyncio.to_thread(speaker.start)
                    elif data is None:
                        # Drain the hardware buffer before acknowledging playback.
                        await asyncio.to_thread(speaker.stop)
                        await asyncio.to_thread(speaker.start)
                        if generation == state.generation:
                            await ws.send(messages.encode(messages.Played()))
                    else:
                        await asyncio.to_thread(speaker.write, data)

            async def downlink():
                async for raw in ws:
                    if isinstance(raw, bytes):
                        await playback.put((state.generation, raw))
                        continue
                    frame = messages.decode_server(raw)
                    state.accept(frame)
                    if not state.recording:
                        while not mic.empty():
                            mic.get_nowait()
                    if isinstance(frame, messages.Heard):
                        print(f"  You said: {frame.text}")
                    elif isinstance(frame, messages.Act):
                        print(f"  [pet: {frame.name}]")
                    elif isinstance(frame, messages.Reply):
                        print(f"  {frame.text}")
                    elif isinstance(frame, messages.Status):
                        if frame.detail:
                            print(" ", frame.detail)
                        elif frame.phase == "listening":
                            print("  Listening…")
                        elif frame.phase == "idle":
                            print("  Press Enter to talk; /quit exits.")
                    elif isinstance(frame, messages.SayEnd):
                        await playback.put((state.generation, None))
                    elif isinstance(frame, messages.Cancel):
                        while not playback.empty():
                            playback.get_nowait()
                        await playback.put((state.generation, "cancel"))
                        print(f"  [{frame.reason}]")

            print("Connected. Press Enter to talk; /quit exits.")
            loop.add_reader(sys.stdin.fileno(), on_enter)
            tasks = [
                asyncio.create_task(coro)
                for coro in (uplink(), play(), downlink(), quit_event.wait())
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                loop.remove_reader(sys.stdin.fileno())
                for task in tasks + list(pending_sends):
                    task.cancel()
                await asyncio.gather(*tasks, *pending_sends, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--dev", default="laptop-mic")
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--devices", action="store_true")
    args = parser.parse_args()
    try:
        if args.devices:
            import sounddevice as sd

            print(sd.query_devices())
        else:
            asyncio.run(main(args.url, args.dev, args.input_device, args.output_device))
    except KeyboardInterrupt:
        print("\nBye!")
    except ImportError:
        print("Install microphone support first: uv sync --extra client")
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"Audio session stopped ({type(exc).__name__}). Check microphone permission and run python -m clients.doctor."
        )
        raise SystemExit(1)
