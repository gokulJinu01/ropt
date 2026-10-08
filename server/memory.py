"""Bounded memory plus an adapter to the user's existing MME MCP server."""

import asyncio
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger("pet.memory")


def bounded(text, budget):
    # A UTF-8 byte ceiling is deliberately more conservative than a word count.
    return text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")


class Memory:
    def __init__(self, store, cfg, remote=None):
        self.store, self.cfg, self.remote = store, cfg, remote
        self.last_status = "off" if cfg.memory == "off" else "local"
        if cfg.memory == "mme" and remote is None:
            self.remote = MMEMemory(cfg.mme_config, cfg.mme_api_key.get_secret_value())

    async def inject(self, query):
        if self.cfg.memory == "off":
            return ""
        if self.remote:
            try:
                async with asyncio.timeout(self.cfg.memory_timeout_s):
                    text = await self.remote.inject(
                        self.cfg.pet_id, query, self.cfg.memory_token_budget
                    )
                self.last_status = "mme"
                return bounded(text, self.cfg.memory_token_budget)
            except Exception as exc:
                log.warning(
                    "MME recall unavailable (%s); using local journal",
                    type(exc).__name__,
                )
                self.last_status = "local_fallback"
        return self.store.recall(self.cfg.pet_id, query, self.cfg.memory_token_budget)

    async def save(self, user_text, reply):
        if self.cfg.memory == "off":
            return
        self.store.save(self.cfg.pet_id, user_text, reply)
        if self.remote:
            try:
                async with asyncio.timeout(self.cfg.memory_timeout_s):
                    await self.remote.save(self.cfg.pet_id, user_text, reply)
                if self.last_status != "local_fallback":
                    self.last_status = "mme"
            except Exception as exc:
                log.warning(
                    "MME save unavailable (%s); exchange saved locally only",
                    type(exc).__name__,
                )
                self.last_status = "local_fallback"


class MMEMemory:
    """Configured tool arguments are validated against the live MME schemas."""

    def __init__(self, path, api_key="", *, transport=None):
        self.config = json.loads(Path(path).read_text())
        self.api_key = api_key
        self.transport = transport
        if "REPLACE" in json.dumps(self.config).upper():
            raise ValueError(
                "Fill in mme-config.json using the actual MME tool schemas"
            )
        if not self.config.get("url", "").startswith(("http://", "https://")):
            raise ValueError("MME needs a Streamable HTTP MCP URL")
        for operation in ("inject", "save"):
            entry = self.config.get(operation, {})
            if not isinstance(entry.get("tool"), str) or not isinstance(
                entry.get("arguments"), dict
            ):
                raise ValueError(
                    f"MME {operation} requires a tool name and an arguments object"
                )

    @staticmethod
    def render(value, variables):
        if isinstance(value, dict):
            return {k: MMEMemory.render(v, variables) for k, v in value.items()}
        if isinstance(value, list):
            return [MMEMemory.render(v, variables) for v in value]
        if isinstance(value, str):
            if value in variables:
                return variables[value]
            for name, replacement in variables.items():
                value = value.replace(name, str(replacement))
        return value

    async def _call(self, operation, variables):
        from jsonschema import validate
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        config = self.config[operation]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(
            headers=headers, timeout=10, transport=self.transport
        ) as client:
            async with streamable_http_client(
                self.config["url"], http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    available = await session.list_tools()
                    tool = next(
                        (t for t in available.tools if t.name == config["tool"]), None
                    )
                    if tool is None:
                        raise ValueError("Configured MME tool not advertised by server")
                    arguments = self.render(config["arguments"], variables)
                    validate(arguments, tool.inputSchema)
                    result = await session.call_tool(config["tool"], arguments)
                    if result.isError:
                        raise RuntimeError("MME tool reported an error")
                    return "\n".join(
                        block.text for block in result.content if block.type == "text"
                    )

    async def inject(self, pet_id, query, budget):
        return await self._call(
            "inject",
            {"${pet_id}": pet_id, "${query}": query, "${token_budget}": budget},
        )

    async def save(self, pet_id, user_text, reply):
        await self._call(
            "save", {"${pet_id}": pet_id, "${user_text}": user_text, "${reply}": reply}
        )
