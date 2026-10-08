"""The motion vocabulary — one definition, three consumers.

The same dict generates the list injected into the system prompt, validates
whatever the model emits, and (from Phase 5) maps to servo keyframes. Keeping
it in one place is what stops the prompt and the firmware drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Motion:
    dur_ms: int
    hint: str  # goes into the prompt, so the model knows when to use it
    ambient: bool  # eligible for the idle loop


ACTIONS: dict[str, Motion] = {
    "wiggle": Motion(800, "happy, agreeing, recognising something", ambient=True),
    "bounce": Motion(900, "excited, enthusiastic", ambient=True),
    "look_up": Motion(600, "curious, thinking, asking a question", ambient=True),
    "tilt": Motion(700, "confused, did not understand", ambient=True),
    "spin": Motion(1400, "delighted, showing off", ambient=False),
    "shuffle": Motion(2000, "moving toward you", ambient=False),
    "sleep": Motion(1200, "tired, saying goodbye", ambient=False),
    "none": Motion(0, "no motion suits the reply", ambient=False),
}

AMBIENT = [name for name, m in ACTIONS.items() if m.ambient]


def is_valid(name: str) -> bool:
    return name in ACTIONS


def duration_ms(name: str) -> int:
    motion = ACTIONS.get(name)
    return motion.dur_ms if motion else 0


def vocabulary() -> str:
    """The action list as the prompt sees it."""
    return "\n".join(f"  {name} - {m.hint}" for name, m in ACTIONS.items())
