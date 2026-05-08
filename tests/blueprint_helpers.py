from __future__ import annotations

from pathlib import Path

from AGENT_Joko.agents.base import AgentResponse
from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.dashboard.api import DashboardState
from AGENT_Joko.orchestrator import Orchestrator


def make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


def make_state(tmp_path: Path) -> DashboardState:
    return DashboardState(config=make_config(tmp_path))


def make_orchestrator(tmp_path: Path) -> Orchestrator:
    return Orchestrator(config=make_config(tmp_path))


def create_manual_task(state: DashboardState, goal: str):
    return state.create_task(goal, "manual")


def fail_task(state: DashboardState, task, error: str = "traceback"):
    task.status = "failed"
    task.error = error
    task.add_event("agent_fail", "Simulated task failure", agent="tester", data={"error": error})
    state._sync_queue_task(task)
    return task


def complete_task(state: DashboardState, task, result: dict | None = None):
    task.status = "completed"
    task.result = result or {"success": True, "message": "done"}
    task.finished_at = task.finished_at or task.created_at
    task.add_event("task", "Simulated task completion")
    state._sync_queue_task(task)
    return task


def retry_task(state: DashboardState, task_id: str):
    return state.retry_task(task_id)


def clear_tasks(state: DashboardState):
    return state.clear_tasks()


class FakeHealingAgent:
    def __init__(self, model: str, success: bool, content: str):
        self.agent_config = type("AgentConfigStub", (), {"model": model})()
        self.success = success
        self.content = content
        self.calls = []

    def quick_process(self, task: str, **kwargs) -> AgentResponse:
        self.calls.append({"task": task, **kwargs})
        return AgentResponse(success=self.success, content=self.content)

    def process(self, task: str, context=None) -> AgentResponse:
        self.calls.append({"task": task, "context": context})
        return AgentResponse(success=self.success, content=self.content)
