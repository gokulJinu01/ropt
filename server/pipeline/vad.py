"""Voice activity detection — the thing that decides t = 0.

EnergyVAD has no dependencies beyond numpy and is accurate enough for
close-talk desk audio, which is the only case this robot has. It is
deliberately the default so that steps 1 and 2 of the build order need
no model downloads.

When it starts mis-firing on a noisy room, swap in Silero behind the same
VAD protocol and change PET_VAD in .env. Nothing else moves.
"""

from __future__ import annotations

import numpy as np

from protocol import audio


class EnergyVAD:
    """RMS threshold with a hangover timer.

    speech_rms      frame loudness that counts as speech
    hangover_ms     silence needed after speech before we call the endpoint
    min_speech_ms   ignore utterances shorter than this (coughs, door bumps)
    """

    def __init__(
        self,
        speech_rms: float = 500.0,
        hangover_ms: int = 700,
        min_speech_ms: int = 300,
    ) -> None:
        self.speech_rms = speech_rms
        self.hangover_frames = hangover_ms // audio.FRAME_MS
        self.min_speech_frames = min_speech_ms // audio.FRAME_MS
        self.reset()

    def reset(self) -> None:
        self.has_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._triggered = False

    @staticmethod
    def rms(frame: bytes) -> float:
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples * samples)))

    def is_endpoint(self, frame: bytes) -> bool:
        loud = self.rms(frame) >= self.speech_rms

        if loud:
            self.has_speech = True
            self._speech_frames += 1
            self._silence_frames = 0
            if self._speech_frames >= self.min_speech_frames:
                self._triggered = True
            return False

        self._silence_frames += 1
        if self._triggered and self._silence_frames >= self.hangover_frames:
            self.reset()
            return True
        return False
