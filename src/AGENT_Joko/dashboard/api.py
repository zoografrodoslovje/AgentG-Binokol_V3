from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import time
import uuid
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ..config import Config, get_config
from ..inference_queue import InferenceQueue
from ..ollama_client import OllamaClient, OllamaError
from ..orchestrator import Orchestrator
from ..task_queue import TaskPriority, TaskQueue, TaskStatus

LOCAL_HEROES_CSV_FIELDS = [
    "First Name",
    "Last Name",
    "Title",
    "Cleaned Title",
    "Uncleaned Company Name",
    "Cleaned Company Name",
    "Unverified Email",
    "quality",
    "result",
    "free",
    "role",
    "Seniority",
    "Departments",
    "Mobile Phone",
    "# Employees",
    "Industry",
    "Cleaned Industry",
    "Keywords",
    "Person Linkedin Url",
    "Website",
    "Company Linkedin Url",
    "Facebook Url",
    "Twitter Url",
    "Company Address",
    "SEO Description",
    "Technologies",
    "Annual Revenue",
    "Total Funding",
    "Latest Funding",
    "Latest Funding Amount",
    "Retail Locations",
    "LinkedIn Group",
    "LinkedIn Follow",
    "headline",
    "org_id",
    "State",
    "City",
    "org_founded_year",
    "org_city",
    "org_country",
    "industry_tag_id",
    "postal_code",
    "org_state",
    "org_street_address",
]

NYC_RESTAURANT_CSV_FIELDS = [
    "camis",
    "name",
    "boro",
    "building",
    "street",
    "zipcode",
    "phone",
    "cuisine",
    "inspection_date",
    "grade",
    "score",
]

SCRAPER_CSV_FIELDS = LOCAL_HEROES_CSV_FIELDS + NYC_RESTAURANT_CSV_FIELDS


@dataclass
class TaskEvent:
    ts: float
    type: str
    message: str
    agent: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    id: str
    goal: str
    workflow: str
    retry_of: Optional[str] = None
    queue_id: Optional[str] = None
    priority: str = "normal"
    dependencies: List[str] = field(default_factory=list)
    source: str = "dashboard"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    status: str = "queued"  # queued|running|completed|failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    events: List[TaskEvent] = field(default_factory=list)
    routing: Optional[Dict[str, Any]] = None

    def add_event(
        self,
        type: str,
        message: str,
        agent: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.events.append(
            TaskEvent(
                ts=time.time(),
                type=type,
                message=message,
                agent=agent,
                data=data or {},
            )
        )
        if len(self.events) > 500:
            self.events = self.events[-500:]


MAX_EXECUTE_GOAL_LENGTH = 100_000


class ExecuteRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=MAX_EXECUTE_GOAL_LENGTH)
    workflow: str = Field(default="auto")  # auto|manual|full|code_only|debate_only


class ShellRequest(BaseModel):
    command: str = Field(min_length=1, max_length=20_000)


class PythonRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)


class WriteFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="")


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=200)


class OutputDirectoryRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class ChatRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, max_length=50_000)
    messages: Optional[List[Dict[str, str]]] = None
    model: Optional[str] = None


class ChatModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class DashboardState:
    _AGENT_NAMES = ("architect", "coder", "tester", "fixer", "debator")
    _QUEUE_TO_DASHBOARD_STATUS = {
        TaskStatus.PENDING: "queued",
        TaskStatus.IN_PROGRESS: "running",
        TaskStatus.COMPLETED: "completed",
        TaskStatus.FAILED: "failed",
        TaskStatus.BLOCKED: "blocked",
        TaskStatus.CANCELLED: "cancelled",
    }
    _DASHBOARD_TO_QUEUE_STATUS = {
        "queued": TaskStatus.PENDING,
        "running": TaskStatus.IN_PROGRESS,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
        "blocked": TaskStatus.BLOCKED,
        "cancelled": TaskStatus.CANCELLED,
    }

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        # Shared orchestrator for tool endpoints (shell/files/git/memory).
        self.tool_orchestrator = Orchestrator(self.config)
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskState] = {}
        self._last_task_id: Optional[str] = None
        self._config_path = (
            Path(self._workspace_root()) / ".devin_agent" / "config.json"
        )
        self._settings_path = (
            Path(self._workspace_root()) / "logs" / "dashboard_settings.json"
        )
        self._agent_failure_log_path = (
            Path(self._workspace_root()) / "logs" / "agent_failures.json"
        )
        self._load_workspace_config()
        self._queue_path = (
            Path(self._workspace_root()) / ".devin_agent" / "task_queue.json"
        )
        self.task_queue = TaskQueue(storage_path=str(self._queue_path))
        self.tool_orchestrator.task_queue = self.task_queue
        self._settings = self._load_settings()
        self._agent_failure_registry = self._load_agent_failure_registry()
        self._cancelled_task_ids: set[str] = set()

        self.ollama_client = OllamaClient(
            host=self.config.ollama_host,
            timeout_seconds=getattr(self.config, "ollama_timeout_seconds", 60),
            max_context_tokens=getattr(self.config, "ollama_max_context_tokens", 2048),
            temperature=getattr(self.config, "ollama_temperature", 0.7),
            idle_keep_alive_minutes=getattr(
                self.config, "ollama_idle_timeout_minutes", 5
            ),
            enable_caching=getattr(self.config, "ollama_enable_caching", True),
            cache_ttl_seconds=getattr(self.config, "ollama_cache_ttl_seconds", 300),
            cache_max_entries=getattr(self.config, "ollama_cache_max_entries", 200),
            groq_api_key=getattr(self.config, "groq_api_key", None),
            groq_base_url=getattr(
                self.config, "groq_base_url", "https://api.groq.com/openai/v1"
            ),
            openai_api_key=getattr(self.config, "openai_api_key", None),
            openai_base_url=getattr(
                self.config, "openai_base_url", "https://api.openai.com/v1"
            ),
            openrouter_api_key=getattr(self.config, "openrouter_api_key", None),
            openrouter_base_url=getattr(
                self.config, "openrouter_base_url", "https://openrouter.ai/api/v1"
            ),
            catalog_models=self._catalog_models(),
        )
        self.inference_queue = InferenceQueue()
        self._inf_stop = threading.Event()
        self._warmup_status: Dict[str, Any] = {
            "enabled": bool(getattr(self.config, "model_warmup_enabled", False)),
            "started": False,
            "finished": False,
            "results": [],
        }
        if getattr(self.config, "offline_queue_enabled", True):
            self._start_inference_worker()
        if getattr(self.config, "model_warmup_enabled", False):
            self._start_model_warmup()

    def _json_safe(self, value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)

    def _priority_to_name(self, priority: TaskPriority) -> str:
        return priority.name.lower()

    def _priority_from_name(self, name: Optional[str]) -> TaskPriority:
        mapping = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        return mapping.get((name or "").strip().lower(), TaskPriority.NORMAL)

    def _status_from_queue(self, status: TaskStatus) -> str:
        return self._QUEUE_TO_DASHBOARD_STATUS.get(status, "queued")

    def _status_to_queue(self, status: str) -> TaskStatus:
        return self._DASHBOARD_TO_QUEUE_STATUS.get(
            (status or "").strip().lower(), TaskStatus.PENDING
        )

    def _task_metadata(self, task: TaskState) -> Dict[str, Any]:
        return {
            "source": task.source,
            "dashboard_task_id": task.id,
            "goal": task.goal,
            "workflow": task.workflow,
            "retry_of": task.retry_of,
            "priority": task.priority,
            "dependencies": list(task.dependencies),
            "routing": self._json_safe(task.routing),
            "result": self._json_safe(task.result),
            "error": task.error,
            "events": [self._json_safe(e.__dict__) for e in task.events],
        }

    def _sync_queue_task(self, task: TaskState) -> None:
        if not task.queue_id:
            return
        with self._lock:
            queue_task = self.task_queue.get(task.queue_id)
            if not queue_task:
                return
            queue_task.description = task.goal
            queue_task.priority = self._priority_from_name(task.priority)
            queue_task.dependencies = list(task.dependencies)
            queue_task.status = self._status_to_queue(task.status)
            queue_task.started_at = task.started_at
            queue_task.completed_at = task.finished_at
            safe_json_text = None
            if task.result is not None:
                safe_json_text = json.dumps(self._json_safe(task.result), indent=2)
            queue_task.result = safe_json_text
            queue_task.error = task.error
            queue_task.metadata = self._task_metadata(task)
            self.task_queue.update(queue_task)

    def _ensure_task_state(self, queue_task) -> TaskState:
        meta = queue_task.metadata or {}
        task_id = meta.get("dashboard_task_id") or f"queue_{queue_task.id}"
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                task = TaskState(
                    id=task_id,
                    goal=meta.get("goal") or queue_task.description,
                    workflow=meta.get("workflow") or "auto",
                    retry_of=meta.get("retry_of"),
                    queue_id=queue_task.id,
                    priority=meta.get("priority")
                    or self._priority_to_name(queue_task.priority),
                    dependencies=list(
                        meta.get("dependencies") or queue_task.dependencies or []
                    ),
                    source=meta.get("source") or "queue",
                    created_at=queue_task.created_at,
                )
                self._tasks[task_id] = task

            task.goal = meta.get("goal") or queue_task.description
            task.workflow = meta.get("workflow") or task.workflow or "auto"
            task.retry_of = meta.get("retry_of")
            task.queue_id = queue_task.id
            task.priority = meta.get("priority") or self._priority_to_name(
                queue_task.priority
            )
            task.dependencies = list(
                meta.get("dependencies") or queue_task.dependencies or []
            )
            task.source = meta.get("source") or task.source
            task.created_at = queue_task.created_at
            task.started_at = queue_task.started_at
            task.finished_at = queue_task.completed_at
            task.status = self._status_from_queue(queue_task.status)
            task.result = meta.get("result")
            if task.result is None and queue_task.result is not None:
                task.result = {"summary": queue_task.result}
            task.error = queue_task.error or meta.get("error")
            task.routing = meta.get("routing")
            events = []
            for event_data in meta.get("events") or []:
                if not isinstance(event_data, dict):
                    continue
                events.append(
                    TaskEvent(
                        ts=float(event_data.get("ts", time.time())),
                        type=str(event_data.get("type", "event")),
                        message=str(event_data.get("message", "")),
                        agent=event_data.get("agent"),
                        data=event_data.get("data") or {},
                    )
                )
            task.events = events
            return task

    def _serialize_task_summary(self, task: TaskState) -> Dict[str, Any]:
        queue_task = self.task_queue.get(task.queue_id) if task.queue_id else None
        dependency_total = len(task.dependencies)
        dependencies_ready = dependency_total == 0 or (
            queue_task is not None
            and self.task_queue.dependencies_satisfied(queue_task.id)
        )
        return {
            "id": task.id,
            "queue_id": task.queue_id,
            "goal": task.goal,
            "workflow": task.workflow,
            "priority": task.priority,
            "dependencies": list(task.dependencies),
            "dependency_count": dependency_total,
            "dependencies_ready": dependencies_ready,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "status": task.status,
            "error": task.error,
            "retry_of": task.retry_of,
            "source": task.source,
            "can_start": task.status == "queued" and dependencies_ready,
            "can_cancel": task.status == "queued",
            "can_retry": task.status in {"completed", "failed", "cancelled"},
        }

    def _serialize_task_detail(self, task: TaskState) -> Dict[str, Any]:
        payload = self._serialize_task_summary(task)
        payload.update(
            {
                "result": self._json_safe(task.result),
                "routing": self._json_safe(task.routing),
                "events": [self._json_safe(e.__dict__) for e in task.events],
            }
        )
        return payload

    def _start_inference_worker(self) -> None:
        def _worker():
            while not self._inf_stop.is_set():
                try:
                    nxt = self.inference_queue.next_pending()
                    if not nxt:
                        time.sleep(1.0)
                        continue
                    health = self.ollama_client.health()
                    if not health.get("ok"):
                        time.sleep(2.0)
                        continue
                    self.inference_queue.mark_running(nxt.id)
                    try:
                        if nxt.kind == "chat":
                            res = self.ollama_client.chat(
                                messages=nxt.messages,
                                model=nxt.model,
                                fallback_models=nxt.fallback_models,
                                options=nxt.options,
                            )
                            self.inference_queue.mark_done(nxt.id, res)
                        else:
                            self.inference_queue.mark_failed(
                                nxt.id, f"Unsupported kind: {nxt.kind}"
                            )
                    except Exception as e:
                        self.inference_queue.retry_if_possible(nxt.id, str(e))
                except Exception:
                    time.sleep(1.0)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _warmup_models(self) -> List[str]:
        candidates = [
            getattr(self.config, "ollama_primary_model", ""),
            *list(getattr(self.config, "models", {}).values()),
            *list(getattr(self.config, "ollama_fallback_models", []) or []),
        ]
        ordered: List[str] = []
        seen = set()
        for model_name in candidates:
            model_name = (model_name or "").strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            ordered.append(model_name)
        return ordered

    def _start_model_warmup(self) -> None:
        def _run() -> None:
            self._warmup_status["started"] = True
            try:
                models = self._warmup_models()
                self._warmup_status["results"] = self.ollama_client.warmup(
                    models=models,
                    prompt=getattr(
                        self.config, "model_warmup_prompt", "Reply with OK only."
                    ),
                    timeout_seconds=getattr(
                        self.config, "model_warmup_timeout_seconds", 20
                    ),
                )
            except Exception as e:
                self._warmup_status["results"] = [{"success": False, "error": str(e)}]
            finally:
                self._warmup_status["finished"] = True

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _load_workspace_config(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        if self._config_path.exists():
            try:
                loaded = Config.load(str(self._config_path))
                loaded.workspace_root = self._workspace_root()
                loaded.memory.storage_path = self.config.memory.storage_path
                loaded.ollama_fallback_models = self._sanitize_fallback_models(
                    loaded.ollama_fallback_models,
                    primary_model=loaded.ollama_primary_model,
                )
                self.config = loaded
                self.tool_orchestrator.config = loaded
                # Persist migrated/sanitized settings so old fallback drift is removed.
                self._save_workspace_config()
                return
            except Exception:
                pass
        self._save_workspace_config()

    def _save_workspace_config(self) -> None:
        self.config.workspace_root = self._workspace_root()
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.save(str(self._config_path))

    def _load_agent_failure_registry(self) -> List[Dict[str, Any]]:
        path = self._agent_failure_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-500:]
        except Exception:
            pass
        return []

    def _default_output_dir(self) -> str:
        return str((Path(self._workspace_root()) / "FINISHED_WORK").resolve())

    def _load_settings(self) -> Dict[str, Any]:
        path = self._settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        defaults = {"output_dir": self._default_output_dir()}
        if not path.exists():
            path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
            return defaults
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
        current_output = (defaults.get("output_dir") or "").strip()
        if current_output in self._legacy_default_output_dirs():
            defaults["output_dir"] = self._default_output_dir()
            path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
        return defaults

    def _legacy_default_output_dirs(self) -> set[str]:
        workspace_root = Path(self._workspace_root()).resolve()
        return {
            str((Path.home() / "Desktop" / "agent_joko BUILDS").resolve()),
            str((Path.home() / "output" / "agent_joko").resolve()),
            str((Path.home() / "output" / "GoKo_Binokol_V2").resolve()),
            str((Path.home() / "output" / "agent_joko").resolve()),
            str((workspace_root / "exports").resolve()),
            str(workspace_root),
        }

    def _save_settings(self) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            json.dumps(self._settings, indent=2), encoding="utf-8"
        )

    def _resolve_output_dir(self, raw_path: Optional[str] = None) -> Path:
        value = (
            raw_path if raw_path is not None else self._settings.get("output_dir") or ""
        ).strip()
        if not value:
            value = self._default_output_dir()
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = Path(self._workspace_root()) / path
        return path.resolve()

    def get_output_dir_settings(self) -> Dict[str, str]:
        configured = self._settings.get("output_dir") or self._default_output_dir()
        resolved = str(self._resolve_output_dir(configured))
        return {"path": configured, "resolved_path": resolved}

    def get_chat_model_settings(self) -> Dict[str, Any]:
        models = self._curated_chat_models()
        primary = getattr(self.config, "ollama_primary_model", "") or ""
        if primary not in models:
            primary = models[0] if models else ""
        return {
            "model": primary,
            "available_models": models,
            "fallback_models": self._sanitize_fallback_models(
                getattr(self.config, "ollama_fallback_models", []) or [],
                primary_model=primary,
            ),
        }

    def _supported_chat_models(self) -> List[str]:
        supported: List[str] = []
        seen = set()

        candidates = [
            *list(getattr(self.config, "ollama_fallback_models", []) or []),
            *list(getattr(self.config, "models", {}).values()),
        ]
        provider_catalog = getattr(self.config, "provider_catalog_models", {}) or {}
        for provider_models in provider_catalog.values():
            candidates.extend(provider_models or [])

        for model_name in candidates:
            model_name = (model_name or "").strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            supported.append(model_name)
        return supported

    def _curated_chat_models(self) -> List[str]:
        supported = self._supported_chat_models()
        available = set(self.ollama_client.list_models())
        curated = [model_name for model_name in supported if model_name in available]
        return curated or supported

    def _sanitize_fallback_models(
        self, fallback_models: List[str], primary_model: Optional[str] = None
    ) -> List[str]:
        cleaned = []
        seen = {primary_model} if primary_model else set()
        for name in fallback_models:
            if not name or name in seen:
                continue
            seen.add(name)
            if "qwen" in name.lower():
                continue
            cleaned.append(name)
        return cleaned or ["ollama:mistral:latest", "openrouter:openrouter/free"]

    def _catalog_models(self) -> List[str]:
        provider_catalog = getattr(self.config, "provider_catalog_models", {}) or {}
        models: List[str] = []
        seen = set()
        for provider_models in provider_catalog.values():
            for model_name in provider_models or []:
                if not model_name or model_name in seen:
                    continue
                seen.add(model_name)
                models.append(model_name)
        return models

    def set_chat_model(self, raw_model: str) -> Dict[str, Any]:
        model = (raw_model or "").strip()
        if not model:
            raise ValueError("Model is required")
        models = self._curated_chat_models()
        if model not in models:
            raise ValueError(f"Model is not enabled in this app: {model}")
        self.config.ollama_primary_model = model
        self.config.ollama_fallback_models = self._sanitize_fallback_models(
            getattr(self.config, "ollama_fallback_models", []) or [],
            primary_model=model,
        )
        self._save_workspace_config()
        return self.get_chat_model_settings()

    def set_output_dir(self, raw_path: str) -> Dict[str, str]:
        raw = (raw_path or "").strip()
        if not raw:
            raise ValueError("Output path is required")
        resolved = str(self._resolve_output_dir(raw))
        Path(resolved).mkdir(parents=True, exist_ok=True)
        self._settings["output_dir"] = resolved
        self._save_settings()
        return {"path": resolved, "resolved_path": resolved}

    def _export_result_summary(self, result: Any, error: Optional[str]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        if isinstance(result, dict):
            if "success" in result:
                summary["success"] = bool(result.get("success"))
            if result.get("message"):
                summary["message"] = str(result.get("message"))
            artifacts = result.get("artifacts")
            if isinstance(artifacts, list) and artifacts:
                summary["artifacts"] = [str(item) for item in artifacts]
            data = result.get("data")
            if isinstance(data, dict):
                for key in ("path", "file", "files", "output_path", "output_paths", "artifact", "artifacts"):
                    value = data.get(key)
                    if value:
                        summary[key] = value
        elif result is not None:
            summary["message"] = str(result)
        if error:
            summary["error"] = error
        return summary

    def _infer_requested_artifact(self, goal: str) -> Dict[str, str]:
        text = (goal or "").strip().lower()
        patterns = [
            (r"\bpython\b|\b\.py\b", ".py", "python"),
            (r"\bjavascript\b|\bjs\b|\b\.js\b", ".js", "javascript"),
            (r"\btypescript\b|\bts\b|\b\.ts\b", ".ts", "typescript"),
            (r"\bhtml\b|\bweb page\b|\bwebsite\b", ".html", "html"),
            (r"\bjson\b|\b\.json\b", ".json", "json"),
            (r"\bmarkdown\b|\b\.md\b", ".md", "markdown"),
            (r"\bcsv\b|\b\.csv\b", ".csv", "csv"),
            (r"\bsql\b|\b\.sql\b", ".sql", "sql"),
            (r"\byaml\b|\byml\b|\b\.ya?ml\b", ".yml", "yaml"),
            (r"\btxt\b|\btext file\b|\bplain text\b|\b\.txt\b", ".txt", "text"),
        ]
        for pattern, extension, language in patterns:
            if re.search(pattern, text):
                return {"extension": extension, "language": language}
        if "script" in text or "scraper" in text:
            return {"extension": ".py", "language": "python"}
        return {"extension": ".txt", "language": "text"}

    def _artifact_filename(self, goal: str, extension: str) -> str:
        raw = re.sub(r"[^a-z0-9]+", "_", (goal or "").lower()).strip("_")
        if not raw:
            raw = "deliverable"
        raw = re.sub(r"^(create|write|generate|build|make)_+", "", raw)
        raw = raw[:80].strip("_") or "deliverable"
        return f"{raw}{extension}"

    def _result_step_text(self, result: Any, agent_name: str) -> str:
        if not isinstance(result, dict):
            return ""
        data = result.get("data")
        if not isinstance(data, dict):
            return ""
        steps = data.get("steps")
        if not isinstance(steps, list):
            return ""
        for step in steps:
            if not isinstance(step, (list, tuple)) or len(step) < 2:
                continue
            if step[0] != agent_name:
                continue
            payload = step[1]
            if isinstance(payload, dict):
                for key in ("data", "content", "message"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
        return ""

    def _extract_fenced_block(self, text: str, language: str) -> str:
        if not text.strip():
            return ""
        matches = re.findall(r"```([\w+-]*)\n(.*?)```", text, re.DOTALL)
        preferred: List[str] = []
        fallback: List[str] = []
        for lang, body in matches:
            candidate = body.strip()
            if not candidate:
                continue
            if language == "text":
                fallback.append(candidate)
                continue
            if (lang or "").strip().lower() in {language, "", "txt", "text"}:
                preferred.append(candidate)
            else:
                fallback.append(candidate)
        if preferred:
            return preferred[0]
        if fallback:
            return fallback[0]
        return ""

    def _fallback_artifact_content(self, goal: str, extension: str) -> str:
        if extension == ".py":
            if "scraper" in (goal or "").lower():
                return "\n".join(
                    [
                        "import csv",
                        "import sys",
                        "import time",
                        "from pathlib import Path",
                        "",
                        "import requests",
                        "",
                        'DATASET_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"',
                        "PAGE_SIZE = 1000",
                        "MAX_RETRIES = 3",
                        "INITIAL_DELAY = 2",
                        "BACKOFF_FACTOR = 2",
                        'USER_AGENT = "agent_joko/1.0"',
                        "TIMEOUT = 30",
                        "",
                        f"FIELDNAMES = {SCRAPER_CSV_FIELDS!r}",
                        "",
                        "def fetch_page(offset, limit, session):",
                        "    params = {",
                        '        "$limit": limit,',
                        '        "$offset": offset,',
                        '        "$order": "camis",',
                        '        "$where": "dba IS NOT NULL",',
                        "    }",
                        "    last_error = None",
                        "    for attempt in range(MAX_RETRIES):",
                        "        try:",
                        '            print(f\"  [Page] offset={offset} attempt={attempt+1}/{MAX_RETRIES}\", file=sys.stderr)',
                        "            response = session.get(",
                        "                DATASET_URL,",
                        "                params=params,",
                        '                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},',
                        "                timeout=TIMEOUT,",
                        "            )",
                        "            response.raise_for_status()",
                        "            return response.json()",
                        "        except requests.exceptions.HTTPError as exc:",
                        "            status_code = exc.response.status_code if exc.response is not None else 0",
                        "            if 500 <= status_code < 600 or status_code == 429:",
                        "                delay = INITIAL_DELAY * (BACKOFF_FACTOR ** attempt)",
                        "                if status_code == 429 and exc.response is not None:",
                        '                    retry_after = exc.response.headers.get("Retry-After")',
                        "                    if retry_after:",
                        "                        try:",
                        "                            delay = max(delay, int(retry_after))",
                        "                        except ValueError:",
                        "                            pass",
                        '                print(f\"  [Retry] HTTP {status_code} in {delay}s\", file=sys.stderr)',
                        "                time.sleep(delay)",
                        "                last_error = exc",
                        "                continue",
                        '            raise RuntimeError(f"HTTP {status_code}: {exc}") from exc',
                        "        except (requests.RequestException, ValueError) as exc:",
                        "            last_error = exc",
                        "            delay = INITIAL_DELAY * (BACKOFF_FACTOR ** attempt)",
                        '            print(f\"  [Retry] {type(exc).__name__} in {delay}s\", file=sys.stderr)',
                        "            time.sleep(delay)",
                        '    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded for offset {offset}") from last_error',
                        "",
                        "def _blank_record():",
                        '    return {field: "" for field in FIELDNAMES}',
                        "",
                        "def normalize_restaurant(row):",
                        "    def clean(value):",
                        '        return str(value) if value is not None else ""',
                        "    record = _blank_record()",
                        "    record.update({",
                        '        "camis": clean(row.get("camis")),',
                        '        "name": clean(row.get("dba")),',
                        '        "boro": clean(row.get("boro")),',
                        '        "building": clean(row.get("building")),',
                        '        "street": clean(row.get("street")),',
                        '        "zipcode": clean(row.get("zipcode")),',
                        '        "phone": clean(row.get("phone")),',
                        '        "cuisine": clean(row.get("cuisine_description")),',
                        '        "inspection_date": clean(row.get("inspection_date")),',
                        '        "grade": clean(row.get("grade")),',
                        '        "score": clean(row.get("score")),',
                        "    })",
                        "    return record",
                        "",
                        "def fetch_all_restaurants(max_records=None):",
                        "    restaurants = []",
                        "    offset = 0",
                        "    start_time = time.time()",
                        "",
                        "    with requests.Session() as session:",
                        "        while True:",
                        "            remaining = PAGE_SIZE if max_records is None else min(PAGE_SIZE, max_records - len(restaurants))",
                        "            if remaining <= 0:",
                        "                break",
                        "",
                        "            fetched = len(restaurants)",
                        "            elapsed = max(time.time() - start_time, 0.001)",
                        "            if max_records:",
                        "                pct = (fetched / max_records) * 100",
                        '                print(f\"[Progress] {fetched}/{max_records} ({pct:.1f}%), {fetched/elapsed:.1f} rows/sec\", file=sys.stderr)',
                        "            else:",
                        '                print(f\"[Progress] {fetched} rows, {fetched/elapsed:.1f} rows/sec\", file=sys.stderr)',
                        "",
                        "            rows = fetch_page(offset, remaining, session)",
                        "            if not rows:",
                        "                break",
                        "",
                        "            restaurants.extend(normalize_restaurant(row) for row in rows)",
                        "            offset += len(rows)",
                        "",
                        "            if len(rows) < remaining:",
                        "                break",
                        "",
                        "    return restaurants",
                        "",
                        "def save_to_csv(restaurants, filename):",
                        "    with open(filename, 'w', newline='', encoding='utf-8') as handle:",
                        "        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)",
                        "        writer.writeheader()",
                        "        writer.writerows(restaurants)",
                        "",
                        "def main():",
                        "    if len(sys.argv) > 1:",
                        "        try:",
                        "            max_records = int(sys.argv[1])",
                        "            if max_records <= 0:",
                        '                raise ValueError("max_records must be positive")',
                        "        except ValueError as exc:",
                        '            print(f"Error: {exc}. Usage: {sys.argv[0]} [MAX_RECORDS]", file=sys.stderr)',
                        "            return 1",
                        "    else:",
                        "        max_records = None",
                        "",
                        "    try:",
                        "        restaurants = fetch_all_restaurants(max_records=max_records)",
                        "    except Exception as exc:",
                        '        print(f"[Fatal] {exc}", file=sys.stderr)',
                        "        return 1",
                        "",
                        "    if not restaurants:",
                        '        print("[Warning] No data fetched", file=sys.stderr)',
                        "        return 1",
                        "",
                        '    output_file = Path("nyc_restaurants.csv")',
                        "    try:",
                        "        save_to_csv(restaurants, output_file)",
                        "    except IOError as exc:",
                        '        print(f"[Fatal] Write failed: {exc}", file=sys.stderr)',
                        "        return 1",
                        "",
                        '    print(f"[Done] Saved {len(restaurants)} rows to {output_file}")',
                        "    return 0",
                        "",
                        "if __name__ == '__main__':",
                        "    sys.exit(main())",
                    ]
                )
            return "\n".join(
                [
                    '"""Generated deliverable for the requested task."""',
                    "",
                    "from __future__ import annotations",
                    "",
                    "import csv",
                    "from pathlib import Path",
                    "from typing import Iterable",
                    "",
                    "import requests",
                    "from bs4 import BeautifulSoup",
                    "",
                    'TARGET_URL = "https://example.com"',
                    'OUTPUT_CSV = Path("results.csv")',
                    "",
                    "def extract_rows(html: str) -> Iterable[dict[str, str]]:",
                    '    """Parse listing-like cards from the page."""',
                    "    soup = BeautifulSoup(html, 'html.parser')",
                    "    for card in soup.select('.restaurant, .listing, article, .card'):",
                    "        name = card.select_one('h1, h2, h3, .name, .title')",
                    "        location = card.select_one('.location, .address, address')",
                    "        yield {",
                    "            'name': name.get_text(strip=True) if name else '',",
                    "            'location': location.get_text(strip=True) if location else '',",
                    "        }",
                    "",
                    "def scrape(url: str = TARGET_URL, output_path: Path = OUTPUT_CSV) -> Path:",
                    '    """Download the page, extract rows, and save them as CSV."""',
                    "    response = requests.get(url, timeout=30)",
                    "    response.raise_for_status()",
                    "    rows = list(extract_rows(response.text))",
                    "    with output_path.open('w', newline='', encoding='utf-8') as fh:",
                    "        writer = csv.DictWriter(fh, fieldnames=['name', 'location'])",
                    "        writer.writeheader()",
                    "        writer.writerows(rows)",
                    "    return output_path",
                    "",
                    "if __name__ == '__main__':",
                    "    path = scrape()",
                    "    print(f'Saved scraped results to {path.resolve()}')",
                ]
            )
        return goal

    def _build_primary_deliverable(self, task: TaskState, output_dir: Path) -> Optional[Dict[str, str]]:
        if task.status != "completed":
            return None
        artifact = self._infer_requested_artifact(task.goal)
        extension = artifact["extension"]
        language = artifact["language"]
        filename = self._artifact_filename(task.goal, extension)
        sources = [
            self._result_step_text(task.result, "coder"),
            self._result_step_text(task.result, "fixer"),
            self._result_step_text(task.result, "architect"),
        ]
        combined = next((value for value in sources if value.strip()), "")
        content = self._extract_fenced_block(combined, language)
        if not content and language == "text" and combined.strip():
            content = combined.strip()
        if not content:
            content = self._fallback_artifact_content(task.goal, extension)
        if not content.strip():
            return None
        artifact_path = output_dir / filename
        artifact_path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return {
            "path": str(artifact_path),
            "filename": filename,
            "language": language,
            "content": content.rstrip() + "\n",
        }

    def _export_task_artifacts(self, task: TaskState) -> List[str]:
        output_dir = self._resolve_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{task.id}"
        primary_deliverable = self._build_primary_deliverable(task, output_dir)
        result_summary = self._export_result_summary(task.result, task.error)
        if primary_deliverable:
            result_summary["primary_artifact"] = primary_deliverable["path"]
        payload = {
            "id": task.id,
            "goal": task.goal,
            "workflow": task.workflow,
            "retry_of": task.retry_of,
            "status": task.status,
            "error": task.error,
            "result": result_summary,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }
        json_path = output_dir / f"{base_name}.json"
        md_path = output_dir / f"{base_name}.md"
        txt_path = output_dir / f"{base_name}.txt"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        summary = [
            f"# {task.id}",
            "",
            f"- Status: {task.status}",
            f"- Workflow: {task.workflow}",
            f"- Output Directory: {output_dir}",
        ]
        if primary_deliverable:
            summary.extend(["- Primary Artifact: " + primary_deliverable["filename"]])
        summary.extend([""])
        if primary_deliverable:
            fence = primary_deliverable["language"] if primary_deliverable["language"] != "text" else ""
            summary.extend(
                [
                    "## Output",
                    "",
                    f"```{fence}".rstrip(),
                    primary_deliverable["content"].rstrip(),
                    "```",
                ]
            )
        else:
            summary.extend(
                [
                    "## Goal",
                    "",
                    task.goal,
                ]
            )
        md_path.write_text("\n".join(summary), encoding="utf-8")
        txt_summary = [
            f"Task ID: {task.id}",
            f"Status: {task.status}",
            f"Workflow: {task.workflow}",
            f"Output Directory: {output_dir}",
        ]
        if primary_deliverable:
            txt_summary.append(f"Primary Artifact: {primary_deliverable['filename']}")
        txt_summary.extend(["", "Goal", task.goal])
        txt_path.write_text("\n".join(txt_summary), encoding="utf-8")
        artifacts = [str(json_path), str(md_path), str(txt_path)]
        if primary_deliverable:
            artifacts.append(primary_deliverable["path"])
        return artifacts

    def _save_agent_failure_registry(self) -> None:
        self._agent_failure_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._agent_failure_log_path.write_text(
            json.dumps(self._agent_failure_registry[-500:], indent=2),
            encoding="utf-8",
        )

    def _record_agent_failure(
        self,
        *,
        task: TaskState,
        event_type: str,
        agent: Optional[str],
        message: str,
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not agent:
            return
        entry = {
            "id": f"fail_{uuid.uuid4().hex[:10]}",
            "ts": time.time(),
            "task_id": task.id,
            "workflow": task.workflow,
            "agent": agent,
            "event_type": event_type,
            "message": message,
            "error": error,
            "goal_preview": task.goal[:200],
            "data": data or {},
        }
        with self._lock:
            previous = (
                self._agent_failure_registry[-1]
                if self._agent_failure_registry
                else None
            )
            duplicate = (
                previous
                and previous.get("task_id") == entry["task_id"]
                and previous.get("agent") == entry["agent"]
                and previous.get("event_type") == entry["event_type"]
                and previous.get("message") == entry["message"]
                and previous.get("error") == entry["error"]
            )
            if duplicate:
                return
            self._agent_failure_registry.append(entry)
            self._agent_failure_registry = self._agent_failure_registry[-500:]
            self._save_agent_failure_registry()

    def list_agent_failures(self, limit: int = 100) -> Dict[str, Any]:
        with self._lock:
            items = list(self._agent_failure_registry[-limit:])
        summary = {
            name: sum(1 for item in items if item.get("agent") == name)
            for name in self._AGENT_NAMES
        }
        return {"items": list(reversed(items)), "summary": summary}

    def clear_agent_failures(self) -> Dict[str, Any]:
        with self._lock:
            self._agent_failure_registry = []
            self._save_agent_failure_registry()
        return {"success": True}

    def clear_tasks(self) -> Dict[str, Any]:
        with self._lock:
            running_dashboard_tasks = [
                task.id for task in self._tasks.values() if task.status == "running"
            ]
        if running_dashboard_tasks:
            raise ValueError("Cannot clear tasks while a task is still running")

        queue_running = [
            task.id
            for task in self.task_queue.get_all()
            if task.status == TaskStatus.IN_PROGRESS
        ]
        if queue_running:
            raise ValueError("Cannot clear tasks while the queue is still running")

        self.task_queue.clear_all()
        with self._lock:
            self._tasks = {}
            self._last_task_id = None
        return {"success": True}

    def stop_agents(self) -> Dict[str, Any]:
        stopped: List[str] = []
        now = time.time()
        with self._lock:
            for task in self._tasks.values():
                if task.status not in {"queued", "running"}:
                    continue
                self._cancelled_task_ids.add(task.id)
                task.status = "cancelled"
                task.finished_at = now
                task.add_event("task", "Agents stopped by user")
                stopped.append(task.id)
                if task.queue_id:
                    queue_task = self.task_queue.get(task.queue_id)
                    if queue_task:
                        queue_task.status = TaskStatus.CANCELLED
                        queue_task.completed_at = now
                        queue_task.error = "Stopped by user"
                        queue_task.metadata = self._task_metadata(task)
                        self.task_queue.update(queue_task)

        for queue_task in self.task_queue.get_all():
            if queue_task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
                continue
            dashboard_task_id = (queue_task.metadata or {}).get("dashboard_task_id")
            if dashboard_task_id:
                with self._lock:
                    self._cancelled_task_ids.add(dashboard_task_id)
            queue_task.status = TaskStatus.CANCELLED
            queue_task.completed_at = now
            queue_task.error = "Stopped by user"
            self.task_queue.update(queue_task)
            if dashboard_task_id and dashboard_task_id not in stopped:
                stopped.append(dashboard_task_id)

        return {"success": True, "stopped": stopped}

    def list_tasks(self) -> List[TaskState]:
        tasks = [
            self._ensure_task_state(queue_task)
            for queue_task in self.task_queue.get_all()
        ]
        return tasks[:50]

    def get_task(self, task_id: str) -> TaskState:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task

        for queue_task in self.task_queue.get_all():
            hydrated = self._ensure_task_state(queue_task)
            if hydrated.id == task_id or hydrated.queue_id == task_id:
                return hydrated
        raise KeyError(task_id)

    def queue_stats(self) -> Dict[str, int]:
        stats = self.task_queue.get_stats()
        return {
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "queued": stats.get("pending", 0),
            "running": stats.get("in_progress", 0),
            "in_progress": stats.get("in_progress", 0),
            "completed": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
            "blocked": stats.get("blocked", 0),
            "cancelled": stats.get("cancelled", 0),
        }

    def create_task(
        self,
        goal: str,
        workflow: str,
        retry_of: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        dependencies: Optional[List[str]] = None,
        source: str = "dashboard",
    ) -> TaskState:
        task_id = f"task_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        queue_task = self.task_queue.add(
            description=goal,
            priority=priority,
            dependencies=dependencies or [],
            metadata={
                "source": source,
                "workflow": workflow,
                "retry_of": retry_of,
                "dashboard_task_id": task_id,
                "goal": goal,
                "priority": self._priority_to_name(priority),
                "dependencies": list(dependencies or []),
            },
        )
        task = TaskState(
            id=task_id,
            goal=goal,
            workflow=workflow,
            retry_of=retry_of,
            queue_id=queue_task.id,
            priority=self._priority_to_name(priority),
            dependencies=list(dependencies or []),
            source=source,
        )
        task.add_event("task", "Task created")
        if retry_of:
            task.add_event(
                "retry",
                f"Pull again created from {retry_of}",
                data={"source_task_id": retry_of},
            )
        with self._lock:
            self._tasks[task_id] = task
            self._last_task_id = task_id
        self._sync_queue_task(task)
        return task

    def retry_task(self, task_id: str) -> TaskState:
        source = self.get_task(task_id)
        if source.status == "running":
            raise ValueError("Running tasks cannot be pulled again")
        retry_task = self.create_task(
            source.goal,
            source.workflow,
            retry_of=source.id,
            priority=self._priority_from_name(source.priority),
            dependencies=list(source.dependencies),
            source=source.source,
        )
        source.add_event(
            "retry",
            f"Pull again requested -> {retry_task.id}",
            data={"retry_task_id": retry_task.id},
        )
        self._sync_queue_task(source)
        if retry_task.workflow != "manual":
            self.run_task_async(retry_task)
        else:
            retry_task.add_event("task", "Manual retry queued (not started)")
            self._sync_queue_task(retry_task)
        return retry_task

    def run_task_async(self, task: TaskState) -> None:
        def _run():
            with self._lock:
                cancelled_before_start = (
                    task.id in self._cancelled_task_ids or task.status == "cancelled"
                )
                if cancelled_before_start:
                    task.status = "cancelled"
                    task.finished_at = task.finished_at or time.time()
            if cancelled_before_start:
                self._sync_queue_task(task)
                return
            if task.queue_id:
                self.task_queue.mark_started(task.queue_id)
            task.started_at = time.time()
            task.status = "running"
            task.add_event("orchestrator", "Execution started")
            self._sync_queue_task(task)
            try:
                workflow = (
                    None if task.workflow in {"auto", "manual"} else task.workflow
                )

                def on_event(evt: Dict[str, Any]) -> None:
                    with self._lock:
                        if task.id in self._cancelled_task_ids or task.status == "cancelled":
                            return
                    et = evt.get("type", "event")
                    msg = evt.get("message", "")
                    agent = evt.get("agent")
                    extra = {
                        k: v
                        for k, v in evt.items()
                        if k not in {"ts", "type", "message", "agent"}
                    }
                    task.add_event(et, msg, agent=agent, data=extra)
                    if et == "routing":
                        task.routing = extra
                    if et == "agent_fail":
                        self._record_agent_failure(
                            task=task,
                            event_type=et,
                            agent=agent,
                            message=msg,
                            error=extra.get("error"),
                            data=extra,
                        )
                    if (
                        et == "heal_step"
                        and agent == "fixer"
                        and "failed" in msg.lower()
                    ):
                        self._record_agent_failure(
                            task=task,
                            event_type=et,
                            agent=agent,
                            message=msg,
                            error=extra.get("error"),
                            data=extra,
                        )
                    self._sync_queue_task(task)

                orch = Orchestrator(
                    self.config,
                    session_id=self.tool_orchestrator.session_id,
                    event_callback=on_event,
                )
                result = orch.execute_goal(task.goal, workflow=workflow)
                with self._lock:
                    stopped = task.id in self._cancelled_task_ids or task.status == "cancelled"
                    if stopped:
                        task.status = "cancelled"
                        task.finished_at = task.finished_at or time.time()
                        task.add_event("task", "Stopped task ignored late agent result")
                if stopped:
                    self._sync_queue_task(task)
                    return
                task.finished_at = time.time()
                if result.success:
                    task.status = "completed"
                    task.result = {
                        "success": True,
                        "message": result.message,
                        "data": result.data,
                        "agent_name": result.agent_name,
                        "timestamp": result.timestamp,
                    }
                    task.add_event("orchestrator", "Execution completed")
                else:
                    task.status = "failed"
                    task.error = result.error or "Unknown error"
                    task.result = {
                        "success": False,
                        "message": result.message,
                        "error": task.error,
                        "agent_name": result.agent_name,
                        "timestamp": result.timestamp,
                    }
                    task.add_event("error", task.error, agent=result.agent_name)
                    self._record_agent_failure(
                        task=task,
                        event_type="result_fail",
                        agent=result.agent_name,
                        message=result.message,
                        error=task.error,
                    )
                exported = self._export_task_artifacts(task)
                if task.result is None:
                    task.result = {}
                task.result["artifacts"] = exported
                task.add_event("output", f"Artifacts saved to {exported[0]}")
                self._sync_queue_task(task)
            except Exception as e:
                task.finished_at = time.time()
                task.status = "failed"
                task.error = str(e)
                task.add_event("error", task.error)
                self._sync_queue_task(task)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def cancel_task(self, task: TaskState) -> None:
        if task.status != "queued":
            raise ValueError("Only queued tasks can be cancelled")
        task.status = "cancelled"
        task.finished_at = time.time()
        task.add_event("task", "Task cancelled")
        if task.queue_id and not self.task_queue.cancel_task(task.queue_id):
            raise ValueError("Only queued tasks can be cancelled")
        self._sync_queue_task(task)

    def _derive_agent_activity(self, task: TaskState) -> Dict[str, bool]:
        activity = {name: False for name in self._AGENT_NAMES}
        if task.status != "running":
            return activity

        for event in task.events:
            event_type = event.type or ""
            agent_name = event.agent

            if event_type == "heal_try":
                if agent_name in activity:
                    activity[agent_name] = False
                continue

            if event_type == "heal_handoff" and agent_name in activity:
                activity[agent_name] = True
                activity["fixer"] = False
                continue

            if (
                event_type in {"heal_review_ok", "heal_review_fail"}
                and agent_name in activity
            ):
                activity[agent_name] = False
                continue

            if event_type == "heal_fix_start":
                activity["fixer"] = True
                continue

            if event_type == "heal_step":
                activity["fixer"] = False
                continue

            if agent_name not in activity:
                continue

            if event_type == "agent_start":
                activity[agent_name] = True
            elif event_type in {"agent_ok", "agent_fail", "heal_ok"}:
                activity[agent_name] = False

        return activity

    def _get_agent_activity(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())

        activity = {
            name: {"working": False, "task_id": None} for name in self._AGENT_NAMES
        }
        for task in tasks:
            per_task = self._derive_agent_activity(task)
            for name, working in per_task.items():
                if working and not activity[name]["working"]:
                    activity[name] = {"working": True, "task_id": task.id}

        return activity

    def get_status(self) -> Dict[str, Any]:
        base = self.tool_orchestrator.get_status()
        qs = self.queue_stats()
        base["queue_stats"] = qs
        base["agent_activity"] = self._get_agent_activity()
        base["output_destination"] = self.get_output_dir_settings()
        base["warmup"] = self._warmup_status
        base["running"] = bool(base.get("running")) or (qs.get("running", 0) > 0)
        base["last_task_id"] = self._last_task_id
        try:
            if self._last_task_id:
                t = self.get_task(self._last_task_id)
                base["last_task"] = {
                    "id": t.id,
                    "status": t.status,
                    "workflow": t.workflow,
                    "routing": t.routing,
                }
        except Exception:
            pass
        try:
            inf = self.inference_queue.list(limit=200)
            base["inference_queue"] = {
                "pending": sum(1 for it in inf if it.status == "queued"),
                "running": sum(1 for it in inf if it.status == "running"),
                "completed": sum(1 for it in inf if it.status == "completed"),
                "failed": sum(1 for it in inf if it.status == "failed"),
                "cancelled": sum(1 for it in inf if it.status == "cancelled"),
            }
        except Exception:
            base["inference_queue"] = {
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
            }
        return base

    def _workspace_root(self) -> str:
        return str(Path(self.config.workspace_root).resolve())

    def run_shell_safe(self, command: str, timeout_s: int = 60) -> Dict[str, Any]:
        """
        Run a single shell command with basic sanitization.
        - Disallow pipes/redirection/chaining to reduce foot-guns.
        - Default to `cmd.exe`/POSIX shell behavior via `shell=True` on Windows,
          but block metacharacters so users can't chain commands.
        """
        cmd = (command or "").strip()
        if not cmd:
            return {"success": False, "error": "Empty command"}
        if len(cmd) > 2000:
            return {"success": False, "error": "Command too long"}
        if any(ch in cmd for ch in ["\r", "\n", "|", "&", ";", ">", "<"]):
            return {
                "success": False,
                "error": "Command contains forbidden shell metacharacters (| & ; > < or newlines)",
            }

        # Basic destructive-command guardrail.
        lowered = cmd.strip().lower()
        blocked_prefixes = (
            "rm ",
            "del ",
            "erase ",
            "rmdir ",
            "rd ",
            "format ",
            "shutdown ",
            "reboot ",
            "poweroff ",
            "remove-item ",
        )
        if any(lowered.startswith(p) for p in blocked_prefixes):
            return {
                "success": False,
                "error": "Destructive commands are blocked in the dashboard shell tool",
            }

        allowed_prefixes = [
            str(item).strip().lower()
            for item in (getattr(self.config, "allowed_commands", []) or [])
            if str(item).strip()
        ]
        blocked_phrases = [
            str(item).strip().lower()
            for item in (getattr(self.config, "blocked_commands", []) or [])
            if str(item).strip()
        ]

        if any(lowered.startswith(item) for item in blocked_phrases):
            return {
                "success": False,
                "error": "Command is blocked by the dashboard safe-command policy",
            }

        if allowed_prefixes and not any(
            lowered.startswith(item) for item in allowed_prefixes
        ):
            return {
                "success": False,
                "error": "Command is not in the dashboard allow-list",
                "allowed_commands": allowed_prefixes,
            }

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self._workspace_root(),
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": cmd,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout_s}s",
                "timeout": True,
                "command": cmd,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "command": cmd}

    def run_python_safe(self, code: str, timeout_s: int = 30) -> Dict[str, Any]:
        """
        Run Python in a subprocess (so user snippets can't crash the web server process).
        """
        src = (code or "").strip()
        if not src:
            return {"success": False, "error": "Empty code"}
        if len(src) > 50_000:
            return {"success": False, "error": "Code too long"}

        env = os.environ.copy()
        # Let snippets import the project package by default (agent_joko is one level above workspace_root).
        env["PYTHONPATH"] = os.pathsep.join(
            [str(_here().parent.parent.resolve()), env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)

        workspace_root = Path(self._workspace_root()).resolve()
        output_root = self._resolve_output_dir()
        execution_target: Optional[Path] = None
        candidate = Path(src)
        candidate_paths = []
        if candidate.is_absolute():
            candidate_paths.append(candidate)
        else:
            candidate_paths.append(workspace_root / candidate)
            candidate_paths.append(output_root / candidate)

        for maybe_path in candidate_paths:
            resolved = maybe_path.resolve()
            if resolved.exists() and resolved.is_file() and resolved.suffix.lower() == ".py":
                execution_target = resolved
                break

        try:
            if execution_target is not None:
                result = subprocess.run(
                    [sys.executable, str(execution_target)],
                    cwd=str(execution_target.parent),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-c", src],
                    cwd=self._workspace_root(),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "executed_file": str(execution_target) if execution_target else None,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Python timed out after {timeout_s}s",
                "timeout": True,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _resolve_dashboard_dir(subdir: str) -> str:
    pkg_dir = _here()
    candidate = pkg_dir / subdir
    if candidate.is_dir():
        return str(candidate.resolve())
    for parent in [Path("/app/src/agent_joko/dashboard"), Path.cwd() / "src" / "agent_joko" / "dashboard"]:
        alt = parent / subdir
        if alt.is_dir():
            return str(alt.resolve())
    return str(candidate.resolve())


def create_app(config: Optional[Config] = None) -> FastAPI:
    app = FastAPI(title="agent_joko Dashboard", version="1.0.0")
    state = DashboardState(config=config)

    templates = Jinja2Templates(directory=_resolve_dashboard_dir("templates"))
    app.mount(
        "/static",
        StaticFiles(directory=_resolve_dashboard_dir("static")),
        name="static",
    )

    @app.middleware("http")
    async def ignore_pinokio_probe(request: Request, call_next):
        # Pinokio's embedded browser may probe the root URL with a non-standard
        # FOO method while testing connectivity. Swallow it to avoid noisy 405 logs.
        if request.method == "FOO" and request.url.path == "/":
            return Response(status_code=204)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        static_root = Path(_resolve_dashboard_dir("static"))
        asset_version = max(
            (static_root / "app.css").stat().st_mtime_ns,
            (static_root / "app.js").stat().st_mtime_ns,
        )
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "ollama_host": state.config.ollama_host,
                "asset_version": asset_version,
            },
        )

    @app.get("/api/status")
    def api_status():
        return state.get_status()

    @app.get("/api/settings/output_dir")
    def api_output_dir_get():
        return state.get_output_dir_settings()

    @app.post("/api/settings/output_dir")
    def api_output_dir_set(req: OutputDirectoryRequest):
        try:
            return state.set_output_dir(req.path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/settings/output-dir")
    def api_output_dir_get_compat_dash():
        return state.get_output_dir_settings()

    @app.post("/api/settings/output-dir")
    def api_output_dir_set_compat_dash(req: OutputDirectoryRequest):
        try:
            return state.set_output_dir(req.path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/output_dir")
    def api_output_dir_get_compat_legacy():
        return state.get_output_dir_settings()

    @app.post("/api/output_dir")
    def api_output_dir_set_compat_legacy(req: OutputDirectoryRequest):
        try:
            return state.set_output_dir(req.path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/agent_failures")
    def api_agent_failures(limit: int = 100):
        return state.list_agent_failures(limit=limit)

    @app.post("/api/agent_failures/clear")
    def api_agent_failures_clear():
        return state.clear_agent_failures()

    @app.get("/api/settings/chat_model")
    def api_chat_model_get():
        try:
            return state.get_chat_model_settings()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.post("/api/settings/chat_model")
    def api_chat_model_set(req: ChatModelRequest):
        try:
            return state.set_chat_model(req.model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/api/ollama/models")
    def api_ollama_models():
        try:
            settings = state.get_chat_model_settings()
            return {
                "ok": True,
                "host": state.ollama_client.host,
                "models": settings["available_models"],
                "primary_model": settings["model"],
                "fallback_models": settings["fallback_models"],
            }
        except Exception as e:
            return {
                "ok": False,
                "host": state.ollama_client.host,
                "error": str(e),
                "models": [],
            }

    @app.get("/api/inference_queue")
    def api_inference_queue(limit: int = 100):
        items = state.inference_queue.list(limit=limit)
        return {"items": [it.to_dict() for it in items]}

    @app.get("/api/inference_queue/{item_id}")
    def api_inference_queue_item(item_id: str):
        try:
            it = state.inference_queue.get(item_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Queue item not found")
        return it.to_dict()

    @app.post("/api/inference_queue/{item_id}/cancel")
    def api_inference_queue_cancel(item_id: str):
        try:
            state.inference_queue.cancel(item_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Queue item not found")
        return {"success": True}

    @app.post("/api/chat/stream")
    def api_chat_stream(req: ChatRequest):
        model = req.model or getattr(
            state.config, "ollama_primary_model", "ollama:llama3.2:latest"
        )
        fallback_models = getattr(state.config, "ollama_fallback_models", []) or []
        messages = req.messages
        if not messages:
            prompt = (req.prompt or "").strip()
            if not prompt:
                raise HTTPException(
                    status_code=400, detail="prompt or messages required"
                )
            messages = [{"role": "user", "content": prompt}]

        def gen() -> Iterable[bytes]:
            # If Ollama is down and offline queueing is enabled, enqueue and return.
            health = state.ollama_client.health()
            if not health.get("ok") and getattr(
                state.config, "offline_queue_requests", True
            ):
                it = state.inference_queue.add_chat(
                    messages=messages or [],
                    model=model,
                    fallback_models=fallback_models,
                    options={},
                )
                payload = {"type": "queued", "id": it.id, "status": it.status}
                yield (json.dumps(payload) + "\n").encode("utf-8")
                return

            start = time.time()
            yield (
                json.dumps({"type": "start", "model": model, "ts": time.time()}) + "\n"
            ).encode("utf-8")
            try:
                for evt in state.ollama_client.chat_stream(
                    messages=messages or [],
                    model=model,
                    fallback_models=fallback_models,
                    options={
                        "temperature": getattr(state.config, "ollama_temperature", 0.7),
                        "num_ctx": getattr(
                            state.config, "ollama_max_context_tokens", 2048
                        ),
                    },
                ):
                    if evt.get("type") == "done":
                        evt["elapsed_s"] = evt.get("elapsed_s") or (time.time() - start)
                    yield (json.dumps(evt) + "\n").encode("utf-8")
            except OllamaError as e:
                yield (json.dumps({"type": "error", "error": str(e)}) + "\n").encode(
                    "utf-8"
                )

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/api/tasks")
    def api_tasks():
        tasks = state.list_tasks()
        return {"tasks": [state._serialize_task_summary(t) for t in tasks]}

    @app.post("/api/tasks/clear")
    def api_tasks_clear():
        try:
            return state.clear_tasks()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/agents/stop")
    def api_agents_stop():
        return state.stop_agents()

    @app.get("/api/tasks/{task_id}")
    def api_task(task_id: str):
        try:
            t = state.get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found")
        return state._serialize_task_detail(t)

    @app.get("/api/activity/recent")
    def api_activity_recent(count: int = 50, task_id: Optional[str] = None):
        """
        Convenience endpoint for UI polling.
        """
        tid = task_id or state._last_task_id
        if not tid:
            return {"task_id": None, "events": []}
        try:
            t = state.get_task(tid)
        except KeyError:
            return {"task_id": None, "events": []}
        return {"task_id": t.id, "events": [e.__dict__ for e in t.events[-count:]]}

    @app.post("/api/execute")
    def api_execute(req: ExecuteRequest):
        task = state.create_task(req.goal, req.workflow)
        if req.workflow != "manual":
            state.run_task_async(task)
        else:
            task.add_event("task", "Manual task queued (not started)")
        return {"task_id": task.id}

    @app.post("/api/tasks/{task_id}/start")
    def api_task_start(task_id: str):
        try:
            t = state.get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found")
        if t.status != "queued":
            raise HTTPException(status_code=400, detail="Task is not queued")
        if t.queue_id and not state.task_queue.dependencies_satisfied(t.queue_id):
            raise HTTPException(
                status_code=400, detail="Task dependencies are not complete"
            )
        state.run_task_async(t)
        return {"success": True}

    @app.post("/api/tasks/{task_id}/cancel")
    def api_task_cancel(task_id: str):
        try:
            t = state.get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found")
        try:
            state.cancel_task(t)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"success": True}

    @app.post("/api/tasks/{task_id}/retry")
    def api_task_retry(task_id: str):
        try:
            retry_task = state.retry_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "success": True,
            "task_id": retry_task.id,
            "workflow": retry_task.workflow,
        }

    @app.post("/api/tools/shell")
    def api_shell(req: ShellRequest):
        return state.run_shell_safe(req.command)

    @app.post("/api/tools/python")
    def api_python(req: PythonRequest):
        return state.run_python_safe(req.code)

    @app.get("/api/files/list")
    def api_files_list(
        path: str = ".", recursive: bool = False, include_dirs: bool = True
    ):
        return state.tool_orchestrator.file_ops.list_files(
            path=path,
            recursive=recursive,
            include_dirs=include_dirs,
        )

    @app.get("/api/files/read")
    def api_files_read(path: str, limit: int = 200, offset: int = 0):
        return state.tool_orchestrator.file_ops.read_file(
            path=path, limit=limit, offset=offset
        )

    @app.post("/api/files/write")
    def api_files_write(req: WriteFileRequest):
        return state.tool_orchestrator.file_ops.write_file(
            path=req.path, content=req.content
        )

    @app.get("/api/git/status")
    def api_git_status(short: bool = False):
        return state.tool_orchestrator.git_ops.status(short=short)

    @app.post("/api/git/commit")
    def api_git_commit(req: GitCommitRequest):
        return state.tool_orchestrator.git_ops.auto_commit(req.message)

    @app.get("/api/memory/recent")
    def api_memory_recent(count: int = 20, entry_type: Optional[str] = None):
        entries = state.tool_orchestrator.memory_store.get_recent(
            count=count, entry_type=entry_type
        )
        return {"entries": [e.to_dict() for e in entries]}

    @app.get("/api/memory/search")
    def api_memory_search(q: str, max_results: int = 20):
        entries = state.tool_orchestrator.memory_store.search(
            q, max_results=max_results
        )
        return {"entries": [e.to_dict() for e in entries]}

    return app


def _here():
    from pathlib import Path

    return Path(__file__).parent
