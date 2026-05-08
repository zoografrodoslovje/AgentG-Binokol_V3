from __future__ import annotations

from pathlib import Path

from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.dashboard.api import DashboardState
from AGENT_Joko.task_queue import TaskPriority, TaskQueue, TaskStatus


def _make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


def test_dashboard_task_persists_to_real_queue_storage(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("build scraper", "manual")

    queue_path = tmp_path / ".devin_agent" / "task_queue.json"
    assert queue_path.exists()
    assert task.queue_id is not None

    reloaded = DashboardState(config=_make_config(tmp_path))
    persisted = reloaded.get_task(task.id)

    assert persisted.goal == "build scraper"
    assert persisted.workflow == "manual"
    assert persisted.queue_id == task.queue_id
    assert persisted.status == "queued"


def test_dashboard_retry_clones_queue_backed_task(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("repair parser", "manual")
    task.status = "failed"
    task.error = "traceback"
    state._sync_queue_task(task)

    retried = state.retry_task(task.id)

    assert retried.id != task.id
    assert retried.queue_id != task.queue_id
    assert retried.retry_of == task.id
    assert retried.status == "queued"

    reloaded = DashboardState(config=_make_config(tmp_path))
    loaded_retry = reloaded.get_task(retried.id)
    assert loaded_retry.retry_of == task.id
    assert loaded_retry.queue_id == retried.queue_id


def test_dashboard_lists_external_queue_entries(tmp_path: Path) -> None:
    queue_path = tmp_path / ".devin_agent" / "task_queue.json"
    queue = TaskQueue(storage_path=str(queue_path))
    queue_item = queue.add(
        "cli-created task",
        priority=TaskPriority.HIGH,
        metadata={"workflow": "manual", "source": "cli"},
    )

    state = DashboardState(config=_make_config(tmp_path))
    tasks = state.list_tasks()
    loaded = next(task for task in tasks if task.queue_id == queue_item.id)

    assert loaded.goal == "cli-created task"
    assert loaded.priority == "high"
    assert loaded.source == "cli"
    assert loaded.status == "queued"


def test_dashboard_clear_tasks_resets_memory_and_queue(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    first = state.create_task("build scraper", "manual")
    second = state.create_task("repair parser", "manual")

    result = state.clear_tasks()

    assert result["success"] is True
    assert state.list_tasks() == []
    assert state._last_task_id is None
    assert state.task_queue.get_all() == []
    assert first.id not in state._tasks
    assert second.id not in state._tasks


def test_dashboard_stop_agents_cancels_running_and_queued_tasks(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    running = state.create_task("build scraper", "auto")
    queued = state.create_task("repair parser", "manual")

    running.status = "running"
    running.started_at = running.created_at
    state._sync_queue_task(running)

    result = state.stop_agents()

    assert result["success"] is True
    assert running.id in result["stopped"]
    assert queued.id in result["stopped"]
    assert state.get_task(running.id).status == "cancelled"
    assert state.get_task(queued.id).status == "cancelled"
    assert state.task_queue.get(running.queue_id).status == TaskStatus.CANCELLED
    assert state.task_queue.get(queued.queue_id).status == TaskStatus.CANCELLED
