# Pinokio Pre-flight Checklist (AGENT_Joko)

This checklist is a **task-specific** distillation of `AGENTS.md` and `C:\pinokio\prototype\PINOKIO.md`, intended for work on this launcher at `C:\pinokio\api\AGENT_Joko`.

## Before Any Edits

- [ ] **AGENTS Snapshot**: Re-open `AGENTS.md` and note which sections apply.
- [ ] **Resolve `PINOKIO_HOME`** (absolute path) and record destination root:
  - Source of truth (in order): `~/.pinokio/config.json` → `home`, then `GET http://127.0.0.1:42000/pinokio/home`, then `access` fallback, then `PINOKIO_HOME` env var.
  - App launcher destination: `PINOKIO_HOME/api/<unique_name>` (this repo: `.../api/AGENT_Joko`).
- [ ] **Example lock-in**: identify closest matching example in `C:\pinokio\prototype\system\examples` and keep it open while editing.
- [ ] **Logs-first when debugging**: if the task is “fix/debug”, inspect `logs/` (especially `logs/api/latest*`) before changing code.

## Script Safety / Structure

- [ ] Keep launcher scripts in project root (`install.*`, `start.*`, `reset.*`, `update.*`, `pinokio.js`, `pinokio.json`); keep app logic under `app/` (if any).
- [ ] Prefer Pinokio APIs (`shell.run`, `script.start`, `local.set`, `web.open`, `json.*`, `fs.*`) over ad-hoc shell glue.
- [ ] Prefer `uv` for Python installs (`uv pip install ...`) and use `venv` in `shell.run`.
- [ ] Use **relative** `path` in `shell.run` (no absolute paths).

## Critical Pattern Lock: Web URL Capture (When Applicable)

If a script needs to surface a web URL (most commonly `start.js` for a server):

- [ ] Copy the capture pattern from an example such as `C:\pinokio\prototype\system\examples\comfy\start.js`.
- [ ] Set `local.url` via `local.set` using the regex capture object from the previous `shell.run`:
  - `url: "{{input.event[1]}}"`
- [ ] Prefer the most generic regex that still reliably captures the URL.

## Exit Checklist (Before Replying)

- [ ] Re-check the checklist above and confirm every applicable item is satisfied.
- [ ] If any launcher script changed, confirm it still mirrors the chosen example’s structure (especially URL capture + `local.set`).
