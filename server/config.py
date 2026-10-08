"""Validated configuration. Credentials are passed explicitly to providers."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PET_", env_file=ROOT / ".env", extra="ignore", populate_by_name=True
    )
    mode: Literal["pet", "echo"] = "pet"
    stt: Literal["echo", "deepgram"] = "echo"
    llm: Literal["scripted", "claude"] = "scripted"
    tts: Literal["beep", "cartesia"] = "beep"
    vad: Literal["energy"] = "energy"
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    pet_id: str = Field("my-pet", min_length=1, max_length=100)
    name: str = Field("Pip", min_length=1, max_length=60)
    personality: str = "warm, curious, a little goofy"
    language: str = "English"
    data_dir: Path = ROOT / ".pet-data"
    anthropic_api_key: SecretStr = Field(
        SecretStr(""), validation_alias="ANTHROPIC_API_KEY"
    )
    deepgram_api_key: SecretStr = Field(
        SecretStr(""), validation_alias="DEEPGRAM_API_KEY"
    )
    cartesia_api_key: SecretStr = Field(
        SecretStr(""), validation_alias="CARTESIA_API_KEY"
    )
    anthropic_base_url: str = "https://api.anthropic.com"
    claude_model: str = ""
    deepgram_model: str = "nova-2"
    stt_language: str = "en-US"
    cartesia_model: str = "sonic-3.6"
    cartesia_voice_id: str = ""
    llm_max_tokens: int = Field(200, ge=32, le=500)
    max_reply_chars: int = Field(400, ge=40, le=1000)
    max_reply_sentences: int = Field(2, ge=1, le=3)
    max_turns_per_hour: int = Field(120, ge=0)
    max_cloud_turns_per_day: int = Field(0, ge=0)
    speech_rms: float = Field(500, gt=0)
    hangover_ms: int = Field(700, ge=100, le=2000)
    min_speech_ms: int = Field(100, ge=20, le=1000)
    listening_timeout_s: float = Field(15, gt=0, le=60)
    turn_timeout_s: float = Field(30, gt=0, le=120)
    played_timeout_s: float = Field(30, gt=0, le=120)
    idle_low_s: float = Field(20, gt=0)
    idle_high_s: float = Field(60, gt=0)
    goodbye_quiet_s: float = Field(300, ge=0)
    memory: Literal["local", "mme", "off"] = "local"
    memory_token_budget: int = Field(400, ge=32, le=2000)
    memory_timeout_s: float = Field(5, gt=0, le=30)
    mme_config: Path = ROOT / "mme-config.json"
    mme_api_key: SecretStr = Field(SecretStr(""), validation_alias="MME_API_KEY")

    @model_validator(mode="after")
    def validate_idle_range(self):
        if self.idle_high_s < self.idle_low_s:
            raise ValueError("PET_IDLE_HIGH_S must be >= PET_IDLE_LOW_S")
        return self

    @property
    def uses_cloud(self):
        return self.mode == "pet" and (
            self.stt != "echo" or self.llm != "scripted" or self.tts != "beep"
        )

    def setup_issues(self):
        issues = []
        if self.mode == "echo":
            return issues
        for selected, value, label in [
            (
                self.stt == "deepgram",
                self.deepgram_api_key.get_secret_value(),
                "DEEPGRAM_API_KEY",
            ),
            (
                self.llm == "claude",
                self.anthropic_api_key.get_secret_value(),
                "ANTHROPIC_API_KEY",
            ),
            (
                self.tts == "cartesia",
                self.cartesia_api_key.get_secret_value(),
                "CARTESIA_API_KEY",
            ),
            (self.llm == "claude", self.claude_model, "PET_CLAUDE_MODEL"),
            (self.tts == "cartesia", self.cartesia_voice_id, "PET_CARTESIA_VOICE_ID"),
        ]:
            if selected and (not value.strip() or "REPLACE" in value.upper()):
                issues.append(f"Fill in {label}")
        if self.uses_cloud and self.max_cloud_turns_per_day == 0:
            issues.append(
                "Set PET_MAX_CLOUD_TURNS_PER_DAY to your chosen daily allowance"
            )
        if self.memory == "mme":
            from server.memory import MMEMemory

            try:
                MMEMemory(self.mme_config, self.mme_api_key.get_secret_value())
            except (OSError, ValueError, KeyError, TypeError):
                issues.append(
                    "Complete mme-config.json using your MME URL and actual tool schemas"
                )
        return issues


@lru_cache
def settings():
    return Settings()


def make_vad(s):
    from server.pipeline.vad import EnergyVAD

    return EnergyVAD(s.speech_rms, s.hangover_ms, s.min_speech_ms)


def make_stt(s):
    if s.stt == "echo":
        from server.pipeline.stt_echo import EchoSTT

        return EchoSTT()
    from server.pipeline.stt_deepgram import DeepgramSTT

    return DeepgramSTT(
        s.deepgram_api_key.get_secret_value(), s.deepgram_model, s.stt_language
    )


def make_llm(s):
    if s.llm == "scripted":
        from server.pipeline.llm_scripted import ScriptedLLM

        return ScriptedLLM(name=s.name)
    from server.behavior.personality import system_prompt
    from server.pipeline.llm_claude import ClaudeLLM

    return ClaudeLLM(
        api_key=s.anthropic_api_key.get_secret_value(),
        model=s.claude_model,
        base_url=s.anthropic_base_url,
        max_tokens=s.llm_max_tokens,
        system=system_prompt(s.name, s.personality, s.language),
    )


def make_tts(s):
    if s.tts == "beep":
        from server.pipeline.tts_beep import BeepTTS

        return BeepTTS()
    from server.pipeline.tts_cartesia import CartesiaTTS

    return CartesiaTTS(
        s.cartesia_api_key.get_secret_value(), s.cartesia_voice_id, s.cartesia_model
    )
