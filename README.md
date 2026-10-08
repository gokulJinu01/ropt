# Robopet brain

A laptop brain for a small robot pet: hear an utterance, choose a gesture,
give a brief reply, remember the interaction, then settle into quiet idle
behavior. The laptop can be the microphone and speaker until the body is ready.

## Start on the laptop

From this folder:

    uv sync --all-extras
    uv run --all-extras python -m clients.laptop

The launcher starts its own server and stops it on exit. If the same pet is
already running on the configured port, it connects without stopping that server.

Default mode is a **scripted demo with tones and a local journal**, not real
speech recognition or an AI model. Type "My name is Mira", quit, restart,
and ask "What is my name?" to exercise persistence.

For microphone/speaker mode:

    uv run --all-extras python -m clients.laptop --voice

Press Enter to talk. The microphone stops forwarding audio while the pet
thinks and replies. Actions are printed, standing in for the future body.
There is no animated avatar.

## Your remaining setup

Read [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md). The project has a private
.gitignored .env file with safe defaults and clearly marked USER fields.
.env.example is the shareable template.

- API keys, model ID, voice ID and a chosen daily cloud allowance enable real voice.
- A separate MME connection template uses your existing MCP service and actual schemas.
- The doctor checks local setup without making a paid request:

      uv run --all-extras python -m clients.doctor

Real cloud conversation, microphone quality and recall from your deployed
MME still need live acceptance tests after setup. Passing local tests does not
prove those external services work.

## Implemented behavior

- Bounded 16 kHz, 16-bit mono PCM transport and explicit listening/thinking/idle signals.
- Short-speech detection, silence timeout, provider timeout and playback recovery.
- Structured, allowlisted gestures dispatched before response audio.
- At most two short response sentences by default.
- Quiet ambient gestures; a goodbye/sleep gesture pauses idle movement for five
  minutes, and the next interaction wakes the pet.
- Hourly limits plus daily cloud-attempt limits reserved before paid recognition.
  Limits persist across reconnects/restarts and share the configured pet identity.
- Persistent local memory; optional MME save/inject with bounded context and
  explicit local fallback during outages.
- Usage-unit accounting. Dollar billing must be capped at the provider.

The default data directory is .pet-data/. Changing PET_PET_ID changes the
memory/allowance identity. PET_MEMORY=off stops conversation text persistence.

## Test

    uv run --all-extras pytest -q
    uv run --all-extras ruff check .
    uv run --all-extras ruff format --check .

Tests use temporary storage and simulated services, including actual MCP
transport and Claude SDK parsing. They make no paid API requests.

Start the server separately when testing the audio transport:

    uv run --all-extras python -m server.app
    uv run --all-extras python -m clients.turn_check

For exact echo verification, restart the server with PET_MODE=echo and run
clients.echo_check. Both check clients accept --url.

## Provider boundaries

- Recognition: Deepgram's streaming WebSocket protocol, avoiding the old SDK import
  mismatch. [Protocol](https://developers.deepgram.com/reference/speech-to-text/listen-streaming)
- Responses: Anthropic SDK with an explicitly selected model and endpoint.
  No assumed model ID, and no inherited proxy address or shell-wide
  `ANTHROPIC_API_KEY` (the pet reads `PET_ANTHROPIC_API_KEY`).
- Speech: Cartesia streaming PCM, using its documented 2026-08-14 API shape.
  [API](https://docs.cartesia.ai/api-reference/tts/bytes)
- Memory: Streamable HTTP MCP tools; argument mappings are validated against
  schemas advertised by the user's actual MME service.

Cloud model availability, account access and voice selection are external
dependencies. No cloud or MME credentials are bundled.

## Layout

    protocol/       shared audio/control contract, including laptop text turns
    server/
      app.py        local FastAPI server, health and usage
      session.py    bounded conversation lifecycle and recovery
      config.py     validated .env settings and secret handling
      storage.py    SQLite journal, request reservations, usage
      memory.py     local memory and optional MME MCP adapter
      behavior/     pet personality, gestures, quiet idle loop
      pipeline/     simulated and cloud STT/LLM/TTS implementations
    clients/
      laptop.py     one-command launcher
      text_robot.py typed laptop interaction, no audio hardware needed
      fake_robot.py microphone/speaker body
      doctor.py     local setup validation
      state.py      testable half-duplex client controls
    tests/          protocol, lifecycle, providers, memory, application tests

The first physical version still uses the laptop as its brain over Wi-Fi.
ESP32 firmware, servo motion, wake words, offline AI and an untethered brain
are separate work. Keep provider secrets on the laptop/server.
