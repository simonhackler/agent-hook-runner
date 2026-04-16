# Agents Hook Runner

This project contains a minimal hook runner and example workflow for local Codex
repository checks.

## Files

- `src/agents_hook_runner/`: packaged hook runner with CLI entry point
- `workflow.yaml`: example workflow that runs `pyright`, `ruff check`, and `pytest` in the hook working directory
- `codex-hooks.json`: example Codex `Stop` hook config pointing at this project
- `.codex/`: live Codex hook configuration for this repository

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
uv run --project "$(git rev-parse --show-toplevel)" agents-hook-runner "$(git rev-parse --show-toplevel)/workflow.yaml" --hook
```

## Repository hook

This repository includes a live Codex hook config under `.codex/` that enables
hooks and runs the packaged CLI on `Stop`.
