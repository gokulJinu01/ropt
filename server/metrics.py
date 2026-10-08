"""Per-turn latency, logged from the very first run.

This is the number the whole architecture exists to protect, so it is measured
by default rather than behind a flag. t = 0 is the endpoint: the moment VAD
decides the user stopped talking.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("pet.turn")

# Printed in this order, when present.
_MARKS = (
    "transcript",
    "first_token",
    "action",
    "first_sentence",
    "first_audio",
    "done",
)


class TurnMetrics:
    def __init__(self) -> None:
        self._t0: float | None = None
        self.marks: dict[str, float] = {}

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self.marks.clear()

    def mark(self, name: str) -> None:
        if self._t0 is None or name in self.marks:
            return  # first occurrence only; that is the interesting one
        self.marks[name] = (time.perf_counter() - self._t0) * 1000

    @property
    def first_audio_ms(self) -> float | None:
        return self.marks.get("first_audio")

    def report(self) -> str:
        return "  ".join(
            f"{k}={self.marks[k]:.0f}ms" for k in _MARKS if k in self.marks
        )

    def log(self) -> None:
        if self.marks:
            log.info("turn  %s", self.report())
