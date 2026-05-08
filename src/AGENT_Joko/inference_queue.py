"""
Offline-first inference queue for Ollama requests.

This is intentionally small and JSON-backed:
- Keeps state inside the project folder (Pinokio-friendly).
- Works even when Ollama is temporarily unavailable.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class InferenceItem:
    id: str
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    status: str = "queued"  # queued|running|completed|failed|cancelled
    kind: str = "chat"
    model: str = ""
    fallback_models: List[str] = field(default_factory=list)
    messages: List[Dict[str, str]] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InferenceItem":
        return cls(**d)


class InferenceQueue:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path:
            self.storage_path = Path(storage_path).expanduser()
        else:
            self.storage_path = Path.cwd() / ".devin_agent" / "inference_queue.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._items: Dict[str, InferenceItem] = {}
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8", errors="replace") or "{}")
            items = data.get("items", []) or []
            self._items = {i["id"]: InferenceItem.from_dict(i) for i in items if isinstance(i, dict) and i.get("id")}
        except Exception:
            self._items = {}

    def _save(self) -> None:
        data = {"saved_at": time.time(), "items": [it.to_dict() for it in self.list(limit=500)]}
        self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        fallback_models: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> InferenceItem:
        item = InferenceItem(
            id=f"inf_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
            kind="chat",
            model=model or "",
            fallback_models=list(fallback_models or []),
            messages=list(messages or []),
            options=dict(options or {}),
        )
        self._items[item.id] = item
        self._save()
        return item

    def list(self, limit: int = 100) -> List[InferenceItem]:
        items = list(self._items.values())
        items.sort(key=lambda it: it.created_at, reverse=True)
        return items[: max(1, int(limit))]

    def get(self, item_id: str) -> InferenceItem:
        if item_id not in self._items:
            raise KeyError(item_id)
        return self._items[item_id]

    def cancel(self, item_id: str) -> None:
        it = self.get(item_id)
        if it.status in {"completed", "failed"}:
            return
        it.status = "cancelled"
        it.finished_at = time.time()
        self._save()

    def next_pending(self) -> Optional[InferenceItem]:
        pending = [it for it in self._items.values() if it.status == "queued"]
        if not pending:
            return None
        pending.sort(key=lambda it: it.created_at)
        return pending[0]

    def mark_running(self, item_id: str) -> None:
        it = self.get(item_id)
        it.status = "running"
        it.started_at = time.time()
        it.attempts += 1
        self._save()

    def mark_done(self, item_id: str, result: Dict[str, Any]) -> None:
        it = self.get(item_id)
        it.status = "completed"
        it.finished_at = time.time()
        it.result = result
        it.error = None
        self._save()

    def mark_failed(self, item_id: str, error: str) -> None:
        it = self.get(item_id)
        it.status = "failed"
        it.finished_at = time.time()
        it.error = error
        self._save()

    def retry_if_possible(self, item_id: str, error: str) -> None:
        it = self.get(item_id)
        it.error = error
        it.finished_at = None
        it.started_at = None
        if it.attempts >= it.max_attempts:
            it.status = "failed"
            it.finished_at = time.time()
        else:
            it.status = "queued"
        self._save()

