from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from agents_hook_runner.cli import main


def test_hook_mode_emits_block_json_for_failing_codex_stop_step(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "failing-codex-stop-workflow.yaml"
    )
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(
        fixture_path.read_text(encoding="utf-8").replace(
            "__PYTHON_EXECUTABLE__", sys.executable
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    exit_code = main(["agents-hook-runner", str(workflow_path), "--hook"])

    captured = capsys.readouterr()
    assert captured.err == ""
    assert exit_code == 0
    assert json.loads(captured.out) == {
        "decision": "block",
        "reason": (
            "1. [fail] The hook failed.\n"
            "   description: Intentionally fail the hook\n"
            "   stderr: boom"
        ),
    }


def test_hook_mode_returns_zero_without_output_for_passing_codex_stop_step(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "passing-codex-stop-workflow.yaml"
    )
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text(
        fixture_path.read_text(encoding="utf-8").replace(
            "__PYTHON_EXECUTABLE__", sys.executable
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    exit_code = main(["agents-hook-runner", str(workflow_path), "--hook"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
