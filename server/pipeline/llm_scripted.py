"""Deterministic pet demo, explicitly not an AI model."""

import asyncio
import re


class ScriptedLLM:
    def __init__(self, token_delay_s=0.02, name="Pip"):
        self.token_delay_s = token_delay_s
        self.name = name
        self.usage = {}

    def reset(self):
        self.usage = {}

    async def stream(self, user_text, *, memory=""):
        text = user_text.casefold()
        if "my name is" in text:
            name = re.search(r"my name is\s+([^\n.!?]{1,60})", user_text, re.I)
            reply = f"<act>wiggle</act>Hello, {name.group(1).strip() if name else 'friend'}! I'm {self.name}."
        elif "my name" in text:
            saved = re.search(r"Human: .*?my name is\s+([^\n.!?]{1,60})", memory, re.I)
            reply = (
                f"<act>wiggle</act>Your name is {saved.group(1).strip()}!"
                if saved
                else "<act>tilt</act>I don't know your name yet."
            )
        elif any(word in text for word in ("good robot", "good pet", "well done")):
            reply = "<act>bounce</act>You made my little robot day!"
        elif any(word in text for word in ("bye", "going to work", "goodnight")):
            reply = "<act>sleep</act>See you soon. I'll be right here."
        elif text.startswith(("hi", "hello", "hey")):
            reply = f"<act>wiggle</act>Hi! I'm {self.name}, your little desk buddy."
        else:
            reply = "<act>look_up</act>I'm practicing with demo replies for now. Real voice and AI come after setup."
        for i in range(0, len(reply), 4):
            await asyncio.sleep(self.token_delay_s)
            yield reply[i : i + 4]
