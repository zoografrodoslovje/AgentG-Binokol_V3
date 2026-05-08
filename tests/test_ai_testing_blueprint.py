from __future__ import annotations

import json
from pathlib import Path

from AGENT_Joko.agents.base import AgentResponse

from .blueprint_helpers import (
    FakeHealingAgent,
    clear_tasks,
    complete_task,
    create_manual_task,
    fail_task,
    make_orchestrator,
    make_state,
    retry_task,
)


def test_phase_i_foundation_bootstraps_dashboard_workspace(tmp_path: Path) -> None:
    state = make_state(tmp_path)

    config_path = tmp_path / ".devin_agent" / "config.json"
    settings_path = tmp_path / "logs" / "dashboard_settings.json"

    assert config_path.exists()
    assert settings_path.exists()

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "output_dir" in settings
    assert state.get_output_dir_settings()["resolved_path"]


def test_phase_ii_reusable_blocks_cover_task_lifecycle(tmp_path: Path) -> None:
    state = make_state(tmp_path)

    task = create_manual_task(state, "Run reusable block scenario")
    failed = fail_task(state, task, error="locator changed")
    retried = retry_task(state, failed.id)
    completed = complete_task(state, retried, result={"success": True, "message": "recovered"})

    assert failed.status == "failed"
    assert retried.retry_of == failed.id
    assert completed.status == "completed"
    assert completed.result["message"] == "recovered"


def test_phase_iii_self_healing_recovers_through_reviewer_and_fixer(tmp_path: Path) -> None:
    orch = make_orchestrator(tmp_path)
    orch.config.ollama_fallback_models = ["ollama:mistral:latest", "openrouter:openrouter/free"]

    reviewer = FakeHealingAgent("openrouter:openrouter/free", True, "Use the alternate locator and rerun.")
    fixer = FakeHealingAgent("ollama:mistral:latest", True, "Applied healing patch.")
    orch._agents["tester"] = reviewer
    orch._agents["fixer"] = fixer

    failed = AgentResponse(success=False, content="element missing", error="NoSuchElementException")
    healed = orch._attempt_healing("coder", "Execute checkout flow", failed, max_attempts=1)

    assert healed is not None
    assert healed.success is True
    assert healed.agent_name == "fixer"
    assert reviewer.calls[0]["fallback_models"] == ["ollama:mistral:latest"]
    assert fixer.calls[0]["fallback_models"] == ["openrouter:openrouter/free"]


def test_phase_iv_orchestrated_retry_exports_results_and_cleans_state(tmp_path: Path) -> None:
    state = make_state(tmp_path)

    task = create_manual_task(state, "Execute end-to-end resilient workflow")
    fail_task(state, task, error="button label changed")
    retried = retry_task(state, task.id)
    complete_task(state, retried, result={"success": True, "message": "healed flow passed"})

    exported = state._export_task_artifacts(retried)
    cleared = clear_tasks(state)

    assert len(exported) == 2
    assert all(Path(path).exists() for path in exported)
    payload = json.loads(Path(exported[0]).read_text(encoding="utf-8"))
    assert payload["retry_of"] == task.id
    assert payload["result"]["message"] == "healed flow passed"
    assert cleared["success"] is True
    assert state.list_tasks() == []
