import asyncio

import pytest

from protocol import audio
from server.config import Settings
from server.pipeline.llm_scripted import ScriptedLLM
from server.pipeline.stt_echo import EchoSTT
from server.pipeline.vad import EnergyVAD
from server.session import Session, State
from server.storage import Store
from tests.test_session import FakeWS, loud, quiet


class FastTTS:
    characters = 0

    async def stream(self, sentences):
        self.characters = 0
        async for sentence in sentences:
            self.characters += len(sentence)
            yield audio.silence(20)


def build(cfg=None, store=None, llm=None, stt=None, tts=None, memory=None):
    cfg = cfg or Settings(_env_file=None)
    ws = FakeWS()
    session = Session(
        ws,
        stt=stt or EchoSTT(),
        llm=llm or ScriptedLLM(0),
        tts=tts or FastTTS(),
        vad=EnergyVAD(cfg.speech_rms, cfg.hangover_ms, cfg.min_speech_ms),
        cfg=cfg,
        store=store,
        memory=memory,
    )
    return session, ws


async def wait_idle(s):
    async with asyncio.timeout(1):
        while s.state is not State.IDLE:
            await asyncio.sleep(0.005)


async def text_turn(s, text="hello"):
    await s.on_text(text)
    if s._turn_task:
        await asyncio.wait_for(s._turn_task, 2)
    await s.on_played()


async def test_short_200ms_utterance_endpoints():
    s, ws = build()
    try:
        await s.on_utt_start()
        for _ in range(10):
            await s.on_frame(loud())
        for _ in range(36):
            await s.on_frame(quiet())
        assert s.state is State.THINKING
        await s._turn_task
        assert s.state is State.SPEAKING
        await s.on_played()
        assert s.state is State.IDLE
    finally:
        await s.close()


async def test_silence_timeout_releases_client():
    s, ws = build(Settings(_env_file=None, listening_timeout_s=0.02))
    try:
        await s.on_utt_start()
        await wait_idle(s)
        assert "cancel" in ws.types()
        await text_turn(s)
        assert "reply" in ws.types()
    finally:
        await s.close()


async def test_budget_refuses_before_stt():
    class STT:
        calls = 0

        async def stream(self, frames):
            self.calls += 1
            return "hello"

    stt = STT()
    s, ws = build(Settings(_env_file=None, max_turns_per_hour=0), stt=stt)
    try:
        await s.on_utt_start()
        await asyncio.sleep(0)
        assert stt.calls == 0
        assert s.state is State.IDLE
        assert any(v.get("reason") == "budget_limit" for k, v in ws.sent if k == "text")
    finally:
        await s.close()


async def test_allowance_survives_reconnect_and_restart(tmp_path):
    path = tmp_path / "pet.sqlite3"
    cfg = Settings(_env_file=None, max_turns_per_hour=1)
    store = Store(path)
    s, _ = build(cfg, store=store)
    await text_turn(s)
    await s.close()
    store.close()
    store = Store(path)
    s, ws = build(cfg, store=store)
    try:
        await s.on_utt_start()
        assert s._stt_task is None
        assert "cancel" in ws.types()
    finally:
        await s.close()
        store.close()


async def test_invalid_audio_recovers():
    s, ws = build()
    try:
        await s.on_utt_start()
        await s.on_frame(b"x")
        assert s.state is State.IDLE
        assert "cancel" in ws.types()
        await text_turn(s)
        assert "reply" in ws.types()
    finally:
        await s.close()


async def test_llm_failure_cleans_tasks_and_next_turn_works():
    class Broken:
        async def stream(self, text, *, memory=""):
            raise RuntimeError("synthetic failure")
            yield ""

    s, ws = build(llm=Broken())
    try:
        await text_turn(s)
        assert s.state is State.IDLE
        assert s._speak_task.done()
        s._llm = ScriptedLLM(0)
        await text_turn(s)
        assert "reply" in ws.types()
    finally:
        await s.close()


async def test_stt_failure_during_listening_recovers():
    class Broken:
        async def stream(self, frames):
            raise RuntimeError("synthetic STT failure")

    s, ws = build(stt=Broken())
    try:
        await s.on_utt_start()
        await wait_idle(s)
        assert "cancel" in ws.types()
        await text_turn(s)
        assert "reply" in ws.types()
    finally:
        await s.close()


async def test_tts_failure_cancels_slow_llm():
    stopped = asyncio.Event()

    class Slow:
        async def stream(self, text, *, memory=""):
            try:
                yield "<act>wiggle</act>Hello. "
                await asyncio.sleep(30)
            finally:
                stopped.set()

    class Broken:
        async def stream(self, sentences):
            async for _ in sentences:
                raise RuntimeError("synthetic TTS failure")
            yield b""

    s, ws = build(llm=Slow(), tts=Broken())
    try:
        await text_turn(s)
        assert stopped.is_set()
        assert s.state is State.IDLE
        assert "cancel" in ws.types()
    finally:
        await s.close()


async def test_provider_timeout_and_missing_playback_ack():
    class Slow:
        async def stream(self, text, *, memory=""):
            await asyncio.sleep(30)
            yield ""

    cfg = Settings(_env_file=None, turn_timeout_s=0.02, played_timeout_s=0.02)
    s, ws = build(cfg, llm=Slow())
    try:
        await text_turn(s)
        assert s.state is State.IDLE
        s._llm = ScriptedLLM(0)
        await s.on_text("hello")
        await s._turn_task
        assert s.state is State.SPEAKING
        await wait_idle(s)
        reasons = [v.get("reason") for k, v in ws.sent if k == "text"]
        assert "provider_timeout" in reasons
        assert "playback_timeout" in reasons
    finally:
        await s.close()


async def test_disconnect_cancels_every_background_task():
    s, _ = build()
    await s.on_utt_start()
    tasks = [s._stt_task, s._listen_timer]
    await s.close()
    assert all(t.done() for t in tasks)


async def test_idle_snoozes_after_goodbye_and_wakes_on_interaction():
    from protocol import messages

    cfg = Settings(_env_file=None, idle_low_s=0.01, idle_high_s=0.01)
    s, ws = build(cfg)
    try:
        await s.on_hello(messages.Hello(dev="idle-test"))
        await s.send_action("sleep")
        before = len(ws.sent)
        await asyncio.sleep(0.035)
        assert len(ws.sent) == before
        await text_turn(s, "hello")
        before = len(ws.sent)
        await asyncio.sleep(0.035)
        assert len(ws.sent) > before
    finally:
        await s.close()


async def test_idle_socket_failure_does_not_break_cleanup():
    from protocol import messages

    cfg = Settings(_env_file=None, idle_low_s=0.005, idle_high_s=0.005)
    s, ws = build(cfg)
    await s.on_hello(messages.Hello(dev="idle-test"))

    async def broken(_):
        raise RuntimeError("closed socket")

    ws.send_text = broken
    await asyncio.sleep(0.015)
    await s.close()
    assert s._closed


@pytest.mark.parametrize(
    "reply", ["Hello. Second. Third.", "<act>bad_action</act>Hello. Second. Third."]
)
async def test_reply_and_action_are_bounded(reply):
    class LLM:
        async def stream(self, text, *, memory=""):
            yield reply

    s, ws = build(llm=LLM())
    try:
        await text_turn(s)
        result = [v for k, v in ws.sent if k == "text" and v["t"] == "reply"][0]
        assert result["text"] == "Hello. Second."
        assert ws.types().index("act") < ws.types().index("audio")
    finally:
        await s.close()


async def test_remembers_name_after_restart(tmp_path):
    cfg = Settings(_env_file=None)
    path = tmp_path / "memory.sqlite3"
    store = Store(path)
    s, _ = build(cfg, store=store)
    await text_turn(s, "My name is Mira")
    await s.close()
    store.close()
    store = Store(path)
    s, ws = build(cfg, store=store)
    try:
        await text_turn(s, "What is my name?")
        replies = [v["text"] for k, v in ws.sent if k == "text" and v["t"] == "reply"]
        assert "Mira" in replies[-1]
    finally:
        await s.close()
        store.close()


async def test_speech_cap_still_collects_final_provider_usage():
    class LLM:
        usage = {}

        async def stream(self, text, *, memory=""):
            yield "<act>wiggle</act>One. Two. "
            yield "Three."
            self.usage = {"llm_output_tokens": 12}

    s, ws = build(llm=LLM())
    try:
        await text_turn(s)
        replies = [v["text"] for k, v in ws.sent if k == "text" and v["t"] == "reply"]
        assert replies == ["One. Two."]
        assert s.store.summary(s._cfg.pet_id)["units"]["llm_output_tokens"] == 12
    finally:
        await s.close()
