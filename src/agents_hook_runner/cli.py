from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
MAX_LOG_LINES = 40
YamlTokens = list[tuple[int, str]]


class WorkflowError(Exception):
    pass


@dataclass
class StepResult:
    step_id: str
    description: str
    run: str
    args: list[str]
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    on_error: str
    spawn_error: str
    timed_out: bool


def strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False

    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index].rstrip()

    return line.rstrip()


def parse_scalar(value: str) -> Any:
    value = strip_inline_comment(value.strip())

    if not value:
        return ""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)

    return value


def tokenize_yaml(text: str) -> YamlTokens:
    tokens: YamlTokens = []

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue

        stripped = raw_line.lstrip(" ")
        if stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(stripped)
        tokens.append((indent, strip_inline_comment(stripped)))

    return tokens


def find_mapping_separator(line: str) -> int | None:
    in_single = False
    in_double = False

    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double:
            next_index = index + 1
            if next_index == len(line) or line[next_index].isspace():
                return index

    return None


def split_key_value(line: str) -> tuple[str, str | None]:
    separator_index = find_mapping_separator(line)
    if separator_index is None:
        raise WorkflowError(f"Invalid YAML mapping line: {line}")

    key = line[:separator_index].strip()
    value = line[separator_index + 1 :].strip()

    if not key:
        raise WorkflowError(f"Invalid YAML key in line: {line}")

    if not value:
        return key, None

    return key, value


def parse_yaml_node(tokens: YamlTokens, start: int, indent: int) -> tuple[Any, int]:
    if start >= len(tokens):
        raise WorkflowError("Unexpected end of YAML input")

    current_indent, current_line = tokens[start]
    if current_indent != indent:
        raise WorkflowError(
            f"Unexpected indentation at line '{current_line}': expected {indent}, got {current_indent}"
        )

    if current_line.startswith("- "):
        return parse_yaml_list(tokens, start, indent)

    return parse_yaml_mapping(tokens, start, indent)


def parse_nested_yaml_value(
    tokens: YamlTokens,
    index: int,
    *,
    parent_indent: int,
    nested_indent: int,
) -> tuple[Any, int]:
    if index < len(tokens) and tokens[index][0] > parent_indent:
        return parse_yaml_node(tokens, index, nested_indent)

    return None, index


def parse_yaml_list(tokens: YamlTokens, start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start

    while index < len(tokens):
        current_indent, current_line = tokens[index]
        if current_indent < indent:
            break
        if current_indent != indent or not current_line.startswith("- "):
            break

        item_text = current_line[2:].strip()
        index += 1

        if not item_text:
            nested, index = parse_nested_yaml_value(
                tokens,
                index,
                parent_indent=indent,
                nested_indent=indent + 2,
            )
            items.append(nested)
            continue

        if find_mapping_separator(item_text) is not None:
            key, value = split_key_value(item_text)
            item: dict[str, Any] = {}

            if value is None:
                item[key], index = parse_nested_yaml_value(
                    tokens,
                    index,
                    parent_indent=indent,
                    nested_indent=indent + 4,
                )
            else:
                item[key] = parse_scalar(value)

            while index < len(tokens):
                child_indent, child_line = tokens[index]
                if child_indent <= indent:
                    break
                if child_indent != indent + 2:
                    raise WorkflowError(
                        f"Unexpected indentation for list item near '{child_line}'"
                    )
                if child_line.startswith("- "):
                    raise WorkflowError(
                        f"Unexpected nested list item near '{child_line}'"
                    )

                child_key, child_value = split_key_value(child_line)
                index += 1
                if child_value is None:
                    item[child_key], index = parse_nested_yaml_value(
                        tokens,
                        index,
                        parent_indent=child_indent,
                        nested_indent=child_indent + 2,
                    )
                else:
                    item[child_key] = parse_scalar(child_value)

            items.append(item)
            continue

        items.append(parse_scalar(item_text))

    return items, index


def parse_yaml_mapping(tokens: YamlTokens, start: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    index = start

    while index < len(tokens):
        current_indent, current_line = tokens[index]
        if current_indent < indent:
            break
        if current_indent != indent or current_line.startswith("- "):
            break

        key, value = split_key_value(current_line)
        index += 1

        if value is None:
            mapping[key], index = parse_nested_yaml_value(
                tokens,
                index,
                parent_indent=current_indent,
                nested_indent=current_indent + 2,
            )
        else:
            mapping[key] = parse_scalar(value)

    return mapping, index


def load_yaml(path: str) -> dict[str, Any]:
    tokens = tokenize_yaml(Path(path).read_text(encoding="utf-8"))
    if not tokens:
        return {}

    document, index = parse_yaml_node(tokens, 0, tokens[0][0])
    if index != len(tokens):
        raise WorkflowError("Unexpected trailing YAML content")
    if not isinstance(document, dict):
        raise WorkflowError("Workflow YAML must be a mapping at the top level")

    return document


def load_workflow(path: str) -> dict[str, Any]:
    data = load_yaml(path)

    if "steps" not in data or not isinstance(data["steps"], list):
        raise WorkflowError("workflow must contain a 'steps' list")

    data.setdefault("name", Path(path).stem)
    data.setdefault("target", "generic")
    data.setdefault("fail_strategy", "collect-all")
    return data


def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_input": raw}


def get_value(data: dict[str, Any], key_path: str, default: str = "") -> str:
    current: Any = data

    for part in key_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    if current is None:
        return default

    if isinstance(current, str):
        return current
    if isinstance(current, (int, float, bool)):
        return str(current)

    return json.dumps(current)


def resolve_template(value: Any, hook_input: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value

    return TEMPLATE_RE.sub(lambda match: get_value(hook_input, match.group(1)), value)


def resolve_env(env: dict[str, Any] | None, hook_input: dict[str, Any]) -> dict[str, str]:
    if not env:
        return {}

    return {key: str(resolve_template(value, hook_input)) for key, value in env.items()}


def to_absolute_cwd(cwd_value: str | None, base_cwd: str) -> str:
    if not cwd_value:
        return base_cwd

    resolved = Path(cwd_value)
    if resolved.is_absolute():
        return str(resolved)

    return str(Path(base_cwd, cwd_value).resolve())


def build_step_result(
    step: dict[str, Any],
    run_command: str,
    step_args: list[str],
    *,
    ok: bool,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    spawn_error: str = "",
    timed_out: bool = False,
) -> StepResult:
    return StepResult(
        step_id=str(step["id"]),
        description=str(step.get("description", "")),
        run=run_command,
        args=step_args,
        ok=ok,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        on_error=str(step.get("on_error", f"Step '{step['id']}' failed.")),
        spawn_error=spawn_error,
        timed_out=timed_out,
    )


def run_step(
    step: dict[str, Any],
    hook_input: dict[str, Any],
    hook_mode: bool,
    base_cwd: str,
) -> StepResult:
    run_command = str(step["run"])
    step_args = [str(resolve_template(arg, hook_input)) for arg in step.get("args", [])]
    step_cwd = to_absolute_cwd(resolve_template(step.get("cwd"), hook_input), base_cwd)
    timeout_seconds = step.get("timeout_seconds")
    timeout = float(timeout_seconds) if timeout_seconds is not None else None

    try:
        completed = subprocess.run(
            [run_command, *step_args],
            cwd=step_cwd,
            env={**os.environ, **resolve_env(step.get("env"), hook_input)},
            text=True,
            capture_output=hook_mode,
            timeout=timeout,
            check=False,
        )
        return build_step_result(
            step,
            run_command,
            step_args,
            ok=(completed.returncode == 0),
            returncode=completed.returncode,
            stdout=completed.stdout.strip() if hook_mode and completed.stdout else "",
            stderr=completed.stderr.strip() if hook_mode and completed.stderr else "",
        )
    except subprocess.TimeoutExpired as error:
        return build_step_result(
            step,
            run_command,
            step_args,
            ok=False,
            returncode=1,
            stdout=normalize_subprocess_output(error.stdout) if hook_mode else "",
            stderr=normalize_subprocess_output(error.stderr) if hook_mode else "",
            timed_out=True,
        )
    except OSError as error:
        return build_step_result(
            step,
            run_command,
            step_args,
            ok=False,
            returncode=1,
            spawn_error=str(error),
        )


def format_failures(results: list[StepResult]) -> str:
    failed = [result for result in results if not result.ok]
    lines: list[str] = []

    for index, result in enumerate(failed, start=1):
        lines.append(f"{index}. [{result.step_id}] {result.on_error}")

        if result.description:
            lines.append(f"   description: {result.description}")

        if result.timed_out:
            lines.append("   error: step timed out")
        elif result.spawn_error:
            lines.append(f"   error: {result.spawn_error}")
        elif result.stderr:
            lines.append(f"   stderr: {summarize_output(result.stderr)}")
        elif result.stdout:
            lines.append(f"   stdout: {summarize_output(result.stdout)}")

    return "\n".join(lines)


def summarize_output(output: str) -> str:
    if not output:
        return ""

    lines = output.splitlines()
    if len(lines) <= MAX_LOG_LINES:
        return output

    tail = "\n".join(lines[-MAX_LOG_LINES:])
    return f"[truncated to last {MAX_LOG_LINES} lines]\n{tail}"


def normalize_subprocess_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace").strip()
    return output.strip()


def emit_hook_result(target: str, message: str) -> int:
    if target == "codex-pretool":
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": message,
                    }
                }
            )
        )
        return 0

    if target == "codex-stop":
        print(json.dumps({"decision": "block", "reason": message}))
        return 0

    if target == "claude":
        print(message, file=sys.stderr)
        return 2

    print(message, file=sys.stderr)
    return 1


def parse_args(argv: list[str]) -> tuple[str, bool]:
    if len(argv) < 2:
        raise WorkflowError(
            "Usage: agents-hook-runner <workflow.yaml> [--hook]"
        )

    workflow_path = str(Path(argv[1]).resolve())
    hook_mode = "--hook" in argv[2:]
    return workflow_path, hook_mode


def build_hook_input(
    workflow_path: str,
    hook_mode: bool,
    base_cwd: str,
) -> dict[str, Any]:
    hook_input = {
        "cwd": base_cwd,
        "workflow_path": workflow_path,
        "workflow_dir": str(Path(workflow_path).parent),
    }
    if hook_mode:
        hook_input.update(read_hook_input())
    return hook_input


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv
    workflow_path, hook_mode = parse_args(args)
    workflow = load_workflow(workflow_path)
    base_cwd = os.getcwd()
    hook_input = build_hook_input(workflow_path, hook_mode, base_cwd)

    results: list[StepResult] = []

    for step in workflow["steps"]:
        if not step.get("id") or not step.get("run"):
            raise WorkflowError("each workflow step must contain 'id' and 'run'")

        result = run_step(step, hook_input, hook_mode, base_cwd)
        results.append(result)

        if not result.ok and workflow["fail_strategy"] == "stop-first":
            break

    if all(result.ok for result in results):
        return 0

    message = format_failures(results)

    if hook_mode:
        return emit_hook_result(str(workflow["target"]), message)

    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkflowError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
