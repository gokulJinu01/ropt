import json

import httpx
import pytest

from server.memory import MMEMemory


async def test_real_mcp_transport_saves_and_recalls(tmp_path):
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP

    service = FastMCP("test-memory", stateless_http=True, json_response=True)
    saved, headers_seen = {}, []

    @service.tool()
    def mme_save(pet_id: str, content: str) -> str:
        saved[pet_id] = content
        return "saved"

    @service.tool()
    def mme_inject(pet_id: str, query: str, token_budget: int) -> str:
        return saved.get(pet_id, "")[:token_budget]

    class Capture(httpx.ASGITransport):
        async def handle_async_request(self, request):
            headers_seen.append(request.headers)
            return await super().handle_async_request(request)

    path = tmp_path / "mme.json"
    path.write_text(
        json.dumps(
            {
                "url": "http://localhost:8000/mcp",
                "inject": {
                    "tool": "mme_inject",
                    "arguments": {
                        "pet_id": "${pet_id}",
                        "query": "${query}",
                        "token_budget": "${token_budget}",
                    },
                },
                "save": {
                    "tool": "mme_save",
                    "arguments": {
                        "pet_id": "${pet_id}",
                        "content": "Human: ${user_text}\nPet: ${reply}",
                    },
                },
            }
        )
    )
    remote = MMEMemory(
        path, "test-token", transport=Capture(app=service.streamable_http_app())
    )
    async with service.session_manager.run():
        await remote.save("pip", "My name is Mira", "Hello")
        assert "Mira" in await remote.inject("pip", "name", 400)
        assert await remote.inject("another-pet", "name", 400) == ""
    assert any(h.get("Authorization") == "Bearer test-token" for h in headers_seen)


async def test_mcp_rejects_wrong_tool_argument_schema(tmp_path):
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP

    service = FastMCP("test-schema", stateless_http=True, json_response=True)
    called = []

    @service.tool()
    def mme_inject(required_field: str) -> str:
        called.append(True)
        return ""

    path = tmp_path / "bad-schema.json"
    path.write_text(
        json.dumps(
            {
                "url": "http://localhost:8000/mcp",
                "inject": {"tool": "mme_inject", "arguments": {"wrong": "value"}},
                "save": {"tool": "mme_save", "arguments": {}},
            }
        )
    )
    remote = MMEMemory(
        path, transport=httpx.ASGITransport(app=service.streamable_http_app())
    )
    async with service.session_manager.run():
        with pytest.raises(Exception):
            await remote.inject("pip", "name", 400)
    assert not called
