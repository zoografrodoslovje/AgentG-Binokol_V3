from __future__ import annotations

from pathlib import Path

from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.dashboard.api import DashboardState


def _make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


def test_chat_model_settings_include_primary_and_available_models(
    tmp_path: Path,
) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    state.ollama_client.list_models = lambda: [
        "ollama:model-a",
        "ollama:llama3.2:latest",
        "ollama:mistral:latest",
        "openrouter:openrouter/free",
    ]

    settings = state.get_chat_model_settings()

    assert settings["model"] == "ollama:llama3.2:latest"
    assert "ollama:llama3.2:latest" in settings["available_models"]
    assert "ollama:model-a" not in settings["available_models"]
    assert "ollama:mistral:latest" in settings["available_models"]
    assert "openrouter:openrouter/free" in settings["available_models"]


def test_set_chat_model_updates_workspace_config(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    state.ollama_client.list_models = lambda: [
        "ollama:llama3.2:latest",
        "openrouter:openrouter/free",
    ]

    updated = state.set_chat_model("openrouter:openrouter/free")

    assert updated["model"] == "openrouter:openrouter/free"
    reloaded = Config.load(str(tmp_path / ".devin_agent" / "config.json"))
    assert reloaded.ollama_primary_model == "openrouter:openrouter/free"


def test_chat_model_settings_falls_back_when_primary_is_not_enabled(
    tmp_path: Path,
) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    state.config.ollama_primary_model = "ollama:qwen3.5:latest"
    state.ollama_client.list_models = lambda: [
        "ollama:llama3.2:latest",
        "ollama:qwen3.5:latest",
    ]

    settings = state.get_chat_model_settings()

    assert settings["model"] == "ollama:llama3.2:latest"
    assert "ollama:qwen3.5:latest" not in settings["available_models"]
