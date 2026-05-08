from __future__ import annotations

from pathlib import Path

from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.agents.base import AgentResponse
from AGENT_Joko.model_router import ModelRouter
from AGENT_Joko.orchestrator import ExecutionResult, Orchestrator


class _DummyRouted:
    enhanced_prompt = "design it"

    def to_dict(self) -> dict:
        return {"model": "dummy"}


def _make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        model_warmup_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


def test_full_workflow_uses_execution_result_data(tmp_path: Path) -> None:
    orch = Orchestrator(config=_make_config(tmp_path))

    def fake_execute(agent_name: str, task: str, func):
        return ExecutionResult(
            success=True,
            message=f"{agent_name} completed",
            data=f"{agent_name} output",
            agent_name=agent_name,
        )

    orch._execute_with_healing = fake_execute  # type: ignore[assignment]
    orch._emit = lambda *args, **kwargs: None  # type: ignore[assignment]

    result = orch._execute_full_workflow("build scraper", _DummyRouted())

    assert result.success is True
    assert "ARCHITECT" in result.data["content"]
    assert "CODER" in result.data["content"]
    assert result.data["steps"][0][0] == "architect"


def test_routed_task_serializes_for_full_workflow_result(tmp_path: Path) -> None:
    router = ModelRouter(config=_make_config(tmp_path))
    routed = router.analyze_task("Create simple scraping python script")

    payload = routed.to_dict()

    assert payload["task_type"] == "coding"
    assert payload["complexity"] == "medium"
    assert payload["model"] == payload["recommended_model"]


def test_healing_hands_off_to_another_agent_before_fixer(tmp_path: Path) -> None:
    orch = Orchestrator(config=_make_config(tmp_path))
    events = []
    orch._emit = lambda event_type, message, **extra: events.append((event_type, message, extra))  # type: ignore[assignment]

    class _FakeAgent:
        def __init__(self, response: AgentResponse):
            self.response = response
            self.calls = []

        def process(self, task: str, context=None) -> AgentResponse:
            self.calls.append(task)
            return self.response

    reviewer = _FakeAgent(
        AgentResponse(
            success=True, content="Patch the failing path and rerun validation."
        )
    )
    fixer = _FakeAgent(AgentResponse(success=True, content="Applied the fix."))
    orch._agents["tester"] = reviewer  # coder failures should hand off to tester first
    orch._agents["fixer"] = fixer

    failed = AgentResponse(success=False, content="compile error", error="traceback")
    result = orch._attempt_healing("coder", "build scraper", failed, max_attempts=1)

    assert result is not None
    assert result.success is True
    assert "handoff" in result.message
    assert reviewer.calls and "taking over recovery" in reviewer.calls[0]
    assert fixer.calls and "Recovery guidance from tester" in fixer.calls[0]
    assert any(
        evt[0] == "heal_handoff" and evt[2].get("agent") == "tester" for evt in events
    )
    assert any(
        evt[0] == "heal_fix_start" and evt[2].get("reviewer") == "tester"
        for evt in events
    )


def test_healing_uses_fast_quick_process_without_qwen_fallback(tmp_path: Path) -> None:
    orch = Orchestrator(config=_make_config(tmp_path))
    orch.config.ollama_fallback_models = [
        "ollama:mistral:latest",
        "openrouter:openrouter/free",
    ]
    orch.config.ollama_healing_timeout_seconds = 17
    orch.config.ollama_healing_max_tokens = 900

    class _FastAgent:
        def __init__(self, success: bool, content: str):
            self.agent_config = type(
                "AgentConfigStub", (), {"model": "ollama:mistral:latest"}
            )()
            self.success = success
            self.content = content
            self.quick_calls = []

        def quick_process(self, task: str, **kwargs) -> AgentResponse:
            self.quick_calls.append({"task": task, **kwargs})
            return AgentResponse(success=self.success, content=self.content)

        def process(self, task: str, context=None) -> AgentResponse:
            raise AssertionError("quick_process should be used for healing")

    reviewer = _FastAgent(True, "Patch the parser import and rerun.")
    fixer = _FastAgent(True, "Applied patch.")
    orch._agents["tester"] = reviewer
    orch._agents["fixer"] = fixer

    failed = AgentResponse(success=False, content="compile error", error="traceback")
    result = orch._attempt_healing("coder", "build scraper", failed, max_attempts=1)

    assert result is not None and result.success is True
    assert reviewer.quick_calls
    assert fixer.quick_calls
    assert reviewer.quick_calls[0]["timeout_seconds"] == 17
    assert reviewer.quick_calls[0]["max_tokens"] == 768
    assert reviewer.quick_calls[0]["fallback_models"] == ["openrouter:openrouter/free"]
    assert fixer.quick_calls[0]["timeout_seconds"] == 17
    assert fixer.quick_calls[0]["max_tokens"] == 900
    assert fixer.quick_calls[0]["fallback_models"] == ["openrouter:openrouter/free"]


def test_orchestrator_status_includes_startup_warmup_results(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.model_warmup_enabled = True
    config.model_warmup_prompt = "Reply with OK only."
    config.model_warmup_timeout_seconds = 7
    config.models = {
        "architect": "ollama:llama3.2:latest",
        "coder": "ollama:mistral:latest",
    }
    config.ollama_fallback_models = [
        "ollama:mistral:latest",
        "openrouter:openrouter/free",
    ]

    orch = Orchestrator(config=config)
    warmup_calls = []

    def fake_warmup(models, prompt, timeout_seconds):
        warmup_calls.append(
            {"models": models, "prompt": prompt, "timeout_seconds": timeout_seconds}
        )
        return [{"model": model, "success": True} for model in models]

    for agent in orch._agents.values():
        agent.ollama.warmup = fake_warmup  # type: ignore[method-assign]
    orch._run_model_warmup()

    status = orch.get_status()

    assert warmup_calls
    assert warmup_calls[0]["models"] == [
        "ollama:llama3.2:latest",
        "ollama:mistral:latest",
        "openrouter:openrouter/free",
    ]
    assert warmup_calls[0]["prompt"] == "Reply with OK only."
    assert warmup_calls[0]["timeout_seconds"] == 7
    assert status["warmup"]["enabled"] is True
    assert status["warmup"]["started"] is True
    assert status["warmup"]["finished"] is True
    assert status["warmup"]["results"][0]["model"] == "ollama:llama3.2:latest"


def test_orchestrator_status_exposes_dashboard_runtime_fields(tmp_path: Path) -> None:
    orch = Orchestrator(config=_make_config(tmp_path))

    class _HealthClient:
        def health(self):
            return {
                "ok": True,
                "host": "http://localhost:11434",
                "models": ["ollama:llama3.2:latest", "ollama:mistral:latest"],
                "local_ok": True,
                "local_error": None,
                "remote_ready": False,
            }

    for agent in orch._agents.values():
        agent.ollama = _HealthClient()  # type: ignore[assignment]

    status = orch.get_status()

    assert status["ollama"]["ok"] is True
    assert status["ollama"]["local_ok"] is True
    assert status["ollama"]["remote_ready"] is False
    assert status["ollama"]["models"] == [
        "ollama:llama3.2:latest",
        "ollama:mistral:latest",
    ]


def test_orchestrator_seeds_swarm_memory_schema(tmp_path: Path) -> None:
    orch = Orchestrator(config=_make_config(tmp_path))

    schema_entries = orch.memory_store.get_by_tag(orch._SWARM_MEMORY_SCHEMA_TAG)
    assert schema_entries
    assert "critical_failures" in schema_entries[0].content
    assert "max_iterations" in schema_entries[0].content

    architect_entries = orch.memory_store.get_by_tag(orch._SWARM_ROLE_TAGS["architect"])
    tester_entries = orch.memory_store.get_by_tag(orch._SWARM_ROLE_TAGS["tester"])
    assert architect_entries
    assert tester_entries
    assert "architect state" in architect_entries[0].content
    assert "critical_failures" in tester_entries[0].content

    scraper_entries = orch.memory_store.get_by_tag(orch._SCRAPER_MEMORY_TAG)
    assert scraper_entries
    assert "First Name" in scraper_entries[0].content
    assert "camis" in scraper_entries[0].content
