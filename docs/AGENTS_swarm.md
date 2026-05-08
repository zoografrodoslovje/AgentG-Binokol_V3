# AGENTS Swarm Scheme

Source scheme: `.pinokio-temp/AGENTS.langflow.json` and `.pinokio-temp/AGENTS.md`.

## Workflow

1. Architect designs the technical and security blueprint.
2. Coder implements the blueprint as robust Python.
3. Tester validates functionality and defensive security.
4. Fixer repairs tester failures and resubmits.
5. Debator challenges the final logic and future-proofs the result.

## Local Runtime

- Ollama endpoint: `http://127.0.0.1:11434`
- Primary model: `ollama:llama3.2:latest`
- Repair and review model: `ollama:mistral:latest`
- Optional remote fallback: `openrouter:openrouter/free`

## App Mapping

- `architect` -> `ollama:llama3.2:latest`
- `coder` -> `ollama:llama3.2:latest`
- `tester` -> `ollama:mistral:latest`
- `fixer` -> `ollama:mistral:latest`
- `debator` -> `ollama:mistral:latest`
