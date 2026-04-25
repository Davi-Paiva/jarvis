from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.openai_client import TaskImplementationResult


def test_task_implementation_result_drops_non_command_test_placeholders():
    result = TaskImplementationResult(
        result_summary="done",
        test_command="No tests run (inspection only).",
    )

    assert result.test_command is None


def test_task_implementation_result_keeps_real_test_command():
    result = TaskImplementationResult(
        result_summary="done",
        test_command="pytest tests/test_api.py",
    )

    assert result.test_command == "pytest tests/test_api.py"
