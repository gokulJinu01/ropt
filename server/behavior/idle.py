"""Ambient motion — what makes it feel alive when nobody is talking to it.

A background task per session. Costs nothing, and is most of the difference
between a speaker with legs and a pet.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from server.behavior import actions

log = logging.getLogger("pet.idle")


class IdleLoop:
    def __init__(self, session, low_s: int = 20, high_s: int = 60) -> None:
        self.session = session
        self.low_s = low_s
        self.high_s = high_s
        self._task: asyncio.Task | None = None
        self._quiet_until = 0.0

    def snooze(self, seconds: float) -> None:
        self._quiet_until = time.monotonic() + seconds

    def wake(self) -> None:
        self._quiet_until = 0.0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="idle-loop")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        from server.session import State

        while True:
            await asyncio.sleep(random.uniform(self.low_s, self.high_s))
            # Only fidget when genuinely idle — never interrupt a turn.
            if self.session.state is not State.IDLE:
                continue
            if time.monotonic() < self._quiet_until:
                continue
            name = random.choice(actions.AMBIENT)
            log.debug("idle fidget: %s", name)
            try:
                await self.session.send_action(name)
            except Exception as exc:
                log.info("Idle connection ended (%s)", type(exc).__name__)
                return
