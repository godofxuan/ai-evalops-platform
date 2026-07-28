import io
import json
from typing import Any

from app.core.logging import configure_logging, get_logger


def test_structured_logging_redacts_sensitive_fields_recursively() -> None:
    output = io.StringIO()
    configure_logging(log_level="INFO", stream=output)
    logger = get_logger("security-test")

    logger.info(
        "dependency_probe_failed",
        api_key="plain-api-key",
        database_url="postgresql://user:database-password@db/evalops",
        nested={"authorization": "Bearer upstream-token", "safe": "kept"},
        outcome="error",
    )

    event: dict[str, Any] = json.loads(output.getvalue())
    assert event["event"] == "dependency_probe_failed"
    assert event["api_key"] == "[REDACTED]"
    assert event["database_url"] == "[REDACTED]"
    assert event["nested"] == {"authorization": "[REDACTED]", "safe": "kept"}
    assert event["outcome"] == "error"
