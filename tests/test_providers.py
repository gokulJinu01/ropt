import asyncio
import json

import httpx
import pytest

from protocol import audio
from server.pipeline.stt_deepgram import DeepgramSTT
from server.pipeline.tts_cartesia import CartesiaTTS


async def items(*values):
    for value in values:
        yield value


async def test_cartesia_request_auth_and_pcm_reframing():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(
            200, content=b"a" * 650, headers={"content-type": "audio/pcm"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tts = CartesiaTTS("test-key", "voice-id", client=client)
    try:
        frames = [frame async for frame in tts.stream(items("Hello.", "Hi."))]
        assert all(len(frame) == audio.FRAME_BYTES for frame in frames)
        assert b"".join(frames) == b"a" * 1300 + b"\x00" * 620
        assert requests[0].headers["authorization"] == "Bearer test-key"
        assert requests[0].headers["cartesia-version"] == "2026-08-14"
        body = json.loads(requests[0].content)
        assert body["voice"] == "voice-id"
        assert body["output_format"] == {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 16000,
        }
        assert tts.characters == 9
    finally:
        await tts.close()


async def test_cartesia_http_failure_is_propagated():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    )
    tts = CartesiaTTS("test-key", "voice-id", client=client)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            _ = [frame async for frame in tts.stream(items("hello"))]
    finally:
        await tts.close()


async def test_deepgram_wire_protocol_and_final_transcripts(monkeypatch):
    sent, arguments = [], {}
    ended = asyncio.Event()

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, data):
            sent.append(data)
            if isinstance(data, str):
                ended.set()

        def __aiter__(self):
            return self.receive()

        async def receive(self):
            yield json.dumps(
                {
                    "type": "Results",
                    "is_final": False,
                    "channel": {"alternatives": [{"transcript": "wrong"}]},
                }
            )
            await ended.wait()
            yield json.dumps(
                {
                    "type": "Results",
                    "is_final": True,
                    "channel": {"alternatives": [{"transcript": "hello pet"}]},
                }
            )

    def connect(url, **kwargs):
        arguments.update(url=url, **kwargs)
        return Socket()

    monkeypatch.setattr("server.pipeline.stt_deepgram.connect", connect)
    result = await DeepgramSTT("test-key").stream(items(audio.silence(20)))
    assert result == "hello pet"
    assert sent[0] == audio.silence(20)
    assert json.loads(sent[-1]) == {"type": "CloseStream"}
    assert arguments["additional_headers"]["Authorization"] == "Token test-key"
    assert "sample_rate=16000" in arguments["url"]


async def test_claude_real_sdk_parses_stream_and_receives_memory():
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    from server.pipeline.llm_claude import ClaudeLLM

    requests = []
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "test-model",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "<act>wiggle</act>Hello Mira."},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 8},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    content = "".join(
        f"event: {kind}\ndata: {json.dumps(data)}\n\n" for kind, data in events
    )

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=content
        )

    sdk = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        base_url="https://test.invalid",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    llm = ClaudeLLM(api_key="test-key", model="test-model", client=sdk)
    try:
        reply = "".join(
            [part async for part in llm.stream("Hello", memory="Name: Mira")]
        )
        assert reply == "<act>wiggle</act>Hello Mira."
        assert "Name: Mira" in requests[0]["system"]
        assert requests[0]["messages"] == [{"role": "user", "content": "Hello"}]
        assert llm.usage["llm_input_tokens"] == 10
        assert llm.usage["llm_output_tokens"] == 8
        assert len(llm._history) == 2
    finally:
        await llm.close()
