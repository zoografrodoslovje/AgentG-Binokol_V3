# Architectural Frameworks for Fully Autonomous Software Development

This document explains a practical way to orchestrate **Devon/Devin-style local agents** (like this repo’s `AGENT_Joko`) together with the **Codex CLI** inside **Pinokio** environments.

## 1) The Goal: Autonomy Without the “Junior Dev Loop”

An autonomous engineering loop should:

- Keep moving without asking “Should I continue?” for routine steps.
- Stop only for true blockers (missing credentials, ambiguous requirements, destructive actions).
- Default to evidence: repo scan, logs, tests, and minimal-risk probes.

The “Junior Dev Loop” failure mode is when an agent:

- asks low-value questions,
- stops after partial implementation,
- or fails to run the simplest verification commands.

## 2) Pinokio as the Host Runtime (Local, Repeatable, Observable)

Pinokio provides:

- **repeatable environments** (Python, `uv`, Node, git, etc.),
- **launcher scripts** (install/start/reset/update),
- **logs** for debugging (`logs/`),
- and a consistent sandboxed workflow.

When you are editing launcher scripts, follow the workflow rules in `AGENTS.md` and the API guidance in `C:\pinokio\prototype\PINOKIO.md`.

## 3) The Two-Ecosystem Pattern: “Planner/Writer” + “Runner/Verifier”

One robust architecture is a **dual-loop**:

1. **Planner/Writer loop** (agentic reasoning and code generation)
   - local: `AGENT_Joko` (Ollama-routed roles like Architect/Coder/Tester/Fixer)
   - or external: Codex CLI “exec” sessions writing patches
2. **Runner/Verifier loop** (fast feedback)
   - run targeted commands, parse errors, iterate

The important part is *not* which agent does which role—it’s that the system can:

- apply multi-file changes,
- run a verification command,
- and iterate until “zero-error” (or a documented, intentional limitation).

## 4) Codex CLI: Non-Interactive Engine + Session Continuity

Codex CLI can run interactive or non-interactive sessions. For fully autonomous runs, use `codex exec` with:

- `-a never` to avoid approvals in the loop
- `-s workspace-write` to allow changes in the working directory
- `-C <dir>` to pin the working root

Example skeleton:

```bash
codex exec -a never -s workspace-write -C "C:\pinokio\api\AGENT_Joko" "Run tests and fix failures until green."
```

For long-running work, use session continuity:

- `codex resume --last`
- `codex fork --last`

## 5) The “Fix Loop” (Build/Test → Patch → Re-run)

The core loop can be expressed as:

1. Run the narrowest verification command that covers the change (unit tests, build, lint).
2. If it fails:
   - capture the exact error output,
   - identify root cause,
   - patch minimally,
   - re-run the same command.
3. Expand verification scope only after the narrow check is green.

Pinokio-specific debugging rule: if the failure happens inside a launcher run, inspect `logs/` first.

## 6) Vision-to-Code (Optional)

If UI mockups are provided as images, the recommended flow is:

1. Extract UI components and states (inputs, actions, navigation).
2. Map components to API routes and data models.
3. Implement UI + API + persistence together, but verify incrementally.

## 7) A Pinokio-Ready “Master Prompt”

See `prompts/MASTER_PROMPT.md` for a copy/paste prompt that:

- enforces phased execution (analyze → plan → implement → fix loop → verify),
- uses “best guess” rules,
- and includes Pinokio launcher constraints (logs-first, URL capture pattern).

