"""Shared decoded observation limits; transport UTF-8 budgets remain independent."""

MAX_PRODUCT_ANSWER_CHARS = 100_000

COARSE_TERMINAL_BY_SOURCE = {
    "answer": "completed",
    "refusal": "blocked",
    "permission_denied": "blocked",
    "budget_exhausted": "blocked",
    "partial": "failed",
    "tool_error": "failed",
    "agent_error": "failed",
}


class InvalidCoarseTerminalError(ValueError):
    """Keep the existing safe observation error code for invalid coarse terminals."""


def validate_terminal_pair(terminal: object, source: object) -> None:
    """Validate, never invent a missing terminal or discard a conflicting field."""
    if terminal is not None and terminal not in ("completed", "failed", "blocked"):
        raise InvalidCoarseTerminalError("invalid coarse Agent terminal")
    if source is None:
        return
    if not isinstance(source, str) or source not in COARSE_TERMINAL_BY_SOURCE:
        raise ValueError("unknown source Agent terminal")
    if terminal is not None and terminal != COARSE_TERMINAL_BY_SOURCE[source]:
        raise ValueError("conflicting Agent terminals")


def terminal_matches_expected(terminal: str | None, source: str | None, expected: str) -> bool:
    validate_terminal_pair(terminal, source)
    if terminal is None:
        return False
    if expected in ("completed", "failed", "blocked"):
        return terminal == expected
    return source == expected
