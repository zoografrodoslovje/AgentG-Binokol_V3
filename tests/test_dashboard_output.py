from __future__ import annotations

import json
from pathlib import Path

from AGENT_Joko.config import Config, GitConfig, MemoryConfig
from AGENT_Joko.dashboard.api import DashboardState


def _make_config(tmp_path: Path) -> Config:
    return Config(
        offline_queue_enabled=False,
        model_warmup_enabled=False,
        workspace_root=str(tmp_path),
        memory=MemoryConfig(storage_path=str(tmp_path / "memory")),
        git=GitConfig(auto_commit=False),
    )


def test_output_directory_settings_and_export(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))

    settings = state.set_output_dir("finished")
    assert settings["resolved_path"].endswith("finished")
    assert Path(settings["resolved_path"]).is_dir()

    task = state.create_task("build scraper", "full")
    task.status = "completed"
    task.result = {"success": True, "message": "done"}
    exported = state._export_task_artifacts(task)

    assert len(exported) == 4
    for path in exported:
        assert Path(path).exists()

    payload = json.loads(Path(exported[0]).read_text(encoding="utf-8"))
    assert payload["id"] == task.id
    assert payload["result"]["message"] == "done"
    assert payload["result"]["primary_artifact"].endswith(".py")
    assert "events" not in payload
    assert "routing" not in payload

    md_body = Path(exported[1]).read_text(encoding="utf-8")
    txt_body = Path(exported[2]).read_text(encoding="utf-8")
    assert "## Result" not in md_body
    assert "\nResult\n" not in txt_body


def test_export_hides_internal_orchestration_payloads(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("Create a .txt file with text insight: ELENA TE SAKAM.", "manual")
    task.status = "completed"
    task.result = {
        "success": True,
        "message": "Full workflow completed",
        "data": {
            "content": "=== ARCHITECT === hidden chain of thought",
            "steps": [["architect", {"data": "hidden detail"}]],
        },
    }
    task.routing = {"enhanced_prompt": "hidden prompt"}
    task.add_event("agent_ok", "hidden event", agent="architect", data={"error": "hidden"})

    exported = state._export_task_artifacts(task)

    payload = json.loads(Path(exported[0]).read_text(encoding="utf-8"))
    md_body = Path(exported[1]).read_text(encoding="utf-8")
    txt_body = Path(exported[2]).read_text(encoding="utf-8")

    assert payload["result"]["success"] is True
    assert payload["result"]["message"] == "Full workflow completed"
    assert payload["result"]["primary_artifact"].endswith(".txt")
    assert "routing" not in payload
    assert "events" not in payload
    assert "ARCHITECT" not in md_body
    assert "ARCHITECT" not in txt_body
    assert "Result" not in txt_body


def test_python_goal_exports_real_script_artifact(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("Create python scraper script", "auto")
    task.status = "completed"
    task.result = {
        "success": True,
        "message": "Full workflow completed",
        "data": {
            "steps": [
                [
                    "coder",
                    {
                        "success": True,
                        "message": "coder completed",
                        "data": "```python\nimport requests\n\n\ndef scrape():\n    return requests.get('https://example.com', timeout=30).text\n```",
                    },
                ]
            ]
        },
    }

    exported = state._export_task_artifacts(task)

    assert len(exported) == 4
    script_path = Path(exported[3])
    assert script_path.suffix == ".py"
    assert script_path.exists()
    script_body = script_path.read_text(encoding="utf-8")
    assert "def scrape" in script_body

    payload = json.loads(Path(exported[0]).read_text(encoding="utf-8"))
    assert payload["result"]["primary_artifact"].endswith(".py")

    md_body = Path(exported[1]).read_text(encoding="utf-8")
    assert "## Output" in md_body
    assert "```python" in md_body
    assert "def scrape" in md_body
    assert "## Goal" not in md_body

def test_default_output_dir_prefers_finished_work_inside_workspace(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    assert state.get_output_dir_settings()["resolved_path"] == str((tmp_path / "FINISHED_WORK").resolve())

def test_legacy_default_output_dir_is_migrated_to_finished_work(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)
    settings_path = logs_dir / "dashboard_settings.json"
    settings_path.write_text(
        json.dumps({"output_dir": str((fake_home / "output" / "GoKo_Binokol_V2").resolve())}, indent=2),
        encoding="utf-8",
    )

    state = DashboardState(config=_make_config(tmp_path))

    assert state.get_output_dir_settings()["resolved_path"] == str((tmp_path / "FINISHED_WORK").resolve())


def test_run_python_safe_executes_python_file_from_finished_work(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    script_dir = tmp_path / "FINISHED_WORK"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / "hello.py"
    script_path.write_text("print('hello from file')\n", encoding="utf-8")

    result = state.run_python_safe("hello.py")

    assert result["success"] is True
    assert result["stdout"].strip() == "hello from file"
    assert result["executed_file"] == str(script_path.resolve())


def test_scraper_fallback_artifact_uses_merged_csv_schema(tmp_path: Path) -> None:
    state = DashboardState(config=_make_config(tmp_path))
    task = state.create_task("Create python scraper script for NYC restaurants csv", "manual")
    task.status = "completed"
    task.result = {"success": True, "message": "done"}

    exported = state._export_task_artifacts(task)

    script_path = Path(exported[3])
    script_body = script_path.read_text(encoding="utf-8")

    assert "MAX_RETRIES = 3" in script_body
    assert "'First Name'" in script_body
    assert "'org_street_address'" in script_body
    assert "'camis'" in script_body
    assert 'output_file = Path("nyc_restaurants.csv")' in script_body
