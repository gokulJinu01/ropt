"""The seam.

The server never imports a provider directly — it calls these three interfaces.
Which implementation fills each slot is decided once, in server/config.py.
Going offline in v2 is a change to that file, not to anything below it.

Every interface is streaming-shaped on purpose. That is what makes it possible
for the next stage to start on the *first* output of the previous one rather
than the last, which is the whole latency argument.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class STT(Protocol):
    async def stream(self, frames: AsyncIterator[bytes]) -> str:
        """Consume 20 ms PCM frames as they are captured.

        Returns the final transcript once the frame iterator is exhausted.
        Implementations should do their work *during* the iteration so that
        almost nothing is left to do at the endpoint.
        """
        ...


@runtime_checkable
class LLM(Protocol):
    def stream(self, user_text: str, *, memory: str = "") -> AsyncIterator[str]:
        """Yield reply text incrementally, as it is generated.

        Implementations own their own conversation history — the provider is
        the only thing that knows what shape its history has to be replayed in.
        """
        ...

    def reset(self) -> None:
        """Forget the conversation."""
        ...


@runtime_checkable
class TTS(Protocol):
    def stream(self, sentences: AsyncIterator[str]) -> AsyncIterator[bytes]:
        """Consume whole sentences, yield 20 ms PCM frames as they are ready."""
        ...


@runtime_checkable
class VAD(Protocol):
    def reset(self) -> None: ...

    def is_endpoint(self, frame: bytes) -> bool:
        """True on the frame where the user is judged to have stopped talking."""
        ...
