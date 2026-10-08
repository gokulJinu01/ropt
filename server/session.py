"""One bounded, half-duplex conversation at a time, with explicit recovery."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import aclosing
from enum import Enum, auto

from protocol import audio, messages
from server.behavior import actions
from server.behavior.idle import IdleLoop
from server.memory import Memory
from server.metrics import TurnMetrics
from server.storage import Store

log = logging.getLogger("pet.session")
_ACT = re.compile(r"<act>\s*(\w+)\s*</act>")
_SENT_END = re.compile(r"[.!?]+[\"')\]]*(?:\s|$)")


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()


async def _drain(q):
    while (item := await q.get()) is not None:
        yield item


def _sentence_end(buf):
    match = _SENT_END.search(buf)
    return match.end() if match else None


class Session:
    def __init__(self, ws, *, stt, llm, tts, vad, cfg, store=None, memory=None):
        self._ws, self._stt, self._llm, self._tts = ws, stt, llm, tts
        self._vad, self._cfg = vad, cfg
        self._owns_store = store is None
        self.store = store or Store()
        self.memory = memory or Memory(self.store, cfg)
        self.dev = "unknown"
        self.state = State.IDLE
        self.metrics = TurnMetrics()
        self.idle = IdleLoop(self, cfg.idle_low_s, cfg.idle_high_s)
        self._frames = None
        self._stt_task = self._turn_task = self._watchdog = self._listen_timer = None
        self._speak_task = self._llm_task = None
        self._turn_id = None
        self._input_bytes = 0
        self._usage = {}
        self._closed = False
        self._playback_ready = False

    async def send(self, frame):
        await self._ws.send_text(messages.encode(frame))

    async def status(self, phase, detail=""):
        await self.send(messages.Status(phase=phase, detail=detail))

    async def send_action(self, name):
        if actions.is_valid(name):
            if name == "sleep":
                self.idle.snooze(self._cfg.goodbye_quiet_s)
            await self.send(messages.Act(name=name, dur_ms=actions.duration_ms(name)))

    async def dispatch(self, frame):
        match frame:
            case messages.Hello():
                await self.on_hello(frame)
            case messages.UttStart():
                await self.on_utt_start()
            case messages.UttEnd():
                await self.on_utt_end()
            case messages.Played():
                await self.on_played()
            case messages.TextTurn():
                await self.on_text(frame.text)

    async def on_hello(self, frame):
        self.dev = frame.dev
        await self.send(messages.Ready())
        if self._cfg.mode == "pet":
            self.idle.start()

    def _allow_turn(self):
        self._turn_id = self.store.reserve(
            self._cfg.pet_id,
            self._cfg.max_turns_per_hour,
            self._cfg.max_cloud_turns_per_day,
            self._cfg.uses_cloud,
        )
        return self._turn_id is not None

    async def _begin(self):
        if self._closed or self.state is not State.IDLE:
            return False
        if not self._allow_turn():
            await self.send_action("sleep")
            await self.send(messages.Cancel(reason="budget_limit"))
            await self.status("idle", "Rest time: the request allowance is used up.")
            return False
        self._input_bytes = 0
        self._usage = {}
        self._playback_ready = False
        self.idle.wake()
        if hasattr(self._llm, "usage"):
            self._llm.usage = {}
        if hasattr(self._tts, "characters"):
            self._tts.characters = 0
        return True

    async def on_utt_start(self):
        if not await self._begin():
            return
        self.state = State.LISTENING
        self._vad.reset()
        if self._cfg.mode == "echo":
            await self.send(messages.SayStart())
        else:
            self._frames = asyncio.Queue(maxsize=200)
            self._stt_task = asyncio.create_task(self._transcribe(), name="stt")
            self._stt_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
            await self.status("listening")
        self._listen_timer = asyncio.create_task(
            self._listening_watchdog(), name="listen-timeout"
        )

    async def _transcribe(self):
        try:
            return await self._stt.stream(_drain(self._frames))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("STT failed (%s)", type(exc).__name__)
            if self.state is State.LISTENING:
                await self._abort(
                    "provider_error", "My ears lost the connection. Try again."
                )
            raise

    async def on_frame(self, pcm):
        if self.state is not State.LISTENING:
            return
        if len(pcm) != audio.FRAME_BYTES:
            await self._abort(
                "invalid_audio", "Audio format mismatch. Please reconnect."
            )
            return
        self._input_bytes += len(pcm)
        if (
            self._input_bytes
            > self._cfg.listening_timeout_s * audio.RATE * audio.SAMPLE_WIDTH
        ):
            await self._endpoint()
            return
        if self._cfg.mode == "echo":
            await self._ws.send_bytes(pcm)
            return
        try:
            self._frames.put_nowait(pcm)
        except asyncio.QueueFull:
            await self._abort("audio_overflow", "Audio arrived too quickly. Try again.")
            return
        if self._vad.is_endpoint(pcm):
            await self._endpoint()

    async def on_utt_end(self):
        await self._endpoint()

    async def on_text(self, text):
        if self._cfg.mode != "pet" or not text.strip() or not await self._begin():
            return
        self.state = State.THINKING
        self.metrics.start()
        await self.status("thinking")
        self._turn_task = asyncio.create_task(self._run_turn(text.strip()), name="turn")

    async def _listening_watchdog(self):
        await asyncio.sleep(self._cfg.listening_timeout_s)
        if self.state is State.LISTENING:
            if self._input_bytes and self._vad.has_speech:
                await self._endpoint()
            else:
                await self._abort(
                    "no_speech", "I didn't hear anything. Press Enter to try again."
                )

    async def _endpoint(self):
        if self.state is not State.LISTENING:
            return
        if self._listen_timer and self._listen_timer is not asyncio.current_task():
            self._listen_timer.cancel()
        if self._cfg.mode == "echo":
            await self.send(messages.SayEnd())
            await self._finish("complete")
            return
        self.state = State.THINKING
        self.metrics.start()
        await self.status("thinking")
        try:
            async with asyncio.timeout(2):
                await self._frames.put(None)
        except TimeoutError:
            await self._abort("provider_timeout", "My ears got stuck. Try again.")
            return
        self._turn_task = asyncio.create_task(self._run_turn(), name="turn")

    async def _produce(self, transcript, context, sentences, reply):
        pending, acted = "", False
        chars = 0

        async def emit(chunk):
            nonlocal chars
            chunk = re.sub(r"<[^>]*>|<[^>]*$", "", chunk).strip()
            chunk = re.sub(r"[*#_\x60]", "", chunk)
            remaining = self._cfg.max_reply_chars - chars
            if len(chunk) > remaining:
                chunk = chunk[:remaining].rsplit(" ", 1)[0].rstrip(" ,") + "."
                chunk = chunk[:remaining]
            if chunk:
                self.metrics.mark("first_sentence")
                reply.append(chunk)
                chars += len(chunk)
                await sentences.put(chunk)

        async with aclosing(self._llm.stream(transcript, memory=context)) as stream:
            async for delta in stream:
                # Still consume the provider's bounded response to receive final
                # usage counts; never synthesize beyond the pet's speech limit.
                if (
                    len(reply) >= self._cfg.max_reply_sentences
                    or chars >= self._cfg.max_reply_chars
                ):
                    continue
                self.metrics.mark("first_token")
                pending += delta
                if not acted:
                    match = _ACT.search(pending)
                    if match:
                        name = match.group(1)
                        await self.send_action(
                            name if actions.is_valid(name) else "tilt"
                        )
                        pending = pending[match.end() :]
                    elif len(pending) >= 60:
                        await self.send_action("look_up")
                    else:
                        continue
                    acted = True
                    self.metrics.mark("action")
                while (cut := _sentence_end(pending)) is not None:
                    await emit(pending[:cut])
                    pending = pending[cut:]
                    if (
                        len(reply) >= self._cfg.max_reply_sentences
                        or chars >= self._cfg.max_reply_chars
                    ):
                        pending = ""
                        break
        if not acted and pending.strip():
            await self.send_action("look_up")
            self.metrics.mark("action")
        while (
            pending.strip()
            and len(reply) < self._cfg.max_reply_sentences
            and chars < self._cfg.max_reply_chars
        ):
            cut = _sentence_end(pending)
            if cut is None:
                break
            await emit(pending[:cut])
            pending = pending[cut:]
        if (
            pending.strip()
            and len(reply) < self._cfg.max_reply_sentences
            and chars < self._cfg.max_reply_chars
        ):
            await emit(pending)
        await sentences.put(None)

    async def _run_turn(self, text=None):
        try:
            async with asyncio.timeout(self._cfg.turn_timeout_s):
                transcript = text if text is not None else await self._stt_task
                self.metrics.mark("transcript")
                if not transcript.strip():
                    await self._abort("no_speech", "I didn't catch that. Try again.")
                    return
                context = await self.memory.inject(transcript)
                sentences = asyncio.Queue(maxsize=4)
                reply = []
                async with asyncio.TaskGroup() as group:
                    self._llm_task = group.create_task(
                        self._produce(transcript, context, sentences, reply),
                        name="pet-llm",
                    )
                    self._speak_task = group.create_task(
                        self._speak(_drain(sentences)), name="pet-speak"
                    )
                if reply:
                    if text is not None or self._cfg.stt != "echo":
                        await self.memory.save(transcript, " ".join(reply))
                    await self.send(
                        messages.Reply(
                            text=" ".join(reply), memory=self.memory.last_status
                        )
                    )
                if self._speak_task.result():
                    self._playback_ready = True
                    self._watchdog = asyncio.create_task(
                        self._played_watchdog(), name="playback-timeout"
                    )
                    await self.send(messages.SayEnd())
                else:
                    await self._abort("empty_reply", "I lost my words. Try again.")
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._abort(
                "provider_timeout", "That took too long. Let's try again."
            )
        except Exception as exc:
            log.warning("Turn failed (%s)", type(exc).__name__)
            await self._abort("provider_error", "I lost the connection. Try again.")

    async def _speak(self, sentences):
        started = False
        async for pcm in self._tts.stream(sentences):
            if not started:
                started = True
                self.state = State.SPEAKING
                await self.send(messages.SayStart())
                self.metrics.mark("first_audio")
            if len(pcm) != audio.FRAME_BYTES:
                raise ValueError("TTS returned an invalid audio frame")
            self._usage["audio_out_seconds"] = (
                self._usage.get("audio_out_seconds", 0) + audio.FRAME_MS / 1000
            )
            await self._ws.send_bytes(pcm)
        return started

    async def on_played(self):
        if self.state is not State.SPEAKING or not self._playback_ready:
            return
        if self._turn_task and not self._turn_task.done():
            await self._turn_task
        if self._watchdog:
            self._watchdog.cancel()
        await self._finish("complete")

    async def _played_watchdog(self):
        await asyncio.sleep(self._cfg.played_timeout_s)
        await self._abort("playback_timeout", "Playback timed out. Ready to try again.")

    async def _finish(self, status, detail=""):
        self._usage["audio_in_seconds"] = self._input_bytes / (
            audio.RATE * audio.SAMPLE_WIDTH
        )
        self._usage.update(getattr(self._llm, "usage", {}))
        self._usage["tts_characters"] = getattr(self._tts, "characters", 0)
        self.store.finish(self._turn_id, status, self._usage)
        self._turn_id = None
        self.metrics.mark("done")
        self.metrics.log()
        self.state = State.IDLE
        self._playback_ready = False
        await self.status("idle", detail)

    async def _cancel_tasks(self):
        tasks = {
            t
            for t in (
                self._turn_task,
                self._stt_task,
                self._watchdog,
                self._listen_timer,
                self._speak_task,
                self._llm_task,
            )
            if t is not None and t is not asyncio.current_task()
        }
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _abort(self, reason, detail):
        await self._cancel_tasks()
        await self.send(messages.Cancel(reason=reason))
        await self._finish(reason, detail)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        await self.idle.stop()
        await self._cancel_tasks()
        if self._turn_id is not None:
            self._usage["audio_in_seconds"] = self._input_bytes / (
                audio.RATE * audio.SAMPLE_WIDTH
            )
            self.store.finish(self._turn_id, "disconnected", self._usage)
        for provider in (self._stt, self._llm, self._tts):
            if close := getattr(provider, "close", None):
                await close()
        if self._owns_store:
            self.store.close()
