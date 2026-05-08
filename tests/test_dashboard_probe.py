from __future__ import annotations

import asyncio
from pathlib import Path

from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.dashboard.api import create_app


def _make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


async def _call_app(app, method: str, path: str):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


def test_root_probe_with_foo_method_returns_no_content(tmp_path: Path) -> None:
    app = create_app(config=_make_config(tmp_path))
    messages = asyncio.run(_call_app(app, "FOO", "/"))

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")

    assert start["status"] == 204
    assert body["body"] == b""
