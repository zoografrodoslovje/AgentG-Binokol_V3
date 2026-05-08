from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from AGENT_Joko.config import Config, LEGACY_DEFAULT_MODELS, LEGACY_FALLBACK_MODELS
from AGENT_Joko.ollama_client import OllamaClient, OllamaError


@dataclass
class _Resp:
    status_code: int = 200
    payload: Optional[Dict[str, Any]] = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return dict(self.payload or {})


class _FakeSession:
    def __init__(self):
        self.post_calls = 0
        self.get_calls = 0
        self.fail_model: Optional[str] = None
        self.fail_models: set[str] = set()
        self.last_headers: Optional[Dict[str, Any]] = None

    def get(self, url: str, timeout: int = 5):
        self.get_calls += 1
        return _Resp(payload={"models": [{"name": "a"}, {"name": "b"}]})

    def post(
        self,
        url: str,
        json: Dict[str, Any],
        timeout: int = 60,
        stream: bool = False,
        headers: Optional[Dict[str, Any]] = None,
    ):
        self.post_calls += 1
        self.last_headers = headers
        if self.fail_model and json.get("model") == self.fail_model:
            raise RuntimeError("boom")
        if json.get("model") in self.fail_models:
            raise RuntimeError("boom")
        # /api/chat non-stream response
        if "chat/completions" in url:
            return _Resp(
                payload={
                    "choices": [{"message": {"content": f"ok:{json.get('model')}"}}],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )
        return _Resp(
            payload={
                "message": {"content": f"ok:{json.get('model')}"},
                "done": True,
                "eval_count": 3,
            }
        )


def test_list_models() -> None:
    sess = _FakeSession()
    c = OllamaClient(session=sess)
    assert c.list_models() == ["ollama:a", "ollama:b"]


def test_chat_caches_identical_request() -> None:
    sess = _FakeSession()
    c = OllamaClient(
        session=sess, enable_caching=True, cache_ttl_seconds=60, cache_max_entries=10
    )
    r1 = c.chat(messages=[{"role": "user", "content": "hi"}], model="ollama:m1")
    r2 = c.chat(messages=[{"role": "user", "content": "hi"}], model="ollama:m1")
    assert r1["content"] == r2["content"]
    assert sess.post_calls == 1


def test_chat_fallback_model() -> None:
    sess = _FakeSession()
    sess.fail_model = "bad"
    c = OllamaClient(session=sess, enable_caching=False)
    res = c.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="ollama:bad",
        fallback_models=["ollama:good"],
    )
    assert res["content"] == "ok:good"


def test_chat_raises_if_all_models_fail() -> None:
    sess = _FakeSession()
    sess.fail_models = {"bad", "also-bad"}
    c = OllamaClient(session=sess, enable_caching=False)
    with pytest.raises(OllamaError) as exc:
        c.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="ollama:bad",
            fallback_models=["ollama:also-bad"],
        )
    assert "bad" in str(exc.value)
    assert "also-bad" in str(exc.value)


def test_config_migrates_legacy_fallback_models() -> None:
    cfg = Config.from_dict({"ollama_fallback_models": list(LEGACY_FALLBACK_MODELS)})
    assert cfg.ollama_fallback_models == [
        "ollama:mistral:latest",
        "ollama:llama3.2:latest",
        "openrouter:openrouter/free",
    ]


def test_config_migrates_legacy_default_scheme() -> None:
    cfg = Config.from_dict(
        {
            "models": dict(LEGACY_DEFAULT_MODELS),
            "ollama_primary_model": "ollama:llama3.1:8b",
            "ollama_fallback_models": [
                "ollama:mistral:latest",
                "openrouter:openrouter/free",
            ],
        }
    )

    assert cfg.models == {
        "architect": "ollama:llama3.2:latest",
        "coder": "ollama:llama3.2:latest",
        "tester": "ollama:mistral:latest",
        "fixer": "ollama:mistral:latest",
        "debator": "ollama:mistral:latest",
        "fallback": "ollama:mistral:latest",
    }
    assert cfg.ollama_primary_model == "ollama:llama3.2:latest"


def test_openrouter_provider_uses_bearer_auth() -> None:
    sess = _FakeSession()
    c = OllamaClient(
        session=sess,
        enable_caching=False,
        openrouter_api_key="sk-or-v1-test",
        catalog_models=["openrouter:openrouter/free"],
    )
    res = c.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="openrouter:openrouter/free",
        fallback_models=[],
    )
    assert res["model"] == "openrouter:openrouter/free"
    assert sess.last_headers == {
        "Authorization": "Bearer sk-or-v1-test",
        "Content-Type": "application/json",
    }
