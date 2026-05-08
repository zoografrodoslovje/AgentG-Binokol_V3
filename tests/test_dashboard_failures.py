from __future__ import annotations

import json
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


def test_agent_failure_registry_persists_and_clears(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("build scraper", "full")

    state._record_agent_failure(
        task=task,
        event_type="agent_fail",
        agent="coder",
        message="coder failed",
        error="traceback",
    )

    result = state.list_agent_failures(limit=10)
    assert result["summary"]["coder"] == 1
    assert result["items"][0]["agent"] == "coder"

    log_path = tmp_path / "logs" / "agent_failures.json"
    assert log_path.exists()
    saved = json.loads(log_path.read_text(encoding="utf-8"))
    assert saved[-1]["message"] == "coder failed"

    cleared = state.clear_agent_failures()
    assert cleared["success"] is True
    assert state.list_agent_failures(limit=10)["items"] == []


def test_retry_task_clones_goal_and_marks_source(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("build scraper", "manual")
    task.status = "failed"
    task.error = "traceback"

    retried = state.retry_task(task.id)

    assert retried.goal == task.goal
    assert retried.workflow == task.workflow
    assert retried.retry_of == task.id
    assert any(event.type == "retry" for event in retried.events)
    assert any(event.type == "retry" for event in task.events)
