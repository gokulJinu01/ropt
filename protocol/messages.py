"""The wire contract, shared by the server and every client.

WebSocket frames are already typed, so the split is simply:
    text frame   -> a JSON control message defined here
    binary frame -> one 20 ms PCM audio frame (see protocol.audio)

That removes the need for any framing header of our own.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from protocol import audio

# --------------------------------------------------------------------------
# robot -> server
# --------------------------------------------------------------------------


class Hello(BaseModel):
    t: Literal["hello"] = "hello"
    dev: str = Field(min_length=1, max_length=100)
    fw: str = "0.1"


class UttStart(BaseModel):
    """Button pressed / tap / wake word. Audio frames follow."""

    t: Literal["utt_start"] = "utt_start"


class UttEnd(BaseModel):
    """Button released. Optional — server-side VAD is the real endpoint."""

    t: Literal["utt_end"] = "utt_end"


class TextTurn(BaseModel):
    """Laptop-only typed input; uses the same brain and memory as voice."""

    t: Literal["text_turn"] = "text_turn"
    text: str = Field(min_length=1, max_length=2000)


class Played(BaseModel):
    """Playback buffer drained. Drives SPEAKING -> IDLE."""

    t: Literal["played"] = "played"


ClientFrame = Annotated[
    Union[Hello, UttStart, UttEnd, Played, TextTurn],
    Field(discriminator="t"),
]


# --------------------------------------------------------------------------
# server -> robot
# --------------------------------------------------------------------------


class Ready(BaseModel):
    t: Literal["ready"] = "ready"
    fmt: str = audio.FORMAT
    frame_bytes: int = audio.FRAME_BYTES


class Act(BaseModel):
    """Run a canned motion. Fires independently of, and usually before, audio."""

    t: Literal["act"] = "act"
    name: str
    dur_ms: int = 0


class SayStart(BaseModel):
    t: Literal["say_start"] = "say_start"
    fmt: str = audio.FORMAT


class SayEnd(BaseModel):
    t: Literal["say_end"] = "say_end"


class Cancel(BaseModel):
    """Drop the playback buffer immediately. Barge-in and error recovery."""

    t: Literal["cancel"] = "cancel"
    reason: str = "cancelled"


class Status(BaseModel):
    t: Literal["status"] = "status"
    phase: Literal["idle", "listening", "thinking", "speaking"]
    detail: str = ""


class Heard(BaseModel):
    """What speech recognition understood, so mishearing is visible."""

    t: Literal["heard"] = "heard"
    text: str


class Reply(BaseModel):
    t: Literal["reply"] = "reply"
    text: str
    memory: str = "off"


ServerFrame = Annotated[
    Union[Ready, Act, SayStart, SayEnd, Cancel, Status, Heard, Reply],
    Field(discriminator="t"),
]


_CLIENT = TypeAdapter(ClientFrame)
_SERVER = TypeAdapter(ServerFrame)


def encode(frame: BaseModel) -> str:
    return frame.model_dump_json()


def decode_client(raw: str | bytes) -> ClientFrame:
    return _CLIENT.validate_json(raw)


def decode_server(raw: str | bytes) -> ServerFrame:
    return _SERVER.validate_json(raw)
