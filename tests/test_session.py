"""Pins the two invariants that matter: the state machine, and that motion is
dispatched before any audio is sent."""

from __future__ import annotations

import json

import numpy as np

from protocol import audio
from server.config import Settings
from server.pipeline.llm_scripted import ScriptedLLM
from server.pipeline.stt_echo import EchoSTT
from server.pipeline.tts_beep import BeepTTS
from server.pipeline.vad import EnergyVAD
from server.session import Session, State


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(("text", json.loads(text)))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", len(data)))

    def types(self) -> list[str]:
        return [v["t"] if k == "text" else "audio" for k, v in self.sent]


def loud() -> bytes:
    t = np.arange(audio.FRAME_SAMPLES, dtype=np.float32) / audio.RATE
    return (0.5 * 32767 * np.sin(2 * np.pi * 300 * t)).astype(np.int16).tobytes()


def quiet() -> bytes:
    return b"\x00" * audio.FRAME_BYTES


def build() -> tuple[Session, FakeWS]:
    cfg = Settings(mode="pet", stt="echo", llm="scripted", tts="beep", vad="energy")
    ws = FakeWS()
    session = Session(
        ws,
        stt=EchoSTT(),
        llm=ScriptedLLM(token_delay_s=0.0),
        tts=BeepTTS(),
        vad=EnergyVAD(speech_rms=cfg.speech_rms, hangover_ms=cfg.hangover_ms),
        cfg=cfg,
    )
    return session, ws


async def run_one_turn(session: Session) -> None:
    await session.on_utt_start()
    assert session.state is State.LISTENING

    for _ in range(40):  # 800 ms of speech
        await session.on_frame(loud())
    for _ in range(40):  # silence past the 700 ms hangover
        if session.state is not State.LISTENING:
            break
        await session.on_frame(quiet())

    assert session._turn_task is not None
    await session._turn_task


async def test_turn_reaches_speaking_then_idle_on_played():
    session, ws = build()
    try:
        await run_one_turn(session)
        assert session.state is State.SPEAKING
        await session.on_played()
        assert session.state is State.IDLE
    finally:
        await session.close()


async def test_motion_is_dispatched_before_any_audio():
    session, ws = build()
    try:
        await run_one_turn(session)
        kinds = ws.types()
        assert "act" in kinds, kinds
        assert "audio" in kinds, kinds
        assert kinds.index("act") < kinds.index("say_start") < kinds.index("audio")
        assert session.metrics.marks["action"] < session.metrics.marks["first_audio"]
    finally:
        await session.close()


async def test_unknown_action_is_dropped_not_raised():
    session, ws = build()
    try:
        await session.send_action("moonwalk")
        assert ws.sent == []
    finally:
        await session.close()


async def test_budget_guard_refuses_past_the_cap():
    session, _ = build()
    session._cfg = Settings(max_turns_per_hour=2)
    try:
        assert session._allow_turn() is True
        assert session._allow_turn() is True
        assert session._allow_turn() is False
    finally:
        await session.close()


async def test_utt_start_ignored_while_speaking():
    session, ws = build()
    try:
        await run_one_turn(session)
        assert session.state is State.SPEAKING
        before = len(ws.sent)
        await session.on_utt_start()
        assert session.state is State.SPEAKING
        assert len(ws.sent) == before
    finally:
        await session.close()


async def test_vad_endpoints_after_hangover():
    vad = EnergyVAD(speech_rms=500.0, hangover_ms=700, min_speech_ms=300)
    for _ in range(20):
        assert vad.is_endpoint(loud()) is False
    fired = [vad.is_endpoint(quiet()) for _ in range(40)]
    assert any(fired)
    assert fired.index(True) >= 700 // audio.FRAME_MS - 1
