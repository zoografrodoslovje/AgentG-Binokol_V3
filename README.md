---
title: AgentG Binokol V3
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
license: mit
app_port: 7860
---
# AGENT_Joko

Hybrid local AI developer app for Pinokio.

It uses:

- `Ollama` for execution-heavy local roles
- local `Ollama` models for the five-agent swarm, with OpenRouter kept as an optional fallback
- a FastAPI dashboard for tasks, chat, memory, queue, and safe command execution

## Current Model Layout

- `architect` -> `ollama:llama3.2:latest`
- `coder` -> `ollama:llama3.2:latest`
- `tester` -> `ollama:mistral:latest`
- `fixer` -> `ollama:mistral:latest`
- `debator` -> `ollama:mistral:latest`
- local chat default -> `ollama:llama3.2:latest`
- fallback chain -> `ollama:mistral:latest`, `ollama:llama3.2:latest`, then `openrouter:openrouter/free`

This mirrors the attached AGENTS Langflow scheme: Architect -> Coder -> Tester -> Fixer -> Debator, backed by local Ollama models.

## Pinokio Use

1. Run `Install`
2. Run `Pull Ollama Models`
3. Run `Start (Interactive)`
4. Open `Dashboard`

Startup behavior:

- the dashboard starts automatically
- configured models warm up in the background
- the dashboard shell tool only allows commands from the built-in safe allow-list

## Environment

Use OpenRouter as the OpenAI-compatible remote provider:

```bat
set OPENROUTER_API_KEY=your_key_here
set OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
set OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

`OPENAI_BASE_URL` is also accepted for compatibility with existing tooling.

## Ready-To-Paste Hybrid Config

```json
{
  "ollama_host": "http://localhost:11434",
  "models": {
    "architect": "ollama:llama3.2:latest",
    "coder": "ollama:llama3.2:latest",
    "tester": "ollama:mistral:latest",
    "fixer": "ollama:mistral:latest",
    "debator": "ollama:mistral:latest",
    "fallback": "ollama:mistral:latest"
  },
  "ollama_primary_model": "ollama:llama3.2:latest",
  "ollama_fallback_models": [
    "ollama:mistral:latest",
    "ollama:llama3.2:latest",
    "openrouter:openrouter/free"
  ],
  "ollama_max_context_tokens": 8192,
  "ollama_temperature": 0.1,
  "ollama_timeout_seconds": 60,
  "ollama_healing_timeout_seconds": 20,
  "ollama_healing_max_tokens": 1024,
  "openrouter_enabled": true,
  "openrouter_base_url": "https://openrouter.ai/api/v1",
  "model_warmup_enabled": true,
  "model_warmup_timeout_seconds": 20,
  "model_warmup_prompt": "Reply with OK only.",
  "allowed_commands": [
    "npm install",
    "npm run dev",
    "npm run build",
    "python",
    "pip install",
    "pip3 install",
    "uv pip install",
    "node",
    "git init",
    "git add .",
    "git commit -m",
    "git status",
    "dir",
    "ls",
    "ollama pull",
    "ollama rm"
  ],
  "blocked_commands": [
    "rm -rf",
    "del /f",
    "shutdown",
    "format",
    "powershell remove-item",
    "curl | sh",
    "wget | sh"
  ]
}
```

## Agent Prompts

### Architect

```text
You are the Architect agent.

Your job:
- Break the user request into clear steps
- Define file structure
- Specify exact files to create or edit
- Output commands to run

Rules:
- Output JSON only
- Be deterministic and structured
- No explanations
```

### Coder

```text
You are the Coder agent.

Your job:
- Create or edit files exactly as instructed
- Follow file paths strictly

Rules:
- Output only code or file content
- If editing, output the full file
- No explanations
- No markdown
```

### Fixer

```text
You are the Fixer agent.

Your job:
- Analyze errors
- Fix broken code
- Improve reliability

Rules:
- Output full corrected files
- Do not explain unless necessary
- Keep changes minimal
```

### Tester

```text
You are the Tester agent.

Your job:
- Validate functionality and scope compliance
- Test malformed input, timeouts, and 403/429 handling
- Log reproducible failures for Fixer

Rules:
- Report pass/fail evidence
- Include exact reproduction steps for failures
```

### Debator

```text
You are the Debator agent.

Your job:
- Review final output for hidden flaws and edge cases
- Challenge assumptions, ethics, OPSEC, and long-term risks
- Suggest safer or simpler alternatives before approval
```

## API

### JavaScript

```js
const res = await fetch("http://127.0.0.1:8000/api/execute", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    goal: "Create a Node.js Express API with one endpoint /hello",
    workflow: "full"
  })
});

const data = await res.json();
console.log(data.task_id);
```

### Python

```python
import requests

response = requests.post(
    "http://127.0.0.1:8000/api/execute",
    json={
        "goal": "Create a Node.js Express API with one endpoint /hello",
        "workflow": "full",
    },
    timeout=30,
)
response.raise_for_status()
print(response.json())
```

### Curl

```bash
curl -X POST http://127.0.0.1:8000/api/execute \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"Create a Node.js Express API with one endpoint /hello\",\"workflow\":\"full\"}"
```

### Useful Endpoints

- `GET /api/status`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/retry`
- `POST /api/chat/stream`
- `GET /api/ollama/models`
- `POST /api/tools/shell`
- `POST /api/tools/python`

## Notes

- `models.json` removes this app's legacy local models before pulling the current set.
- `update.json` refreshes Python dependencies and resyncs the local Ollama models.
- `dashboard.js` follows the required Pinokio URL capture pattern and exposes the dashboard URL through `local.set`.
