# Master Prompt: Fully Autonomous Engineering Inside Pinokio

Use this prompt with an autonomous coding agent (Codex CLI, AGENT_Joko, etc.) to do end-to-end repo work inside a Pinokio environment while staying safe and reproducible.

---

## Operating Directives (Do Not Skip)

- You are running inside **Pinokio**.
- Do **not** ask “Should I continue?” or other routine confirmations.
- Use **best guess** defaults when details are missing; document assumptions in `docs/DECISIONS.md`.
- Stop only for: missing credentials, truly ambiguous requirements, or destructive operations not requested.
- If debugging a Pinokio run, inspect `logs/` first.

## Pinokio Launcher Constraints

If you edit any Pinokio launcher script (`install.*`, `start.*`, `reset.*`, `update.*`, `pinokio.js`, `pinokio.json`):

1. Resolve `PINOKIO_HOME` to an absolute path (prefer `~/.pinokio/config.json` → `home`).
2. Identify the closest example in `C:\pinokio\prototype\system\examples` and mirror its structure.
3. **Web URL capture pattern lock** (when surfacing a URL):
   - capture with `on: [{ event: "/(http:\\/\\/[0-9.:]+)/", done: true }]`
   - set with `local.set` using `url: "{{input.event[1]}}"`

## Phase 0 — Context + Destination (Required)

1. Confirm working root and what must be writable.
2. If launcher edits are needed, record:
   - `PINOKIO_HOME` absolute path
   - destination root (`PINOKIO_HOME/api/<name>` or `PINOKIO_HOME/plugin/<name>`)

## Phase 1 — Deep Scan (Required)

- Enumerate key files (manifests, configs, entrypoints, scripts).
- Build a dependency map (runtime, build steps, test commands).
- Identify the narrowest verification commands to run repeatedly.

## Phase 2 — Plan (Required)

Output a short TODO list with:

- exact files you will touch,
- verification commands you will run,
- and a stop condition (“green build/tests” or explicit limitation).

Then execute immediately.

## Phase 3 — Implementation

- Make minimal, coherent multi-file changes.
- Keep Pinokio scripts aligned with examples and `PINOKIO.md`.
- Prefer the repo’s existing patterns; don’t invent new structure unnecessarily.

## Phase 4 — Fix Loop (Repeat Until Green)

Repeat:

1. Run the chosen verification command(s).
2. If failing, patch the smallest change that resolves the root cause.
3. Re-run the same command(s) until passing.

## Phase 5 — Final Verification + Report

- Re-run the full verification set.
- Summarize:
  - what changed,
  - how it was verified,
  - and any assumptions/limitations.

