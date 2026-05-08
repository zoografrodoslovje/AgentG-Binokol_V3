"""
Ollama client utilities.

Goals:
- Keep dependencies lightweight (requests-only).
- Support streaming (NDJSON) for better UX.
- Provide basic response caching and model fallback.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

import requests


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaUsage:
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None


class _TTLCache:
    def __init__(self, max_entries: int = 200, ttl_seconds: int = 300):
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._data: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        item = self._data.get(key)
        if not item:
            return None
        ts, value = item
        if (now - ts) > self._ttl_seconds:
            try:
                del self._data[key]
            except KeyError:
                pass
            return None
        # LRU touch
        self._data.move_to_end(key, last=True)
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key, last=True)
        while len(self._data) > self._max_entries:
            self._data.popitem(last=False)


class OllamaClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout_seconds: int = 60,
        max_context_tokens: int = 2048,
        temperature: float = 0.7,
        idle_keep_alive_minutes: int = 5,
        enable_caching: bool = True,
        cache_ttl_seconds: int = 300,
        cache_max_entries: int = 200,
        groq_api_key: Optional[str] = None,
        groq_base_url: str = "https://api.groq.com/openai/v1",
        openai_api_key: Optional[str] = None,
        openai_base_url: str = "https://api.openai.com/v1",
        openrouter_api_key: Optional[str] = None,
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        catalog_models: Optional[List[str]] = None,
        session: Optional[requests.Session] = None,
    ):
        self.host = host.rstrip("/")
        self.timeout_seconds = int(timeout_seconds)
        self.max_context_tokens = int(max_context_tokens)
        self.temperature = float(temperature)
        self.idle_keep_alive_minutes = int(idle_keep_alive_minutes)
        self._session = session or requests.Session()
        self.groq_api_key = groq_api_key
        self.groq_base_url = groq_base_url.rstrip("/")
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url.rstrip("/")
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_base_url = openrouter_base_url.rstrip("/")
        self.catalog_models = list(catalog_models or [])
        self._cache: Optional[_TTLCache] = None
        if enable_caching:
            self._cache = _TTLCache(max_entries=cache_max_entries, ttl_seconds=cache_ttl_seconds)

    def list_models(self) -> List[str]:
        models: List[str] = []
        url = f"{self.host}/api/tags"
        try:
            resp = self._session.get(url, timeout=min(5, self.timeout_seconds))
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("models", []) or []:
                name = m.get("name") or m.get("model") or ""
                if name:
                    models.append(f"ollama:{name}")
        except Exception:
            pass

        seen = set(models)
        for model_name in self.catalog_models:
            if model_name and model_name not in seen:
                models.append(model_name)
                seen.add(model_name)

        if not models:
            raise OllamaError("Failed to list models: no providers responded")
        return models

    def health(self) -> Dict[str, Any]:
        local_ok = False
        local_error = None
        local_models: List[str] = []
        try:
            local_models = [name for name in self.list_models() if name.startswith("ollama:")]
            local_ok = bool(local_models)
        except Exception as e:
            local_error = str(e)
        remote_ready = bool(self.groq_api_key or self.openai_api_key or self.openrouter_api_key)
        return {
            "ok": local_ok or remote_ready,
            "host": self.host,
            "models": local_models,
            "local_ok": local_ok,
            "local_error": local_error,
            "remote_ready": remote_ready,
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        fallback_models: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Non-streaming chat call. Returns dict with {content, model, usage, raw}."""
        models_to_try = [model] + [m for m in (fallback_models or []) if m and m != model]
        errors: List[str] = []
        for m in models_to_try:
            try:
                provider, actual_model = self._parse_model_ref(m)
                return self._chat_nonstream(
                    provider=provider,
                    messages=messages,
                    model=actual_model,
                    options=options,
                    system=system,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as e:
                errors.append(str(e))
                continue
        raise OllamaError("; ".join(errors) if errors else "Chat failed")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        fallback_models: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Streaming chat call (NDJSON from Ollama).

        Yields dict items:
        - {"type":"delta","content":"..."}
        - {"type":"done","content":"<full>","usage":{...},"model":"...","raw":{...}}
        """
        models_to_try = [model] + [m for m in (fallback_models or []) if m and m != model]
        errors: List[str] = []
        for m in models_to_try:
            try:
                provider, actual_model = self._parse_model_ref(m)
                yield from self._chat_stream_impl(
                    provider=provider,
                    messages=messages,
                    model=actual_model,
                    options=options,
                    system=system,
                    timeout_seconds=timeout_seconds,
                )
                return
            except Exception as e:
                errors.append(str(e))
                continue
        raise OllamaError("; ".join(errors) if errors else "Chat stream failed")

    def generate(
        self,
        prompt: str,
        model: str,
        fallback_models: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Non-streaming generate call. Returns dict with {content, model, usage, raw}."""
        models_to_try = [model] + [m for m in (fallback_models or []) if m and m != model]
        errors: List[str] = []
        for m in models_to_try:
            try:
                provider, actual_model = self._parse_model_ref(m)
                return self._generate_nonstream(
                    provider=provider,
                    prompt=prompt,
                    model=actual_model,
                    options=options,
                    system=system,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as e:
                errors.append(str(e))
                continue
        raise OllamaError("; ".join(errors) if errors else "Generate failed")

    def generate_stream(
        self,
        prompt: str,
        model: str,
        fallback_models: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        system: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Streaming generate call. Same yield protocol as chat_stream."""
        models_to_try = [model] + [m for m in (fallback_models or []) if m and m != model]
        errors: List[str] = []
        for m in models_to_try:
            try:
                provider, actual_model = self._parse_model_ref(m)
                yield from self._generate_stream_impl(
                    provider=provider,
                    prompt=prompt,
                    model=actual_model,
                    options=options,
                    system=system,
                    timeout_seconds=timeout_seconds,
                )
                return
            except Exception as e:
                errors.append(str(e))
                continue
        raise OllamaError("; ".join(errors) if errors else "Generate stream failed")

    def _chat_nonstream(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ):
        if provider != "ollama":
            return self._chat_nonstream_openai_compat(
                provider=provider,
                messages=messages,
                model=model,
                options=options,
                system=system,
                timeout_seconds=timeout_seconds,
            )
        url = f"{self.host}/api/chat"
        merged_options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self.max_context_tokens,
        }
        if options:
            merged_options.update(options)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": merged_options,
            # Keep the model warm, but allow Ollama to unload when idle.
            "keep_alive": f"{max(1, self.idle_keep_alive_minutes)}m",
        }
        if system:
            payload["system"] = system

        cache_key = None
        if self._cache:
            cache_key = self._cache_key(url, payload)
            hit = self._cache.get(cache_key)
            if hit is not None:
                return hit

        try:
            resp = self._session.post(url, json=payload, timeout=timeout_seconds or self.timeout_seconds)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            raise OllamaError(f"Ollama chat failed ({model}): {e}") from e

        content = (((raw.get("message") or {}) or {}).get("content")) or ""
        usage = self._usage_from_raw(raw)
        result = {"content": content, "model": model, "usage": usage.__dict__, "raw": raw}
        if self._cache and cache_key:
            self._cache.set(cache_key, result)
        return result

    def _chat_stream_impl(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ):
        if provider != "ollama":
            yield from self._chat_stream_openai_compat(
                provider=provider,
                messages=messages,
                model=model,
                options=options,
                system=system,
                timeout_seconds=timeout_seconds,
            )
            return
        url = f"{self.host}/api/chat"
        merged_options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self.max_context_tokens,
        }
        if options:
            merged_options.update(options)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": merged_options,
            "keep_alive": f"{max(1, self.idle_keep_alive_minutes)}m",
        }
        if system:
            payload["system"] = system

        start = time.time()
        full = []
        last_raw: Dict[str, Any] = {}
        try:
            with self._session.post(url, json=payload, timeout=timeout_seconds or self.timeout_seconds, stream=True) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    last_raw = obj
                    msg = obj.get("message") or {}
                    delta = msg.get("content") or ""
                    if delta:
                        full.append(delta)
                        yield {"type": "delta", "content": delta}
                    if obj.get("done"):
                        usage = self._usage_from_raw(obj)
                        content = "".join(full)
                        yield {
                            "type": "done",
                            "content": content,
                            "model": model,
                            "usage": usage.__dict__,
                            "elapsed_s": time.time() - start,
                            "raw": obj,
                        }
                        return
        except Exception as e:
            raise OllamaError(f"Ollama chat stream failed ({model}): {e}") from e

        # If stream ends without done, still return what we have.
        usage = self._usage_from_raw(last_raw)
        yield {
            "type": "done",
            "content": "".join(full),
            "model": model,
            "usage": usage.__dict__,
            "elapsed_s": time.time() - start,
            "raw": last_raw,
        }

    def _generate_nonstream(
        self,
        provider: str,
        prompt: str,
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ):
        if provider != "ollama":
            return self._chat_nonstream_openai_compat(
                provider=provider,
                messages=[{"role": "user", "content": prompt}],
                model=model,
                options=options,
                system=system,
                timeout_seconds=timeout_seconds,
            )
        url = f"{self.host}/api/generate"
        merged_options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self.max_context_tokens,
        }
        if options:
            merged_options.update(options)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": merged_options,
            "keep_alive": f"{max(1, self.idle_keep_alive_minutes)}m",
        }
        if system:
            payload["system"] = system

        cache_key = None
        if self._cache:
            cache_key = self._cache_key(url, payload)
            hit = self._cache.get(cache_key)
            if hit is not None:
                return hit

        try:
            resp = self._session.post(url, json=payload, timeout=timeout_seconds or self.timeout_seconds)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            raise OllamaError(f"Ollama generate failed ({model}): {e}") from e

        content = raw.get("response") or ""
        usage = self._usage_from_raw(raw)
        result = {"content": content, "model": model, "usage": usage.__dict__, "raw": raw}
        if self._cache and cache_key:
            self._cache.set(cache_key, result)
        return result

    def _generate_stream_impl(
        self,
        provider: str,
        prompt: str,
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ):
        if provider != "ollama":
            yield from self._chat_stream_openai_compat(
                provider=provider,
                messages=[{"role": "user", "content": prompt}],
                model=model,
                options=options,
                system=system,
                timeout_seconds=timeout_seconds,
            )
            return
        url = f"{self.host}/api/generate"
        merged_options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self.max_context_tokens,
        }
        if options:
            merged_options.update(options)

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": merged_options,
            "keep_alive": f"{max(1, self.idle_keep_alive_minutes)}m",
        }
        if system:
            payload["system"] = system

        start = time.time()
        full = []
        last_raw: Dict[str, Any] = {}
        try:
            with self._session.post(url, json=payload, timeout=timeout_seconds or self.timeout_seconds, stream=True) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    last_raw = obj
                    delta = obj.get("response") or ""
                    if delta:
                        full.append(delta)
                        yield {"type": "delta", "content": delta}
                    if obj.get("done"):
                        usage = self._usage_from_raw(obj)
                        content = "".join(full)
                        yield {
                            "type": "done",
                            "content": content,
                            "model": model,
                            "usage": usage.__dict__,
                            "elapsed_s": time.time() - start,
                            "raw": obj,
                        }
                        return
        except Exception as e:
            raise OllamaError(f"Ollama generate stream failed ({model}): {e}") from e

        usage = self._usage_from_raw(last_raw)
        yield {
            "type": "done",
            "content": "".join(full),
            "model": model,
            "usage": usage.__dict__,
            "elapsed_s": time.time() - start,
            "raw": last_raw,
        }

    def warmup(self, models: List[str], prompt: str = "Reply with OK.", timeout_seconds: int = 12) -> List[Dict[str, Any]]:
        results = []
        for model_ref in models:
            try:
                response = self.generate(
                    prompt=prompt,
                    model=model_ref,
                    fallback_models=[],
                    options={"num_predict": 16, "temperature": 0.0},
                    timeout_seconds=timeout_seconds,
                )
                results.append({"model": model_ref, "success": True, "content": response.get("content", "")[:32]})
            except Exception as e:
                results.append({"model": model_ref, "success": False, "error": str(e)})
        return results

    def _parse_model_ref(self, model: str) -> Tuple[str, str]:
        if model.startswith("ollama:"):
            return "ollama", model.split(":", 1)[1]
        if model.startswith("groq:"):
            return "groq", model.split(":", 1)[1]
        if model.startswith("openai:"):
            return "openai", model.split(":", 1)[1]
        if model.startswith("openrouter:"):
            return "openrouter", model.split(":", 1)[1]
        return "ollama", model

    def _provider_endpoint(self, provider: str) -> Tuple[str, str]:
        if provider == "groq":
            if not self.groq_api_key:
                raise OllamaError("Groq API key is not configured")
            return self.groq_base_url, self.groq_api_key
        if provider == "openai":
            if not self.openai_api_key:
                raise OllamaError("OpenAI API key is not configured")
            return self.openai_base_url, self.openai_api_key
        if provider == "openrouter":
            if not self.openrouter_api_key:
                raise OllamaError("OpenRouter API key is not configured")
            return self.openrouter_base_url, self.openrouter_api_key
        raise OllamaError(f"Unsupported provider: {provider}")

    def _chat_nonstream_openai_compat(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ) -> Dict[str, Any]:
        base_url, api_key = self._provider_endpoint(provider)
        url = f"{base_url}/chat/completions"
        merged_options: Dict[str, Any] = {"temperature": self.temperature}
        if options:
            merged_options.update(options)

        payload_messages = list(messages or [])
        if system:
            payload_messages = [{"role": "system", "content": system}, *payload_messages]
        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "stream": False,
            "temperature": merged_options.get("temperature", self.temperature),
        }
        if merged_options.get("num_predict") is not None:
            payload["max_tokens"] = int(merged_options["num_predict"])

        cache_key = None
        if self._cache:
            cache_key = self._cache_key(url, payload)
            hit = self._cache.get(cache_key)
            if hit is not None:
                return hit

        try:
            resp = self._session.post(
                url,
                json=payload,
                timeout=timeout_seconds or self.timeout_seconds,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            raise OllamaError(f"{provider} chat failed ({model}): {e}") from e

        choice = ((raw.get("choices") or [{}])[0] or {})
        message = choice.get("message") or {}
        content = self._extract_openai_content(message.get("content"))
        usage = self._usage_from_openai(raw)
        result = {"content": content, "model": f"{provider}:{model}", "usage": usage.__dict__, "raw": raw}
        if self._cache and cache_key:
            self._cache.set(cache_key, result)
        return result

    def _chat_stream_openai_compat(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        model: str,
        options: Optional[Dict[str, Any]],
        system: Optional[str],
        timeout_seconds: Optional[int],
    ) -> Generator[Dict[str, Any], None, None]:
        base_url, api_key = self._provider_endpoint(provider)
        url = f"{base_url}/chat/completions"
        merged_options: Dict[str, Any] = {"temperature": self.temperature}
        if options:
            merged_options.update(options)
        payload_messages = list(messages or [])
        if system:
            payload_messages = [{"role": "system", "content": system}, *payload_messages]
        payload: Dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "stream": True,
            "temperature": merged_options.get("temperature", self.temperature),
        }
        if merged_options.get("num_predict") is not None:
            payload["max_tokens"] = int(merged_options["num_predict"])

        start = time.time()
        full: List[str] = []
        last_raw: Dict[str, Any] = {}
        try:
            with self._session.post(
                url,
                json=payload,
                timeout=timeout_seconds or self.timeout_seconds,
                stream=True,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            ) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        usage = self._usage_from_openai(last_raw)
                        yield {
                            "type": "done",
                            "content": "".join(full),
                            "model": f"{provider}:{model}",
                            "usage": usage.__dict__,
                            "elapsed_s": time.time() - start,
                            "raw": last_raw,
                        }
                        return
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    last_raw = obj
                    delta = (((obj.get("choices") or [{}])[0] or {}).get("delta") or {}).get("content") or ""
                    if delta:
                        full.append(delta)
                        yield {"type": "delta", "content": delta}
        except Exception as e:
            raise OllamaError(f"{provider} chat stream failed ({model}): {e}") from e

        usage = self._usage_from_openai(last_raw)
        yield {
            "type": "done",
            "content": "".join(full),
            "model": f"{provider}:{model}",
            "usage": usage.__dict__,
            "elapsed_s": time.time() - start,
            "raw": last_raw,
        }

    @staticmethod
    def _extract_openai_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return ""

    @staticmethod
    def _usage_from_openai(raw: Dict[str, Any]) -> OllamaUsage:
        usage = raw.get("usage") or {}
        return OllamaUsage(
            prompt_eval_count=usage.get("prompt_tokens"),
            eval_count=usage.get("completion_tokens"),
            total_duration=usage.get("total_tokens"),
        )

    def _usage_from_raw(self, raw: Dict[str, Any]) -> OllamaUsage:
        return OllamaUsage(
            prompt_eval_count=raw.get("prompt_eval_count"),
            eval_count=raw.get("eval_count"),
            total_duration=raw.get("total_duration"),
            load_duration=raw.get("load_duration"),
        )

    def _cache_key(self, url: str, payload: Dict[str, Any]) -> str:
        canonical = json.dumps({"url": url, "payload": payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
