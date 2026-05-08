# Open-Claw / Nerve Hybrid Config

Use this when you want:

- local Ollama for coding and fixing
- OpenRouter free routing for planning and remote fallback
- deterministic prompts for Architect, Coder, Reviewer, and Fixer

```json
{
  "models": {
    "planner": {
      "provider": "openrouter",
      "model": "openrouter/free",
      "temperature": 0.2,
      "top_p": 0.9,
      "max_tokens": 2000
    },
    "coder": {
      "provider": "ollama",
      "model": "llama3.1:8b",
      "temperature": 0.1,
      "top_p": 0.9,
      "repeat_penalty": 1.1,
      "num_ctx": 8192
    },
    "fixer": {
      "provider": "ollama",
      "model": "mistral:latest",
      "temperature": 0.0,
      "top_p": 0.9,
      "num_ctx": 8192
    },
    "reviewer": {
      "provider": "ollama",
      "model": "qwen3:4b",
      "temperature": 0.1,
      "top_p": 0.9,
      "num_ctx": 8192
    }
  },
  "loop": [
    "planner",
    "coder",
    "reviewer",
    "fixer"
  ],
  "max_iterations": 6,
  "stop_condition": "no_errors_detected"
}
```

OpenRouter note:

- free availability changes over time
- `openrouter/free` is the most stable zero-cost routing option because it selects from the currently available free pool
