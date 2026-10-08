# Your setup checklist

The project starts in a no-cost demo mode. You can type to the pet immediately;
it has scripted pet responses and local memory. Microphone demo mode returns
tones, not real spoken answers. Your private keys are not needed for tests.

## 1. Try the laptop pet now

From `/Users/goku/Projects/pet`:

```sh
uv sync --all-extras
uv run --all-extras python -m clients.laptop
```

Type `My name is Mira`, then `What is my name?`. Quit with `/quit`, restart,
and ask again. Change the example name to yours. The built-in name response
is a scripted demonstration of persistent recall, not an AI benchmark.

## 2. Fill in .env for real voice

The `.env` file already exists with safe defaults and USER comments. Fill:

| Setting | You provide |
|---|---|
| `DEEPGRAM_API_KEY` | Speech recognition API key with available credits |
| `PET_ANTHROPIC_API_KEY` | API key for your chosen Claude/compatible account |
| `PET_CLAUDE_MODEL` | Exact model ID supported by that account |
| `PET_ANTHROPIC_BASE_URL` | Leave the direct Anthropic URL, or set your intentional compatible proxy URL |
| `CARTESIA_API_KEY` | Text-to-speech API key with available credits |
| `PET_CARTESIA_VOICE_ID` | The voice you choose in Cartesia |
| `PET_MAX_CLOUD_TURNS_PER_DAY` | Your daily allowance; zero blocks cloud operation |
| `PET_NAME`, `PET_PERSONALITY`, `PET_LANGUAGE` | Optional pet preferences |
| `PET_STT_LANGUAGE` | Recognition language, such as `en-US` |

Then switch these three selectors:

```dotenv
PET_STT=deepgram
PET_LLM=claude
PET_TTS=cartesia
```

Keep `PET_PET_ID` stable: that identifies this pet's memory and allowance.
Keep keys only in `.env` or your local environment; `.env` is ignored by git.
Shell environment variables override `.env`. The Claude key and endpoint use
pet-specific names (`PET_ANTHROPIC_API_KEY`, `PET_ANTHROPIC_BASE_URL`), so a
generic `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_BASE_URL`
exported for other tools is never inherited. `DEEPGRAM_API_KEY` and
`CARTESIA_API_KEY` exported in your shell would still take precedence.

Run the local setup check:

```sh
uv run --all-extras python -m clients.doctor
```

This validates local configuration only. It does not charge a provider or
prove that credentials, credits, models, or voice IDs are valid.

Request limits count attempts, including failed or silent ones, and persist
across reconnects/restarts. The daily boundary is midnight UTC. These are
request limits, not dollar caps: set monetary limits in each provider account.
`/usage` reports accumulated audio seconds, generated characters and the AI
token counts available from responses. Interrupted requests may have incomplete
usage reports; provider billing remains the authoritative source.

## 3. Try your actual microphone and speaker

```sh
uv run --all-extras python -m clients.laptop --voice
```

Allow microphone access in macOS when prompted. Press Enter to speak; wait for
the reply and the next prompt. `/quit` exits. The microphone stops forwarding
audio while the pet thinks or speaks. Headphones can help during early tuning.

To select devices explicitly:

```sh
uv run --all-extras python -m clients.fake_robot --devices
```

Start the server separately with `uv run --all-extras python -m server.app`, then
use `clients.fake_robot --input-device NUMBER --output-device NUMBER` if needed.

## 4. Connect your actual MME service

Until this is filled, `PET_MEMORY=local` uses a small persistent journal. It is
not MME. The cloud AI receives bounded context from this journal before replies.

The MME adapter supports an existing **Streamable HTTP MCP** endpoint and its
advertised tools. It does not modify or deploy MME infrastructure.

1. Open the prepared `mme-config.json` file (`mme-config.example.json` is the template backup).
2. Replace the URL with the actual MME MCP endpoint.
3. Replace each argument field with the names required by your MME tool schemas.
   Add/remove fields to match those schemas. The example is a template, not a
   claim about your deployed API. Tool names are configurable too.
4. Keep `${pet_id}`, `${query}`, `${token_budget}`, `${user_text}` and `${reply}`
   where their values belong. A value consisting solely of `${token_budget}`
   is passed as a number.
5. Set `MME_API_KEY` if your endpoint uses Bearer authentication.
6. Change `PET_MEMORY=local` to `PET_MEMORY=mme`, then run the doctor again.

You need to supply the endpoint and actual tool schemas. A REST-only service,
legacy SSE transport, stdio-only MCP server, or non-Bearer authentication needs
a matching adapter; do not guess a URL or paste an unrelated REST route here.

The adapter validates arguments against the live MCP schema. If MME becomes
unavailable during conversation, the pet uses its local journal and reports
`local_fallback`. Exchanges saved locally during an outage are **not automatically
uploaded later**. Replies are saved once generation and synthesis finish; playback
can still be interrupted afterward. Failures before that point are not saved.

Local data lives in `.pet-data/pet.sqlite3`. `PET_MEMORY=off` disables saving and
retrieving conversation text; usage counts continue. The memory budget is
conservatively bounded in UTF-8 bytes, so it stays small across languages.

## 5. Final checks for you

- [ ] Real speech: greet the pet and hear an appropriate short spoken reply.
- [ ] Personality: praise it, say goodbye, and confirm its reactions feel pet-like.
- [ ] Silence: press Enter without speaking; it should recover after 15 seconds.
- [ ] Memory: share your name, restart, and ask it again with actual AI enabled.
- [ ] MME: verify the exchange in your real MME service and recall it the next day.
- [ ] Budget: confirm account limits and the daily request allowance you chose.

The legs can still be absent. Physical movement is represented by action
messages on the laptop. No animated avatar, wake word, or offline AI is included.
