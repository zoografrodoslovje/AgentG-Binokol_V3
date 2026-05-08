from __future__ import annotations

import json
from pathlib import Path

from AGENT_Joko.memory.context import AgentContext, ContextManager
from AGENT_Joko.memory.json_store import JsonStore


def test_agent_context_round_trips_nested_messages() -> None:
    ctx = AgentContext(agent_name="architect", session_id="s1")
    ctx.add_message("user", "hello", {"source": "test"})
    payload = ctx.to_dict()

    loaded = AgentContext.from_dict(payload)

    assert loaded.agent_name == "architect"
    assert loaded.session_id == "s1"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].role == "user"
    assert loaded.messages[0].content == "hello"
    assert loaded.messages[0].metadata == {"source": "test"}


def test_context_manager_loads_saved_session(tmp_path: Path) -> None:
    store = JsonStore(storage_path=str(tmp_path / "memory"))
    manager = ContextManager(memory_store=store, context_window=5)

    saved = AgentContext(agent_name="architect", session_id="session42")
    saved.add_message("user", "Create Python scraper script")
    saved.add_message("assistant", "Plan ready", {"step": 1})

    session_file = tmp_path / "memory" / "sessions" / "architect_session42.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(saved.to_dict(), indent=2), encoding="utf-8")

    loaded = manager.get_or_create_context("architect", "session42")

    assert len(loaded.messages) == 2
    assert loaded.messages[0].content == "Create Python scraper script"
    assert loaded.messages[1].metadata == {"step": 1}


def test_context_manager_includes_pinned_memory_profiles(tmp_path: Path) -> None:
    store = JsonStore(storage_path=str(tmp_path / "memory"))
    store.add(
        content="[SCRAPER CSV DIRECTIVE] Always keep merged scraper CSV headers pinned.",
        entry_type="memory_profile",
        tags=["scraper", "csv"],
        importance=5,
    )
    store.add(
        content="recent note",
        entry_type="context",
        tags=["recent"],
        importance=2,
    )
    manager = ContextManager(memory_store=store, context_window=5)

    prompt = manager.build_system_prompt("coder", "session99")

    assert "Pinned memory:" in prompt
    assert "SCRAPER CSV DIRECTIVE" in prompt
    assert "Recent memory:" in prompt
