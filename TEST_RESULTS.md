# Verification — September 23, 2026

## Passed

- **45 automated tests**, no failures or warnings.
- Static checks and formatting checks pass.
- Actual laptop launcher started and stopped the local server cleanly.
- Actual WebSocket conversations: greeting with a supplied test name, praise
  with a bounce action, goodbye with a sleep action.
- Full server restart: the pet recalled the saved test name from the persistent
  local journal. This used a deterministic scripted response, not a live model.
- Actual echo server: 50 audio frames sent, 50 returned, byte-for-byte identical.
- Actual synthetic audio turn: action arrived at approximately 112 ms and first
  tone audio at 522 ms. The response contained 208 valid 20 ms frames. These are
  demo timings, not real speech recognition/AI/synthesis latency claims.

## Automated coverage

The suite exercises protocol validation; motion-before-audio ordering; short
utterances; silent-input timeout; malformed audio; provider failure/timeout;
missing playback acknowledgements; disconnect cleanup; bounded replies;
collection of final provider usage despite a shorter spoken response; client
half-duplex state; idle behavior and goodbye quiet time; persistent and shared
request limits; local memory isolation, restart persistence and context bounds;
MME failure fallback; configuration and secret handling; application restart;
cloud adapter request formats, streaming data and errors.

The Claude adapter was tested with the installed Anthropic SDK and simulated
streaming HTTP responses. Deepgram and Cartesia were tested against simulated
wire/HTTP responses. The MME adapter was tested through the actual MCP SDK and
Streamable HTTP transport using an in-process test MCP service that advertised
and validated tool schemas.

## Still requires your setup and acceptance

- Real Deepgram/AI/Cartesia credentials, supported model and chosen voice.
- Available provider credits and your selected daily cloud-attempt allowance.
- Your actual MME endpoint, authentication and save/inject argument mappings.
- A real microphone/speaker conversation and subjective voice/personality tuning.
- Live service latency, billing accuracy and actual MME recall across days.
- Physical robot firmware, audio hardware and movement, when parts are ready.

No paid API requests or real MME writes were made during these implementation
tests. Test conversations used temporary storage outside the project's normal
memory directory. Test servers were stopped after use.

## Reproduce

```sh
cd /Users/goku/Projects/pet
uv sync --all-extras
uv run --all-extras pytest -q
uv run --all-extras ruff check .
uv run --all-extras ruff format --check .
uv run --all-extras python -m clients.doctor
uv run --all-extras python -m clients.laptop
```

See `SETUP_CHECKLIST.md` before enabling real voice. Local memory is a fallback
journal, not MME. Request limits are not provider dollar caps.
