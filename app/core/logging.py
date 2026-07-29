import logging
import sys
from collections.abc import Mapping
from typing import Any, TextIO

import structlog
from structlog.stdlib import BoundLogger
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "database_url",
    "dsn",
    "answer",
    "evidence",
    "expected_answer",
    "input",
    "password",
    "prompt",
    "question",
    "redis_url",
    "response",
    "secret",
    "token",
    "trace",
}
_SENSITIVE_SUFFIXES = ("_api_key", "_password", "_secret", "_token")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else _redact_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_sensitive_fields(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    return {
        key: REDACTED if _is_sensitive_key(key) else _redact_value(value)
        for key, value in event_dict.items()
    }


def configure_logging(*, log_level: str, stream: TextIO | None = None) -> None:
    output = stream or sys.stdout
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive_fields,
    ]
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(sort_keys=True, default=str),
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(output)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None, **initial_values: Any) -> BoundLogger:
    return structlog.stdlib.get_logger(name, **initial_values)
