import asyncio
import json

import pytest

from clients.state import ClientState
from protocol import messages
from server.config import Settings, make_stt, make_tts
from server.memory import Memory, MMEMemory
from server.storage import Store


def test_dotenv_credentials_are_passed_to_providers(tmp_path, monkeypatch):
    for key in ("DEEPGRAM_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "PET_STT=deepgram\nPET_TTS=cartesia\nDEEPGRAM_API_KEY=test-dg\nCARTESIA_API_KEY=test-car\nPET_CARTESIA_VOICE_ID=voice-id\nPET_MAX_CLOUD_TURNS_PER_DAY=5\n"
    )
    cfg = Settings(_env_file=env)
    assert cfg.setup_issues() == []
    assert make_stt(cfg).api_key == "test-dg"
    tts = make_tts(cfg)
    assert tts.api_key == "test-car"
    asyncio.run(tts.close())
    assert "test-dg" not in repr(cfg)
    assert "test-car" not in repr(cfg)


def test_unconfigured_cloud_has_actionable_placeholders():
    cfg = Settings(
        _env_file=None,
        stt="deepgram",
        llm="claude",
        tts="cartesia",
        anthropic_api_key="",
        deepgram_api_key="",
        cartesia_api_key="",
    )
    issues = " ".join(cfg.setup_issues())
    for name in (
        "ANTHROPIC_API_KEY",
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY",
        "PET_CLAUDE_MODEL",
        "PET_CARTESIA_VOICE_ID",
        "PET_MAX_CLOUD_TURNS_PER_DAY",
    ):
        assert name in issues


def test_persistent_allowance_atomic_and_expires(tmp_path):
    path = tmp_path / "limits.sqlite3"
    first, second = Store(path), Store(path)
    try:
        assert first.reserve("pet", 1, 2, True, now=100000)
        assert second.reserve("pet", 1, 2, True, now=100001) is None
        assert second.reserve("pet", 1, 2, True, now=104000)
        assert first.reserve("pet", 10, 2, True, now=108000) is None
    finally:
        first.close()
        second.close()


def test_memory_isolated_and_bounded():
    store = Store()
    try:
        store.save("a", "My name is Mira", "Hello Mira")
        store.save("b", "My name is Other", "Hi")
        assert "Mira" in store.recall("a", "name", 400)
        assert "Other" not in store.recall("a", "name", 400)
        assert len(store.recall("a", "name", 32).encode()) <= 32
    finally:
        store.close()


async def test_memory_failure_falls_back_and_saves_locally():
    class Broken:
        async def inject(self, *args):
            await asyncio.sleep(30)

        async def save(self, *args):
            raise OSError("unavailable")

    store = Store()
    cfg = Settings(_env_file=None, memory="mme", memory_timeout_s=0.01)
    memory = Memory(store, cfg, remote=Broken())
    try:
        await memory.save("My name is Mira", "Hi")
        assert "Mira" in await memory.inject("name")
        assert memory.last_status == "local_fallback"
    finally:
        store.close()


async def test_memory_off_stores_no_transcripts():
    store = Store()
    memory = Memory(store, Settings(_env_file=None, memory="off"))
    try:
        await memory.save("My name is Mira", "Hi")
        assert await memory.inject("name") == ""
        assert store.db.execute("SELECT count(*) FROM exchanges").fetchone()[0] == 0
    finally:
        store.close()


async def test_successful_save_does_not_hide_failed_recall():
    class Remote:
        async def inject(self, *args):
            raise OSError("offline")

        async def save(self, *args):
            return None

    store = Store()
    memory = Memory(store, Settings(_env_file=None), remote=Remote())
    try:
        await memory.inject("name")
        await memory.save("hello", "hi")
        assert memory.last_status == "local_fallback"
    finally:
        store.close()


def test_mme_placeholder_is_not_silently_treated_as_live(tmp_path):
    config = tmp_path / "mme.json"
    config.write_text(json.dumps({"url": "REPLACE_WITH_MME_URL"}))
    with pytest.raises(ValueError, match="Fill in"):
        MMEMemory(config)


def test_mme_templates_preserve_types_and_literal_user_text():
    result = MMEMemory.render(
        {"limit": "${token_budget}", "query": "${query}"},
        {"${token_budget}": 400, "${query}": 'name "${pet_id}"'},
    )
    assert result == {"limit": 400, "query": 'name "${pet_id}"'}


def test_client_half_duplex_and_error_recovery():
    state = ClientState()
    state.accept(messages.Ready())
    assert state.begin()
    assert not state.begin()
    assert not state.recording
    state.accept(messages.Status(phase="listening"))
    assert state.recording
    generation = state.generation
    state.accept(messages.Status(phase="thinking"))
    assert not state.recording
    state.accept(messages.SayStart())
    assert not state.begin()
    state.accept(messages.Cancel(reason="provider_error"))
    assert state.generation != generation
    assert not state.begin()
    state.accept(messages.Status(phase="idle"))
    assert state.begin()
