"""Half-duplex controls kept independent of microphone hardware for testing."""

from protocol import messages


class ClientState:
    def __init__(self):
        self.phase = "connecting"
        self.generation = 0

    @property
    def recording(self):
        return self.phase == "listening"

    def begin(self):
        if self.phase != "idle":
            return False
        self.generation += 1
        self.phase = "starting"
        return True

    def accept(self, frame):
        if isinstance(frame, messages.Ready):
            self.phase = "idle"
        elif isinstance(frame, messages.Status):
            self.phase = frame.phase
        elif isinstance(frame, messages.SayStart):
            self.phase = "speaking"
        elif isinstance(frame, messages.Cancel):
            self.generation += 1
            self.phase = "recovering"
