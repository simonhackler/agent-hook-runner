# Agents Hook Runner

This project contains a minimal hook runner and example workflow for local Codex
repository checks.

## Files

- `src/agents_hook_runner/`: packaged hook runner with CLI entry point
- `workflow.yaml`: example workflow that runs `npm test` in the hook working directory
- `codex-hooks.json`: example Codex `Stop` hook config pointing at this project

## Run locally

```bash
cd ~/projects/agents-hook-runner
uv sync
uv run agents-hook-runner workflow.yaml
```

## Run in hook mode

The wrapper reads hook JSON from `stdin`, resolves template values like `{{ cwd }}`,
captures child output, and emits one final block response when a step fails.

Example Codex `Stop` hook command:

```bash
uv run --project "$HOME/projects/agents-hook-runner" agents-hook-runner "$HOME/projects/agents-hook-runner/workflow.yaml" --hook
```
