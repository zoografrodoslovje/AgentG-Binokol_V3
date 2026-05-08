# AGENT_Joko – Codebase Analysis (April 2026)

This repo is a Pinokio **app launcher** at `C:\pinokio\api\AGENT_Joko` that ships:
- A local **multi-agent developer CLI** (Python)
- A local **FastAPI dashboard** (HTML/JS/CSS) with task execution + tools + streaming chat
- An **offline-first** Ollama integration (model fallback, caching, queueing)

## 1) Top-level structure

- `main.py`: CLI entrypoint (interactive + subcommands)
- `orchestrator.py`: coordinates agents, tools, memory, task queue, self-heal loop
- `config.py`: config dataclasses + load/save `.devin_agent/config.json`
- `model_router.py`: routes tasks by type/complexity to agent model mapping
- `task_queue.py`: persistent task queue `.devin_agent/task_queue.json`
- `ollama_client.py`: requests-based Ollama client (streaming, caching, fallbacks)
- `inference_queue.py`: JSON-backed offline inference queue `.devin_agent/inference_queue.json`

Subpackages:
- `agents/`: `architect`, `coder`, `tester`, `fixer`, `debator` built on `agents/base.py`
- `tools/`: file ops, shell execution, git operations
- `memory/`: JSON store + session context persistence
- `dashboard/`: FastAPI app + static UI assets

Launcher scripts:
- `install.json`: creates/uses `venv/` and installs deps via `uv pip`
- `start.json`: starts interactive CLI and auto-starts the dashboard
- `dashboard.js`: starts the dashboard server and captures URL via regex + `local.set`
- `models.json`: pulls recommended Ollama models
- `reset.json`: wipes `venv/` and `.devin_agent/` state
- `pinokio.js` / `pinokio.json`: Pinokio UI + metadata

## 2) Core runtime data flows

### CLI / Orchestrator flow
1. `main.py` builds/loads `Config` from `.devin_agent/config.json`
2. `Orchestrator` sets up:
   - agents (`agents/*`)
   - tools (`tools/*`)
   - memory (`memory/*`)
   - queues (`task_queue.py`)
3. Agents call Ollama via `OllamaClient` (through `agents/base.py`)
4. Optional git auto-commit happens if enabled in config

### Dashboard flow
1. `dashboard/server.py` runs `uvicorn` for the FastAPI app from `dashboard/api.py`
2. UI loads `dashboard/templates/index.html` + `dashboard/static/app.js/app.css`
3. UI polls `/api/status` + task endpoints and renders activity/queue/tools
4. Chat view uses `POST /api/chat/stream` which proxies Ollama streaming (NDJSON)
5. If Ollama is down, chat requests can be queued into `InferenceQueue` and replayed by a background worker when Ollama is back

## 3) Dashboard API surface (FastAPI)

Task execution:
- `GET /api/status`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/execute`
- `POST /api/tasks/{task_id}/start`
- `POST /api/tasks/{task_id}/cancel`

Tools:
- `POST /api/tools/shell`
- `POST /api/tools/python`
- `GET /api/files/list`
- `GET /api/files/read`
- `POST /api/files/write`
- `GET /api/git/status`
- `POST /api/git/commit`
- `GET /api/memory/recent`
- `GET /api/memory/search`

Ollama + offline inference:
- `GET /api/ollama/models`
- `POST /api/chat/stream` (returns `application/x-ndjson`)
- `GET /api/inference_queue`
- `GET /api/inference_queue/{item_id}`
- `POST /api/inference_queue/{item_id}/cancel`

## 4) Persistence and state

Project-local state (Pinokio-friendly):
- `.devin_agent/config.json`
- `.devin_agent/memory/*`
- `.devin_agent/task_queue.json`
- `.devin_agent/inference_queue.json`

## 5) Pinokio URL capture pattern

The dashboard launcher `dashboard.js` uses:
- `shell.run` with an `on: [{ event: "/(http:\\/\\/[0-9.:]+)/", done: true }]`
- then `local.set` with `url: "{{input.event[1]}}"`

This ensures Pinokio can surface the running dashboard URL in the UI.

