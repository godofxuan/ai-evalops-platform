import json
from typing import Any

import pytest

from app.cli import main


def test_worker_check_reports_lifecycle_only_capability(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["worker", "--check"])

    assert exit_code == 0
    event: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert event["event"] == "process_configuration_valid"
    assert event["role"] == "worker"
    assert event["capability"] == "lifecycle_only"
